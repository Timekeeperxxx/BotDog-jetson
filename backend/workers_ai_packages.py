"""Backpack inference and evidence integration; no motion-control calls."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path
import time

import numpy as np

from .abandoned_package import PACKAGE_LABELS, PackageConfig, PackageObservationService
from .alert_timing import observation_timing
from .config import settings
from .logging_config import get_logger

log = get_logger("遗弃包裹识别")


@dataclass
class PackageDetection:
    label: str
    confidence: float
    bbox: tuple[int, int, int, int]
    track_id: int = -1
    source: str = "full"
    package_state: str = "unknown"
    unattended_seconds: float | None = None


class BackpackDetector:
    def __init__(self, path, device, confidence, imgsz, width, height, *,
                 refine=False, include_luggage=False, max_refine_crops=6, roi_reviewer=None):
        # Never download a missing model in the live backend startup path.
        if not Path(path).is_file():
            raise FileNotFoundError(f"背包检测模型不存在：{path}")
        if not 1 <= max_refine_crops <= 8:
            raise ValueError("局部复核区域数量必须为1至8")
        from ultralytics import YOLO
        if device == "auto":
            import torch
            device = "cuda:0" if torch.cuda.is_available() else "cpu"
        self.model = YOLO(path, task="detect")
        names = self.model.names
        self.names = dict(enumerate(names)) if isinstance(names, list) else names
        if not PACKAGE_LABELS.intersection(self.names.values()):
            raise ValueError("包裹支路需要至少包含一个包类的检测模型")
        self.target_labels = PACKAGE_LABELS if include_luggage else {"backpack"}
        self.classes = [int(k) for k, v in self.names.items()
                        if v in (PACKAGE_LABELS if refine else self.target_labels)]
        self.bag_classes = [int(k) for k, v in self.names.items() if v in PACKAGE_LABELS]
        self.device, self.confidence, self.imgsz = device, confidence, imgsz
        self.review_confidence = min(.25, confidence)
        self.width, self.height = width, height
        self.refine, self.include_luggage = refine, include_luggage
        self.max_refine_crops = max_refine_crops
        self.roi_reviewer = roi_reviewer
        self.whole_frame_context = {"table", "bin"}.issubset(self.names.values())
        if self.whole_frame_context and refine:
            raise ValueError("整图背景区分类模型必须关闭 PACKAGE_REFINE_ENABLED，不能使用弱候选局部放大")
        if self.whole_frame_context and roi_reviewer is not None:
            raise ValueError("整图背景区分类模型必须关闭 PACKAGE_REVIEW_ENABLED，不能叠加旧局部复核")
        self.context_classes = [int(k) for k, v in self.names.items()
                                if v in PACKAGE_LABELS or v in {"chair", "table", "bin"}]
        self.last_status = {}

    @staticmethod
    def _deduplicate(detections):
        # Bag-family NMS preserves the winning model label and confidence;
        # duplicate labels of the same object must not create multiple alerts.
        kept = []
        for detection in sorted(detections, key=lambda d: d.confidence, reverse=True):
            a = detection.bbox
            duplicate = False
            for previous in kept:
                b = previous.bbox
                inter = max(0., min(a[2], b[2])-max(a[0], b[0])) * max(
                    0., min(a[3], b[3])-max(a[1], b[1]))
                union = (a[2]-a[0])*(a[3]-a[1])+(b[2]-b[0])*(b[3]-b[1])-inter
                if union > 0 and inter/union >= .5:
                    duplicate = True
                    break
            if not duplicate:
                kept.append(detection)
        return kept

    def _predict(self, image, classes, confidence, *, offset=(0, 0), source="full"):
        if not classes:
            return []
        # Match the square letterbox used by the static TensorRT engine in both modes.
        options = {"classes": classes}
        if self.whole_frame_context:
            # Background classes must compete before they are filtered from alarm candidates.
            options = {"classes": self.context_classes, "agnostic_nms": True, "iou": .5}
        results = self.model.predict(image, device=self.device, conf=confidence,
                                     imgsz=self.imgsz, rect=False, verbose=False, **options)
        detections = []
        h, w = image.shape[:2]
        for result in results:
            if hasattr(result.boxes, "data"):
                rows = result.boxes.data.detach().cpu().tolist()
            else:
                rows = [box.xyxy[0].tolist() + [float(box.conf[0]), int(box.cls[0])]
                        for box in result.boxes]
            for row in rows:
                # Confidence/class remain the final columns when a track ID is present.
                class_id = int(row[-1])
                label = self.names.get(class_id)
                if class_id not in classes or label not in PACKAGE_LABELS:
                    continue
                values = row[:4]
                score = float(row[-2])
                if not np.isfinite([*values, score]).all():
                    continue
                x1, y1, x2, y2 = values
                coordinates = (max(0., x1), max(0., y1), min(float(w), x2), min(float(h), y2))
                if coordinates[2] <= coordinates[0] or coordinates[3] <= coordinates[1]:
                    continue
                coordinates = tuple(v+offset[i % 2] for i, v in enumerate(coordinates))
                detections.append(PackageDetection(label, score, coordinates, source=source))
        return detections

    def detect_many(self, frame):
        image = np.frombuffer(frame, dtype=np.uint8).reshape(self.height, self.width, 3)
        # Low scores propose regions only; every returned observation still has
        # the normal confidence threshold and comes from the current frame.
        proposal_confidence = min(.05, self.confidence) if self.refine else self.confidence
        raw = self._predict(image, self.classes, proposal_confidence)
        bag_candidates = [d for d in raw if d.label in PACKAGE_LABELS]
        proposals = self._deduplicate(bag_candidates) if self.refine or self.include_luggage else bag_candidates
        # Raising the final cutoff must not consume extra slots in the fixed crop budget.
        review_threshold = self.review_confidence if self.refine else self.confidence
        bags = [d for d in proposals if d.label in self.target_labels and d.confidence >= review_threshold]
        regions = []
        if self.refine:
            uncertain = [d for d in proposals if d.label != "backpack" or d.confidence < self.review_confidence]
            for detection in uncertain[:self.max_refine_crops]:
                a, c, e, g = detection.bbox
                cx, cy = (a+e)/2, (c+g)/2
                # Generic 3x proposal context; no scene-specific region or
                # cached/manual target coordinates are used in inference.
                x1, x2 = max(0, round(cx-(e-a)*1.5)), min(self.width, round(cx+(e-a)*1.5))
                y1, y2 = max(0, round(cy-(g-c)*1.5)), min(self.height, round(cy+(g-c)*1.5))
                if x2-x1 < 4 or y2-y1 < 4:
                    continue
                regions.append((x1, y1, x2, y2))
                verified = self._predict(image[y1:y2, x1:x2], self.bag_classes,
                                         self.review_confidence, offset=(x1, y1), source="refined")
                bags.extend(d for d in verified if d.label in self.target_labels
                            and d.confidence >= self.review_confidence)
        result = self._deduplicate(bags) if self.refine or self.include_luggage else bags
        result = [d for d in result if d.confidence >= self.confidence]
        for detection in result:
            detection.bbox = tuple(int(v) for v in detection.bbox)
        self.last_status = {"refine_enabled": self.refine, "include_luggage": self.include_luggage,
                            "final_confidence": self.confidence, "review_confidence": self.review_confidence,
                            "proposal_count": len(raw), "package_candidate_count": len(bag_candidates),
                            "accepted_before_roi": len(result),
                            "regions_evaluated": 1+len(regions), "refine_regions": regions,
                            "whole_frame_context": self.whole_frame_context}
        if self.roi_reviewer is not None:
            result = self.roi_reviewer.filter(image, result)
            self.last_status["roi_review"] = dict(self.roi_reviewer.last_status)
        self.last_status["accepted_after_roi"] = len(result)
        return result


class _PackageEventBatch(list):
    """Keep the producing generation through the main frame's other awaits."""

    def __init__(self, events, generation):
        super().__init__(events)
        self.generation = generation


class PackageWorkerMixin:
    def _initialize_packages(self):
        self._package_switch_lock = asyncio.Lock()
        self._package_generation = 0
        self._package_enabled = False
        self._package_error = None
        self._package_detector = None
        self._package_service = None
        self._package_warmed_up = False
        self._package_updated = False
        self._package_status = "disabled"
        self._last_package_at = None
        self._package_observation_gap_ms = None
        self._package_overlap_cleared_track_ids = []
        self._last_package_ms = 0.0
        self._package_events_count = 0
        self._package_frames_processed = 0
        self._package_reset_pending = False
        if not settings.PACKAGE_ENABLED or settings.AI_SIMULATE_DETECTION:
            settings.PACKAGE_ENABLED = False
            return
        try:
            self._package_detector, self._package_service = self._create_package_components()
            self._package_enabled = True
            self._package_status = "ready"
        except Exception as exc:
            settings.PACKAGE_ENABLED = False
            self._package_status = "failed"
            self._package_error = str(exc)
            log.error("背包支路加载失败：{}",exc)

    def _create_package_components(self):
        # Thread-local construction only: never publish partially loaded objects
        # or initialize unrelated detectors from the model-loading thread.
        roi_reviewer = None
        if settings.PACKAGE_REVIEW_ENABLED:
            from .package_roi_review import PackageRoiReviewer
            roi_reviewer = PackageRoiReviewer(settings.PACKAGE_REVIEW_MODEL_PATH,
                settings.PACKAGE_REVIEW_METADATA_PATH, settings.PACKAGE_DEVICE)
        detector = BackpackDetector(
            settings.PACKAGE_MODEL_PATH, settings.PACKAGE_DEVICE,
            settings.PACKAGE_CONFIDENCE_THRESHOLD, settings.PACKAGE_INFERENCE_IMGSZ,
            self._frame_width, self._frame_height,
            refine=settings.PACKAGE_REFINE_ENABLED,
            include_luggage=settings.PACKAGE_INCLUDE_LUGGAGE,
            max_refine_crops=settings.PACKAGE_REFINE_MAX_CROPS,
            roi_reviewer=roi_reviewer)
        service = PackageObservationService(PackageConfig(
            confirm_seconds=settings.PACKAGE_CONFIRM_SECONDS,
            max_gap_seconds=settings.PACKAGE_MAX_GAP_SECONDS,
        ), self._frame_width, self._frame_height)
        return detector, service

    @property
    def package_detection_enabled(self):
        return bool(self._package_enabled and settings.PACKAGE_ENABLED
                    and self._package_detector is not None and self._package_service is not None)

    def _package_generation_is_current(self, generation):
        return self.package_detection_enabled and generation == self._package_generation

    def _retire_package_generation(self, state="disabled", error=None):
        self._package_generation += 1
        self._package_enabled = False
        settings.PACKAGE_ENABLED = False
        # A to_thread call cannot be killed. Detach its objects instead of
        # resetting/reusing a service that may still be accumulating old frames.
        self._package_detector = None
        self._package_service = None
        self._package_warmed_up = False
        self._package_updated = True
        self._package_reset_pending = False
        self._last_package_at = None
        self._package_observation_gap_ms = None
        self._package_overlap_cleared_track_ids = []
        self._last_package_ms = 0.0
        self._package_frames_processed = 0
        self._package_events_count = 0
        self._package_status = state
        self._package_error = error

    async def set_package_detection_enabled(self, enabled: bool) -> bool:
        # Also used for the final event dispatch, so disabling cannot finish
        # while an already admitted event is committing/broadcasting.
        async with self._package_switch_lock:
            if enabled and self.package_detection_enabled:
                return True
            self._retire_package_generation("loading" if enabled else "disabled")
            if not enabled:
                return False
            try:
                if settings.AI_SIMULATE_DETECTION:
                    raise ValueError("模拟模式不支持包模型检测")
                detector, service = await self._run_inference(
                    "背包模型加载", self._create_package_components)
                # The hot-loaded detector is private until warmup succeeds.
                # Match the board's existing eight-second warmup budget.
                await asyncio.wait_for(
                    self._run_inference("背包预热", detector.detect_many,
                                        bytes(self._frame_width * self._frame_height * 3)),
                    timeout=8.0)
            except asyncio.CancelledError:
                self._retire_package_generation("failed", "包模型加载已取消")
                raise
            except Exception as exc:
                message = "包模型预热超时（8秒）" if isinstance(exc, asyncio.TimeoutError) else f"包模型加载失败：{exc}"
                self._retire_package_generation("failed", message)
                log.error("{}", message)
                raise ValueError(message) from exc
            self._package_detector, self._package_service = detector, service
            self._package_warmed_up = True
            self._package_enabled = True
            settings.PACKAGE_ENABLED = True
            self._package_status = "ready"
            return True

    def _package_status_payload(self):
        return {"state": self._package_status,
                "enabled": self.package_detection_enabled,
                "error": self._package_error,
                "processing_ms": self._last_package_ms,
                "frames_processed": self._package_frames_processed,
                "events_count": self._package_events_count,
                "observation_gap_ms": self._package_observation_gap_ms,
                "detector": dict(getattr(self._package_detector, "last_status", {})) if self._package_detector else None,
                "observation": self._package_service.get_status() if self._package_service else None}

    @staticmethod
    def _package_person_observations(detections):
        if detections is None:
            return None
        persons = []
        for detection in detections:
            if detection.label != "person":
                continue
            try:
                bbox = tuple(detection.bbox)
                if (len(bbox) != 4 or not np.isfinite([*bbox, detection.confidence]).all()
                        or bbox[2] <= bbox[0] or bbox[3] <= bbox[1]):
                    return None
            except (TypeError, ValueError):
                return None
            persons.append(PackageDetection("person", detection.confidence, bbox,
                                            track_id=detection.track_id, source="main"))
        return persons

    async def _maybe_infer_packages(self,frame,observed_at,person_detections=None):
        """None means unknown people; [] means a valid current-frame absence."""
        self._last_package_ms = 0.0
        self._package_updated = False
        self._package_overlap_cleared_track_ids = []
        if not self.package_detection_enabled:
            self._package_updated = True
            return [],[]
        generation = self._package_generation
        detector, service = self._package_detector, self._package_service
        persons = self._package_person_observations(person_detections)
        if persons is None:
            # Mark even an unsampled frame, so confirmation cannot bridge an
            # unknown observation. Reset only after in-flight work has ended.
            self._package_reset_pending = True
            self._package_status = "person_observation_unknown"
            self._package_updated = True
        if (self._last_package_at is not None
                and observed_at-self._last_package_at < settings.PACKAGE_INTERVAL_SECONDS):
            return [],[]
        self._package_updated = True
        self._package_observation_gap_ms = (round((observed_at-self._last_package_at)*1000, 1)
                                            if self._last_package_at is not None else None)
        self._last_package_at = observed_at
        started = time.monotonic()
        try:
            # Sequential GPU work avoids adding another concurrent TensorRT
            # context. The existing single-frame timeout still applies.
            detections = await self._run_inference("背包检测",detector.detect_many,frame)
            if not self._package_generation_is_current(generation):
                return [],[]
            bags = [d for d in detections if d.label in PACKAGE_LABELS]
            for bag in bags:
                bag.package_state = "unknown"
                bag.unattended_seconds = None
            if self._package_reset_pending:
                service.reset("person_observation_unknown" if persons is None else "stream_reset")
                self._package_reset_pending = False
            if persons is None:
                # Current bag boxes can be previewed, but no absence is inferred.
                return [],bags
            events, bags = await self._run_inference(
                "包裹时序",service.process_frame,frame,[*bags,*persons],observed_at)
            if not self._package_generation_is_current(generation):
                return [],[]
            # This frame's status owns the persistent latch, not the one-shot events
            # or the timer (which can restart after a brief missed detection).
            observation_status = service.get_status()
            self._package_overlap_cleared_track_ids = list(
                observation_status.get("overlap_cleared_track_ids", []))
            tracks_by_id = {track["track_id"]: track
                            for track in observation_status.get("tracks", [])}
            for bag in bags:
                if bag.label not in PACKAGE_LABELS:
                    continue
                track = tracks_by_id.get(bag.track_id)
                bag.package_state = track["state"] if track is not None else "unknown"
                bag.unattended_seconds = track["unattended_seconds"] if track is not None else None
            self._package_frames_processed += 1
            self._package_status = "ready"
            return _PackageEventBatch(events, generation),bags
        except Exception as exc:
            if self._package_generation_is_current(generation):
                self._package_status = "failed"
                self._package_reset_pending = True
                log.error("背包支路处理失败：{}",exc)
            return [],[]
        finally:
            if self._package_generation_is_current(generation):
                self._last_package_ms = round((time.monotonic()-started)*1000,1)

    async def _process_package_events(self,events,frame):
        generation = getattr(events, "generation", None)
        if not self._package_generation_is_current(generation):
            return
        from .alert_service import get_alert_service
        for event in events:
            if not self._package_generation_is_current(generation):
                return
            image_path,image_url = await self._save_snapshot(frame)
            if not self._package_generation_is_current(generation):
                return
            gps = self._get_latest_gps()
            async with self._session_factory() as session:
                async with self._package_switch_lock:
                    if not self._package_generation_is_current(generation):
                        return
                    evidence = await get_alert_service().handle_ai_event(
                        event_type="PACKAGE_ABANDONED",event_code="E_PACKAGE_ABANDONED",
                        severity="WARNING",message=("发现疑似遗弃双肩包" if event.label == "backpack" else
                            "发现疑似遗弃包裹（模型分类："+{"handbag":"手提包","suitcase":"行李箱",
                                "luggage":"行李","parcel":"包裹"}.get(event.label,event.label)+"）"),
                        confidence=event.confidence,file_path=str(image_path),image_url=image_url,
                        gps_lat=gps[0],gps_lon=gps[1],
                        task_id=self._current_task_id if isinstance(self._current_task_id,int) else None,
                        session=session,track_id=event.track_id,owner_track_id=event.owner_id,
                        bbox=list(event.bbox),object_label=event.label,observation_policy="no_person_overlap",
                        frame_received_at_monotonic=event.observed_at,
                        timing=observation_timing(event.observed_at,duration=event.duration_seconds,
                            threshold=settings.PACKAGE_CONFIRM_SECONDS,source="package_no_overlap_window"),
                        event_guard=lambda: self._package_generation_is_current(generation))
                    if evidence is not None:
                        self._package_events_count += 1
