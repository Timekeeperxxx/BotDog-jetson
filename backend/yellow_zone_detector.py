"""
独立黄色+黑边区域检测模块（阶段 1）。

与 GuardMissionService 完全解耦，只负责：
  1. HSV 分割纯黄色区域
  2. 形态学闭+开运算
  3. 轮廓筛选（面积 / 位置 / 长宽比 / 饱满度）
  4. minAreaRect 拟合四边形
  5. 黑边验证（四边形外扩采样，V 通道均值要低）
  6. 输出 ZoneDetection 数据类，含 polygon / bbox / center / area / angle / quality

所有可调参数均从 .env（通过 config.Settings）读取，无硬编码常量。
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple

from .logging_config import logger


@dataclass
class ZoneDetection:
    """单帧区域检测结果。"""
    polygon: np.ndarray              # shape (4, 2)，顺时针四边形顶点
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)  轴对齐外接矩形
    center: Tuple[int, int]          # (cx, cy)  区域中心
    area: float                      # 像素面积（轮廓面积）
    angle: float                     # minAreaRect 旋转角度（度）
    quality: float                   # 综合质量分（含汉字奖励后可超过 1.0）
    border_ok: bool                  # 黑边验证是否通过
    has_center_text: bool = field(default=False)          # 中心是否检测到黑色汉字
    # 供调试的原始分量
    area_score: float = field(default=0.0, repr=False)
    solid_score: float = field(default=0.0, repr=False)
    border_score: float = field(default=0.0, repr=False)
    center_text_score: float = field(default=0.0, repr=False)  # 中心暗像素密度


class YellowZoneDetector:
    """
    独立的黄色防区检测器。所有检测参数从 .env 读取。

    用法::
        detector = YellowZoneDetector(frame_width=1280, frame_height=720)
        zone: Optional[ZoneDetection] = detector.detect(frame_bytes)
    """

    def __init__(self, frame_width: int, frame_height: int):
        self._frame_width  = frame_width
        self._frame_height = frame_height
        self._frame_area   = frame_width * frame_height
        # 丢失帧计数（供 GuardMissionService.get_status 查询）
        self._lost_frames_count: int = 0

        # ── 从 .env / Settings 读取所有可调参数 ──────────────────────
        from .config import get_settings
        cfg = get_settings()

        # HSV 颜色范围
        self._h_low  = cfg.ZONE_YELLOW_H_LOW
        self._h_high = cfg.ZONE_YELLOW_H_HIGH
        self._s_low  = cfg.ZONE_YELLOW_S_LOW
        self._s_high = cfg.ZONE_YELLOW_S_HIGH
        self._v_low  = cfg.ZONE_YELLOW_V_LOW
        self._v_high = cfg.ZONE_YELLOW_V_HIGH

        # 黑边验证
        self._border_v_threshold = cfg.ZONE_BORDER_V_THRESHOLD
        self._border_expand_px   = cfg.ZONE_BORDER_EXPAND_PX

        # 面积约束
        self._min_area_px    = cfg.ZONE_MIN_AREA_PX
        self._max_area_ratio = cfg.ZONE_MAX_AREA_RATIO

        # 形状约束
        self._min_aspect  = cfg.ZONE_MIN_ASPECT
        self._max_aspect  = cfg.ZONE_MAX_ASPECT
        self._min_solidity = cfg.ZONE_MIN_SOLIDITY

        # ROI 与形态学
        self._roi_top_ratio    = cfg.ZONE_ROI_TOP_RATIO
        self._morph_kernel_size = cfg.ZONE_MORPH_KERNEL_SIZE

        # quality 权重
        self._w_area   = cfg.ZONE_W_AREA
        self._w_solid  = cfg.ZONE_W_SOLID
        self._w_border = cfg.ZONE_W_BORDER

        # 中心黑色汉字检测参数
        self._center_crop_ratio        = cfg.ZONE_CENTER_CROP_RATIO
        self._center_black_v_threshold = cfg.ZONE_CENTER_BLACK_V_THRESHOLD
        self._center_black_min_ratio   = cfg.ZONE_CENTER_BLACK_MIN_RATIO
        self._center_text_bonus        = cfg.ZONE_CENTER_TEXT_BONUS

    # ─── 公开接口 ──────────────────────────────────────────────────

    def detect(self, frame: bytes) -> Optional[ZoneDetection]:
        """
        对单帧 BGR 裸字节执行完整检测管线。

        Returns:
            ZoneDetection 或 None（无合格候选时）
        """
        try:
            import cv2
        except ImportError:
            logger.error("[YellowZoneDetector] cv2 未安装")
            return None

        try:
            result = self._detect_raw(frame, cv2)
            if result is None:
                self._lost_frames_count += 1
            else:
                self._lost_frames_count = 0
            return result
        except Exception as exc:
            logger.debug(f"[YellowZoneDetector] 检测异常: {exc}")
            self._lost_frames_count += 1
            return None

    # ─── 内部检测管线 ────────────────────────────────────────────

    def _detect_raw(self, frame: bytes, cv2) -> Optional[ZoneDetection]:
        # ── 1. 解帧 ──
        frame_np = np.frombuffer(frame, dtype=np.uint8).reshape(
            (self._frame_height, self._frame_width, 3)
        )

        # ── ROI：跳过顶部，只处理含地面的下部 ──
        roi_y  = int(self._frame_height * self._roi_top_ratio)
        roi_np = frame_np[roi_y:, :]

        # ── 2. BGR→HSV，阈值分割纯黄色 ──
        hsv  = cv2.cvtColor(roi_np, cv2.COLOR_BGR2HSV)
        low  = np.array([self._h_low,  self._s_low,  self._v_low],  dtype=np.uint8)
        high = np.array([self._h_high, self._s_high, self._v_high], dtype=np.uint8)
        mask = cv2.inRange(hsv, low, high)
        # ── 3. 形态学闭+开运算 ──
        k = self._morph_kernel_size
        kernel = cv2.getStructuringElement(cv2.MORPH_RECT, (k, k))
        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, kernel)
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN,  kernel)

        # ── 4. 找外轮廓 ──
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        # ── 5. 候选筛选 ──
        candidates = []
        for cnt in contours:
            result = self._evaluate_contour(cnt, hsv, cv2)
            if result is not None:
                candidates.append(result)

        if not candidates:
            return None

        # ── 6. 取 quality 最高候选（面积作为 tie-break） ──
        candidates.sort(key=lambda z: (z.quality, z.area), reverse=True)
        best = candidates[0]

        # ── 7. 将 ROI 内坐标还原为全图坐标 ──
        best.polygon[:, 1] += roi_y
        bx, by, bw, bh      = best.bbox
        best.bbox            = (bx, by + roi_y, bw, bh)
        cx, cy               = best.center
        best.center          = (cx, cy + roi_y)

        return best

    def _evaluate_contour(self, cnt, hsv, cv2) -> Optional[ZoneDetection]:
        """对单个轮廓进行评估，返回 ZoneDetection 或 None。"""
        area = cv2.contourArea(cnt)

        # ── 基础面积过滤 ──
        if area < self._min_area_px:
            return None
        if area > self._frame_area * self._max_area_ratio:
            return None

        # ── minAreaRect ──
        rect = cv2.minAreaRect(cnt)
        (cx, cy), (rw, rh), angle = rect

        if rw == 0 or rh == 0:
            return None

        long_side  = max(rw, rh)
        short_side = min(rw, rh)
        aspect     = long_side / short_side

        # ── 长宽比过滤 ──
        if aspect < self._min_aspect or aspect > self._max_aspect:
            return None

        # ── 饱满度过滤（轮廓面积 / 最小外接矩形面积） ──
        rect_area = rw * rh
        solidity  = area / rect_area if rect_area > 0 else 0.0
        if solidity < self._min_solidity:
            return None

        # ── 四边形多边形 ──
        box_pts = cv2.boxPoints(rect)
        box_pts = np.int32(box_pts)  # shape (4, 2)

        # ── 轴对齐外接矩形 ──
        bx, by, bw, bh = cv2.boundingRect(cnt)

        # ── 黑边验证 ──
        border_ok, border_score = self._verify_black_border(box_pts, hsv, cv2)
        # if not border_ok:
        #     return None

        # ── 中心汉字检测 ──
        has_text, text_score = self._verify_center_black_text(box_pts, hsv, cv2)

        #得分限制
        MIN_BORDER_SCORE = 0.20
        MIN_TEXT_SOORE = 0.30
        if border_ok and not has_center_text:
            return None

        # ── quality 计算 ──
        area_score  = self._score_area(area)
        solid_score = min(1.0, (solidity - self._min_solidity) / (1.0 - self._min_solidity))
        quality = (
            self._w_area   * area_score
            + self._w_solid  * solid_score
            + self._w_border * border_score
        )
        # 检测到中心汉字：叠加奖励分，使带字候选天然优先（质量分可超过 1.0）
        if has_text:
            quality += self._center_text_bonus * min(1.0, text_score)

        return ZoneDetection(
            polygon           = box_pts,
            bbox              = (bx, by, bw, bh),
            center            = (int(cx), int(cy)),
            area              = float(area),
            angle             = float(angle),
            quality           = float(quality),
            border_ok         = border_ok,
            has_center_text   = has_text,
            area_score        = float(area_score),
            solid_score       = float(solid_score),
            border_score      = float(border_score),
            center_text_score = float(text_score),
        )

    def _score_area(self, area: float) -> float:
        """面积评分：在合理范围内给 1.0，太小或太大打折。"""
        min_ok = self._frame_area * 0.01   # 占画面 1%
        max_ok = self._frame_area * 0.35   # 占画面 35%
        if min_ok <= area <= max_ok:
            return 1.0
        elif area < min_ok:
            return area / min_ok
        else:
            over = (area - max_ok) / (self._frame_area * self._max_area_ratio - max_ok + 1)
            return max(0.0, 1.0 - over)

    def _verify_black_border(
        self,
        box_pts: np.ndarray,
        hsv:     np.ndarray,
        cv2,
    ) -> Tuple[bool, float]:
        """
        在四边形外扩 border_expand_px 像素的环形区域内采样。
        若 V 通道均值 < border_v_threshold，认为有黑边，得分 1.0。
        """
        try:
            h, w = hsv.shape[:2]

            inner_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(inner_mask, [box_pts], 255)

            exp_px = max(1, self._border_expand_px)
            dil_kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (exp_px * 2 + 1, exp_px * 2 + 1)
            )
            outer_mask = cv2.dilate(inner_mask, dil_kernel)
            ring_mask  = cv2.subtract(outer_mask, inner_mask)

            v_channel   = hsv[:, :, 2]
            ring_pixels = v_channel[ring_mask > 0]

            if ring_pixels.size == 0:
                return False, 0.5

            # 用低百分位数而非均值：只要环内有少数黑色橡胶像素即可通过。
            # 均值会被大量地毯像素拉高，导致有黑边的真实垫子也被误杀。
            # 10th percentile = 环内最暗的 10% 像素的上限值，对距离远近更鲁棒。
            p10 = float(np.percentile(ring_pixels, 10))

            if p10 < self._border_v_threshold:
                return True, 1.0
            else:
                score = max(0.0, 1.0 - (p10 - self._border_v_threshold) / (255 - self._border_v_threshold + 1))
                return False, float(score)

        except Exception as exc:
            logger.debug(f"[YellowZoneDetector] 黑边验证异常: {exc}")
            return False, 0.5

    def _verify_center_black_text(
        self,
        box_pts: np.ndarray,
        hsv:     np.ndarray,
        cv2,
    ) -> Tuple[bool, float]:
        """
        在四边形内部中心区域检测黑色汉字像素。

        策略：
          1. 以四边形的中心点为基准，取中心 crop_ratio 比例的缩放矩形区域作为掩码；
          2. 统计该区域内 V 通道 < black_v_threshold 的像素比例；
          3. 比例超过 min_ratio 即认为存在黑色文字，返回 (True, 密度分)。

        Returns:
            (has_text, density_score)
            - has_text: 是否检测到黑色汉字
            - density_score: 暗像素密度 0.0-1.0，供调试观察
        """
        try:
            h, w = hsv.shape[:2]

            # ── 计算四边形中心点 ──
            cx = float(box_pts[:, 0].mean())
            cy = float(box_pts[:, 1].mean())

            # ── 以中心点为基准，将四边形顶点向中心缩放 crop_ratio ──
            ratio = self._center_crop_ratio
            center_pts = np.array(
                [
                    [cx + (pt[0] - cx) * ratio, cy + (pt[1] - cy) * ratio]
                    for pt in box_pts
                ],
                dtype=np.float32,
            )
            center_pts_int = np.int32(center_pts)

            # ── 绘制缩小四边形掩码 ──
            center_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(center_mask, [center_pts_int], 255)

            # ── 统计中心区内的暗像素 ──
            v_channel     = hsv[:, :, 2]
            center_pixels = v_channel[center_mask > 0]

            if center_pixels.size == 0:
                return False, 0.0

            dark_count  = int(np.sum(center_pixels < self._center_black_v_threshold))
            dark_ratio  = dark_count / center_pixels.size
            density_score = min(1.0, dark_ratio / max(self._center_black_min_ratio, 1e-6))

            has_text = dark_ratio >= self._center_black_min_ratio

            if has_text:
                logger.debug(
                    f"[YellowZoneDetector] 中心汉字检测通过: "
                    f"暗像素比={dark_ratio:.3f} (阈值={self._center_black_min_ratio})"
                )

            return has_text, float(density_score)

        except Exception as exc:
            logger.debug(f"[YellowZoneDetector] 中心汉字检测异常: {exc}")
            return False, 0.0
