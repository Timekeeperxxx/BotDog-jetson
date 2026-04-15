"""
独立黄色+黑边区域检测模块（阶段 1）。

与 GuardMissionService 完全解耦，只负责：
  1. HSV 分割纯黄色区域（H:20-35，聚焦纯黄，比原来的 10-40 更窄）
  2. 形态学闭+开运算
  3. 轮廓筛选（面积 / 位置 / 长宽比 / 饱满度）
  4. minAreaRect 拟合四边形
  5. 黑边验证（四边形外扩采样，V 通道均值要低）
  6. 输出 ZoneDetection 数据类，含 polygon / bbox / center / area / angle / quality

不让狗动，只负责输出检测结果供上层消费。
"""

from __future__ import annotations

import numpy as np
from dataclasses import dataclass, field
from typing import Optional, Tuple

from .logging_config import logger

# ─── 可调 HSV 参数（初始值） ──────────────────────────────────────────
# 纯黄色（排除橙色和米黄，聚焦标准黄色纸板/地垫）
YELLOW_H_LOW  = 15
YELLOW_H_HIGH = 40
YELLOW_S_LOW  = 80
YELLOW_S_HIGH = 255
YELLOW_V_LOW  = 120
YELLOW_V_HIGH = 255

# 黑边验证：外扩区域的 V 通道平均值阈值（低于此值 = 有黑边）
BORDER_V_THRESHOLD = 80
# 外扩像素数
BORDER_EXPAND_PX = 12

# 面积约束
ZONE_MIN_AREA_PX = 800
ZONE_MAX_AREA_RATIO = 0.50   # 不能占画面超过 50%

# 形状约束
ZONE_MIN_ASPECT   = 1.5
ZONE_MAX_ASPECT   = 15.0
ZONE_MIN_SOLIDITY = 0.60
ZONE_MIN_Y_RATIO  = 0.30    # 中心点必须在画面中下部（地面约束）

# 形态学核大小
MORPH_KERNEL_SIZE = 7

# quality 权重
W_AREA    = 0.30
W_SOLID   = 0.30
W_BORDER  = 0.40


@dataclass
class ZoneDetection:
    """单帧区域检测结果。"""
    polygon: np.ndarray            # shape (4, 2)，顺时针四边形顶点
    bbox: Tuple[int, int, int, int]  # (x, y, w, h)  轴对齐外接矩形
    center: Tuple[int, int]        # (cx, cy)  区域中心
    area: float                    # 像素面积（轮廓面积）
    angle: float                   # minAreaRect 旋转角度（度）
    quality: float                 # 0.0 – 1.0 综合质量分
    border_ok: bool                # 黑边验证是否通过
    # 供调试的原始分量
    area_score: float = field(default=0.0, repr=False)
    solid_score: float = field(default=0.0, repr=False)
    border_score: float = field(default=0.0, repr=False)


class YellowZoneDetector:
    """
    独立的黄色防区检测器。

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

        # ── 2. BGR→HSV，阈值分割纯黄色 ──
        hsv  = cv2.cvtColor(frame_np, cv2.COLOR_BGR2HSV)
        low  = np.array([YELLOW_H_LOW,  YELLOW_S_LOW,  YELLOW_V_LOW],  dtype=np.uint8)
        high = np.array([YELLOW_H_HIGH, YELLOW_S_HIGH, YELLOW_V_HIGH], dtype=np.uint8)
        mask = cv2.inRange(hsv, low, high)

        # ── 3. 形态学闭+开运算 ──
        kernel = cv2.getStructuringElement(
            cv2.MORPH_RECT, (MORPH_KERNEL_SIZE, MORPH_KERNEL_SIZE)
        )
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
        return candidates[0]

    def _evaluate_contour(self, cnt, hsv, cv2) -> Optional[ZoneDetection]:
        """对单个轮廓进行评估，返回 ZoneDetection 或 None。"""
        area = cv2.contourArea(cnt)

        # ── 基础面积过滤 ──
        if area < ZONE_MIN_AREA_PX:
            return None
        if area > self._frame_area * ZONE_MAX_AREA_RATIO:
            return None

        # ── minAreaRect ──
        rect = cv2.minAreaRect(cnt)
        (cx, cy), (rw, rh), angle = rect

        if rw == 0 or rh == 0:
            return None

        # ── 位置过滤（地面约束） ──
        if cy < self._frame_height * ZONE_MIN_Y_RATIO:
            return None

        long_side  = max(rw, rh)
        short_side = min(rw, rh)
        aspect     = long_side / short_side

        # ── 长宽比过滤 ──
        if aspect < ZONE_MIN_ASPECT or aspect > ZONE_MAX_ASPECT:
            return None

        # ── 饱满度过滤（轮廓面积 / 最小外接矩形面积） ──
        rect_area = rw * rh
        solidity  = area / rect_area if rect_area > 0 else 0.0
        if solidity < ZONE_MIN_SOLIDITY:
            return None

        # ── 四边形多边形 ──
        box_pts = cv2.boxPoints(rect)
        box_pts = np.int32(box_pts)  # shape (4, 2)

        # ── 轴对齐外接矩形 ──
        bx, by, bw, bh = cv2.boundingRect(cnt)

        # ── 黑边验证 ──
        border_ok, border_score = self._verify_black_border(box_pts, hsv, cv2)

        # ── quality 计算 ──
        area_score  = self._score_area(area)
        solid_score = min(1.0, (solidity - ZONE_MIN_SOLIDITY) / (1.0 - ZONE_MIN_SOLIDITY))
        quality = (
            W_AREA   * area_score
            + W_SOLID  * solid_score
            + W_BORDER * border_score
        )

        return ZoneDetection(
            polygon     = box_pts,
            bbox        = (bx, by, bw, bh),
            center      = (int(cx), int(cy)),
            area        = float(area),
            angle       = float(angle),
            quality     = float(quality),
            border_ok   = border_ok,
            area_score  = float(area_score),
            solid_score = float(solid_score),
            border_score= float(border_score),
        )

    def _score_area(self, area: float) -> float:
        """面积评分：在合理范围内给 1.0，太小或太大打折。"""
        min_ok  = self._frame_area * 0.01   # 占画面 1%
        max_ok  = self._frame_area * 0.35   # 占画面 35%
        if min_ok <= area <= max_ok:
            return 1.0
        elif area < min_ok:
            return area / min_ok
        else:
            # 超过 35%，线性衰减至 ZONE_MAX_AREA_RATIO
            over = (area - max_ok) / (self._frame_area * ZONE_MAX_AREA_RATIO - max_ok + 1)
            return max(0.0, 1.0 - over)

    def _verify_black_border(
        self,
        box_pts:  np.ndarray,
        hsv:      np.ndarray,
        cv2,
    ) -> Tuple[bool, float]:
        """
        在四边形外扩 BORDER_EXPAND_PX 像素的环形区域内采样。
        若该环形区域的 V 通道均值 < BORDER_V_THRESHOLD，认为有黑边，得分 1.0。
        否则得分 = 1 - (mean_v - BORDER_V_THRESHOLD) / (255 - BORDER_V_THRESHOLD)。
        """
        try:
            h, w = hsv.shape[:2]

            # 外扩轮廓 mask
            inner_mask = np.zeros((h, w), dtype=np.uint8)
            cv2.fillPoly(inner_mask, [box_pts], 255)

            # 膨胀核
            exp_px = max(3, BORDER_EXPAND_PX)
            dil_kernel = cv2.getStructuringElement(
                cv2.MORPH_RECT, (exp_px * 2 + 1, exp_px * 2 + 1)
            )
            outer_mask = cv2.dilate(inner_mask, dil_kernel)

            # 环形区域 = 外扩 - 内部
            ring_mask  = cv2.subtract(outer_mask, inner_mask)

            # 采样 V 通道
            v_channel  = hsv[:, :, 2]
            ring_pixels = v_channel[ring_mask > 0]

            if ring_pixels.size == 0:
                return False, 0.5   # 无法验证，中性分

            mean_v = float(ring_pixels.mean())

            if mean_v < BORDER_V_THRESHOLD:
                return True, 1.0
            else:
                score = max(0.0, 1.0 - (mean_v - BORDER_V_THRESHOLD) / (255 - BORDER_V_THRESHOLD + 1))
                return False, float(score)

        except Exception as exc:
            logger.debug(f"[YellowZoneDetector] 黑边验证异常: {exc}")
            return False, 0.5
