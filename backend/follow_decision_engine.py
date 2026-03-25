"""
跟踪决策引擎。

职责边界：
- 根据当前目标位置和画面关系生成离散控制命令
- 实现命令节流与防抖，避免控制频繁抖动
- 结合纵向位置防止近距离前冲

输出命令集：
  "left" / "right" / "forward" / "stop"

注意：本模块不直接调用 ControlService，仅生成决策。
调用方负责将决策提交给 ControlService。
"""

from __future__ import annotations

import time
from typing import Optional

from .tracking_types import TrackDecision


class FollowDecisionEngine:
    """
    跟踪决策引擎。

    结合水平偏差、纵向位置（锚点 y 值）、目标面积生成跟踪命令。
    内置命令节流（`command_interval_ms`）和方向切换防抖（`direction_debounce_frames`）。
    """

    def __init__(
        self,
        yaw_deadband_px: int = 80,
        forward_area_ratio: float = 0.15,
        anchor_y_stop_ratio: float = 0.80,
        command_interval_ms: float = 200.0,
        direction_debounce_frames: int = 1,  #左右防抖所需帧数
    ) -> None:
        """
        初始化决策引擎。

        Args:
            yaw_deadband_px: 水平偏航死区（像素），小于此值视为居中
            forward_area_ratio: 目标框面积占画面比例低于此值时考虑前进
            anchor_y_stop_ratio: 锚点纵向位置超过画面高度的此比例时禁止前进
            command_interval_ms: 命令最小发送间隔（毫秒）节流
            direction_debounce_frames: 方向命令连续 N 帧后才真正下发（防抖）
        """
        self._yaw_deadband_px = yaw_deadband_px
        self._forward_area_ratio = forward_area_ratio
        self._anchor_y_stop_ratio = anchor_y_stop_ratio
        self._command_interval_s = command_interval_ms / 1000.0
        self._direction_debounce_frames = direction_debounce_frames

        # 内部状态
        self._last_sent_time: float = 0.0
        self._last_sent_command: Optional[str] = None
        self._pending_command: Optional[str] = None
        self._pending_count: int = 0

    def decide(
        self,
        bbox: tuple[int, int, int, int],
        image_width: int,
        image_height: int,
    ) -> TrackDecision:
        """
        根据目标 bbox 生成控制决策。

        Args:
            bbox: (x1, y1, x2, y2) 目标检测框，图像像素坐标
            image_width: 画面宽度（像素）
            image_height: 画面高度（像素）

        Returns:
            TrackDecision（command + should_send + reason）
        """
        x1, y1, x2, y2 = bbox
        target_cx = (x1 + x2) // 2
        target_cy = (y1 + y2) // 2  # noqa: F841（暂未使用）
        image_cx = image_width // 2

        anchor_y = y2  # 底部中心纵向坐标

        # ── 计算水平偏差 ──────────────────────────────────────────────────
        err_x = target_cx - image_cx
        bbox_area = (x2 - x1) * (y2 - y1)
        frame_area = image_width * image_height
        area_ratio = bbox_area / frame_area if frame_area > 0 else 0.0

        # ── 生成候选命令 ──────────────────────────────────────────────────
        if abs(err_x) > self._yaw_deadband_px:
            # 目标偏左/右，转向
            raw_cmd = "left" if err_x < 0 else "right"
            reason = f"水平偏差 err_x={err_x}px（死区={self._yaw_deadband_px}px）"
        elif area_ratio < self._forward_area_ratio:
            # 目标居中但较远，判断是否允许前进
            if anchor_y > image_height * self._anchor_y_stop_ratio:
                # 锚点已靠近画面下缘，禁止前进（避免近距离前冲）
                raw_cmd = "stop"
                reason = (
                    f"锚点已靠近底部（anchor_y={anchor_y}, "
                    f"阈值={int(image_height * self._anchor_y_stop_ratio)}），禁止前进"
                )
            else:
                raw_cmd = "forward"
                reason = f"目标居中且较远（area_ratio={area_ratio:.3f}）"
        else:
            # 目标居中且距离合适，保持
            raw_cmd = "stop"
            reason = f"目标居中且距离合适（area_ratio={area_ratio:.3f}）"

        # ── 方向防抖 ──────────────────────────────────────────────────────
        # 对于 left/right 切换，连续相同命令才真正下发
        if raw_cmd in ("left", "right"):
            if raw_cmd == self._pending_command:
                self._pending_count += 1
            else:
                self._pending_command = raw_cmd
                self._pending_count = 1

            if self._pending_count < self._direction_debounce_frames:
                # 还未稳定，不下发
                return TrackDecision(
                    command=raw_cmd,
                    should_send=False,
                    reason=f"防抖等待 {self._pending_count}/{self._direction_debounce_frames} 帧",
                )
        else:
            # forward/stop 不需要防抖，直接处理
            self._pending_command = raw_cmd
            self._pending_count = 0

        # ── 命令节流 ──────────────────────────────────────────────────────
        # stop 命令不受节流限制，确保能立即响应
        now = time.monotonic()
        if raw_cmd != "stop" and raw_cmd == self._last_sent_command:
            if (now - self._last_sent_time) < self._command_interval_s:
                return TrackDecision(
                    command=raw_cmd,
                    should_send=False,
                    reason=f"节流等待（间隔={self._command_interval_s * 1000:.0f}ms）",
                )

        # ── 允许下发 ──────────────────────────────────────────────────────
        self._last_sent_time = now
        self._last_sent_command = raw_cmd
        return TrackDecision(command=raw_cmd, should_send=True, reason=reason)

    def reset(self) -> None:
        """重置内部状态（目标切换或跟踪停止时调用）。"""
        self._last_sent_time = 0.0
        self._last_sent_command = None
        self._pending_command = None
        self._pending_count = 0
