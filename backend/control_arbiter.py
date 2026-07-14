"""
控制权仲裁器。

职责边界：
- 维护当前控制权拥有者 control_owner
- 根据优先级规则决定自动跟踪命令是否可以下发
- 提供控制权变更通知接口

优先级（高→低）：
  E_STOP > REMOTE_CONTROLLER > WEB_MANUAL > AUTO_TRACK > GUARD_MISSION > NAVIGATION

注意：
- ControlArbiter 负责判断"谁应该控制"
- ControlService 负责"执行命令 + 限流 + Watchdog"，不承担控制权判定
- 人工控制释放后不自动恢复 AUTO_TRACK，须显式调用 release_manual_override()
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Optional

from .tracking_types import ControlOwner
from .logging_config import logger


class ControlArbiter:
    """
    控制权仲裁器。

    使用优先级队列式逻辑：高优先级控制方优先，低优先级命令被丢弃。
    """

    # 优先级映射（数字越大优先级越高）
    _PRIORITY: dict[ControlOwner, int] = {
        ControlOwner.NONE: 0,
        ControlOwner.NAVIGATION: 1,
        ControlOwner.GUARD_MISSION: 2,
        ControlOwner.AUTO_TRACK: 3,
        ControlOwner.WEB_MANUAL: 4,
        ControlOwner.REMOTE_CONTROLLER: 5,
        ControlOwner.E_STOP: 6,
    }

    def __init__(self) -> None:
        self._owner: ControlOwner = ControlOwner.NONE
        # 当前激活的请求者集合（用于多方共存场景）
        self._active_requesters: set[ControlOwner] = set()
        self._on_owner_change_callback = None
        self._owner_change_listeners: list[
            Callable[[ControlOwner, ControlOwner], None]
        ] = []

    # ─── 控制权申请 ──────────────────────────────────────────────────────────

    def request_control(self, requester: ControlOwner) -> bool:
        """
        申请控制权。

        Args:
            requester: 申请控制权的一方

        Returns:
            True 若申请成功（成为当前 owner 或优先级更高）
        """
        self._active_requesters.add(requester)
        prev_owner = self._owner
        self._recalculate_owner()
        if self._owner != prev_owner:
            logger.info(
                f"[ControlArbiter] 控制权变更: {prev_owner.value} → {self._owner.value}"
                f"（申请方: {requester.value}）"
            )
            self._notify_owner_change_listeners(prev_owner, self._owner)
            if self._on_owner_change_callback:
                asyncio.create_task(self._on_owner_change_callback(prev_owner, self._owner))
        return self._owner == requester

    def release_control(self, requester: ControlOwner) -> None:
        """
        释放控制权。

        人工控制释放后，AUTO_TRACK 不会自动恢复，须显式重新申请。
        """
        self._active_requesters.discard(requester)
        prev_owner = self._owner
        self._recalculate_owner()
        if self._owner != prev_owner:
            logger.info(
                f"[ControlArbiter] 控制权变更: {prev_owner.value} → {self._owner.value}"
                f"（{requester.value} 已释放）"
            )
            self._notify_owner_change_listeners(prev_owner, self._owner)
            if self._on_owner_change_callback:
                asyncio.create_task(self._on_owner_change_callback(prev_owner, self._owner))

    def activate_e_stop(self) -> None:
        """Make E-stop the sole requester so reset cannot revive stale owners."""
        prev_owner = self._owner
        self._active_requesters.clear()
        self._active_requesters.add(ControlOwner.E_STOP)
        self._recalculate_owner()
        if self._owner != prev_owner:
            logger.warning(
                f"[ControlArbiter] E_STOP acquired control: "
                f"{prev_owner.value} -> {self._owner.value}"
            )
            self._notify_owner_change_listeners(prev_owner, self._owner)
            if self._on_owner_change_callback:
                asyncio.create_task(self._on_owner_change_callback(prev_owner, self._owner))

    def release_manual_override(self) -> None:
        """
        显式释放人工覆盖（WEB_MANUAL / REMOTE_CONTROLLER），
        供前端"恢复自动跟踪"按钮使用。
        """
        self._active_requesters.discard(ControlOwner.WEB_MANUAL)
        self._active_requesters.discard(ControlOwner.REMOTE_CONTROLLER)
        prev_owner = self._owner
        self._recalculate_owner()
        if self._owner != prev_owner:
            logger.info(
                f"[ControlArbiter] 人工覆盖已释放: {prev_owner.value} → {self._owner.value}"
            )

    # ─── 权限查询 ────────────────────────────────────────────────────────────

    def can_auto_track_send(self) -> bool:
        """
        自动跟踪是否允许下发控制命令。

        只有当 owner == AUTO_TRACK 时才允许。
        """
        return self._owner == ControlOwner.AUTO_TRACK

    def can_guard_send(self) -> bool:
        """
        自动驱离是否允许下发控制命令。
        """
        return self._owner == ControlOwner.GUARD_MISSION

    def can_navigation_send(self) -> bool:
        """
        导航是否允许下发速度控制命令。
        """
        return self._owner == ControlOwner.NAVIGATION

    def is_e_stop_active(self) -> bool:
        return self._owner == ControlOwner.E_STOP

    def is_manual_override_active(self) -> bool:
        return self._owner in (ControlOwner.WEB_MANUAL, ControlOwner.REMOTE_CONTROLLER)

    @property
    def owner(self) -> ControlOwner:
        return self._owner

    def get_status(self) -> dict:
        return {
            "owner": self._owner.value,
            "active_requesters": [r.value for r in self._active_requesters],
            "can_auto_track": self.can_auto_track_send(),
            "can_navigation": self.can_navigation_send(),
        }

    # ─── 内部逻辑 ────────────────────────────────────────────────────────────

    def _recalculate_owner(self) -> None:
        """根据当前激活的申请方重新计算控制权拥有者。"""
        if not self._active_requesters:
            self._owner = ControlOwner.NONE
            return
        # 选优先级最高的
        self._owner = max(
            self._active_requesters,
            key=lambda r: self._PRIORITY[r],
        )

    def set_on_owner_change(self, callback) -> None:
        """设置控制权变更回调（异步函数）。"""
        self._on_owner_change_callback = callback

    def add_owner_change_listener(
        self,
        listener: Callable[[ControlOwner, ControlOwner], None],
    ) -> None:
        """Register a synchronous observer without replacing the async callback."""
        if listener not in self._owner_change_listeners:
            self._owner_change_listeners.append(listener)

    def remove_owner_change_listener(
        self,
        listener: Callable[[ControlOwner, ControlOwner], None],
    ) -> None:
        """Remove a previously registered synchronous observer."""
        try:
            self._owner_change_listeners.remove(listener)
        except ValueError:
            pass

    def _notify_owner_change_listeners(
        self,
        previous: ControlOwner,
        current: ControlOwner,
    ) -> None:
        for listener in tuple(self._owner_change_listeners):
            try:
                listener(previous, current)
            except Exception as exc:  # noqa: BLE001
                logger.exception("[ControlArbiter] 控制权监听器异常: {}", exc)


# ─── 全局单例 ────────────────────────────────────────────────────────────────

_control_arbiter: Optional[ControlArbiter] = None


def get_control_arbiter() -> Optional[ControlArbiter]:
    return _control_arbiter


def set_control_arbiter(arbiter: ControlArbiter) -> None:
    global _control_arbiter
    _control_arbiter = arbiter
