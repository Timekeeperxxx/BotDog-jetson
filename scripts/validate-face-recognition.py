#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import statistics
import sys
import time

import numpy as np

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from backend.config import settings
from backend.face_recognition.engine import FaceRecognitionEngine
from backend.face_recognition.matcher import FaceMatcher, FaceTemplateRecord


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    index = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * fraction))))
    return ordered[index]


def main() -> int:
    parser = argparse.ArgumentParser(description="运行 YuNet/SFace 合成人脸验收")
    parser.add_argument("--iterations", type=int, default=12)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    fixtures = PROJECT_ROOT / "tests" / "fixtures" / "face_recognition"
    detect_model = Path(settings.FACE_DETECT_MODEL_PATH)
    recognition_model = Path(settings.FACE_RECOGNITION_MODEL_PATH)
    engine = FaceRecognitionEngine(
        str(detect_model),
        str(recognition_model),
        detect_threshold=settings.FACE_DETECT_THRESHOLD,
        min_face_size=settings.FACE_MIN_SIZE_PX,
    )
    load_started = time.perf_counter()
    engine.load()
    load_ms = (time.perf_counter() - load_started) * 1000

    images = {
        name: engine.decode_image((fixtures / f"{name}.png").read_bytes())
        for name in ("known_person", "unknown_person")
    }
    extractions = {name: engine.extract_exactly_one(image) for name, image in images.items()}
    matcher = FaceMatcher(settings.FACE_MATCH_THRESHOLD)
    matcher.replace([
        FaceTemplateRecord(1, 1, "测试人员A", extractions["known_person"].embedding)
    ])
    known_match = matcher.match(extractions["known_person"].embedding)
    unknown_match = matcher.match(extractions["unknown_person"].embedding)

    durations_ms: list[float] = []
    for index in range(max(1, args.iterations)):
        image = images["known_person" if index % 2 == 0 else "unknown_person"]
        started = time.perf_counter()
        engine.extract_exactly_one(image)
        durations_ms.append((time.perf_counter() - started) * 1000)

    matcher.replace([])
    after_delete = matcher.match(extractions["known_person"].embedding)
    report = {
        "result": "passed" if known_match.matched and not unknown_match.matched and not after_delete.matched else "failed",
        "models": {
            "yunet": {"path": str(detect_model), "sha256": sha256(detect_model)},
            "sface": {"path": str(recognition_model), "sha256": sha256(recognition_model)},
        },
        "settings": {
            "detect_threshold": settings.FACE_DETECT_THRESHOLD,
            "match_threshold": settings.FACE_MATCH_THRESHOLD,
            "frame_skip": settings.FACE_FRAME_SKIP,
            "confirm_hits": settings.FACE_CONFIRM_HITS,
            "frame_timeout_ms": settings.AI_FRAME_PROCESS_TIMEOUT_SECONDS * 1000,
        },
        "known": {
            "display_name": known_match.display_name,
            "matched": known_match.matched,
            "score": round(known_match.score, 6),
            "detect_score": round(extractions["known_person"].detection_score, 6),
            "bbox": list(extractions["known_person"].bbox),
        },
        "unknown": {
            "matched": unknown_match.matched,
            "score": round(unknown_match.score, 6),
            "detect_score": round(extractions["unknown_person"].detection_score, 6),
            "bbox": list(extractions["unknown_person"].bbox),
        },
        "after_template_delete_matched": after_delete.matched,
        "performance_ms": {
            "model_load": round(load_ms, 2),
            "iterations": len(durations_ms),
            "mean": round(statistics.mean(durations_ms), 2),
            "p50": round(percentile(durations_ms, 0.50), 2),
            "p95": round(percentile(durations_ms, 0.95), 2),
            "max": round(max(durations_ms), 2),
        },
    }
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if report["result"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
