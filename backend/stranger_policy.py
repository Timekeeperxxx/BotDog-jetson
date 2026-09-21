"""
陌生人判定策略模块。

职责边界：
- 规则引擎判断检测到的目标是否为"陌生人"
- 阶段 2：基于会话级 known_targets 列表判断（session-scoped 白名单）
- 未来可扩展为策略链，接入人脸识别等外部服务

注意：
- 此处的"已知人员"仅为会话级人工标记，不构成稳定身份白名单
- 跨任务、跨重启不复用，见 session_known_targets 表语义
"""

from __future__ import annotations

from typing import Any, Optional

from .logging_config import logger


class StrangerPolicy:
    """
    陌生人判定策略（阶段 2：规则引擎版）。

    当前策略：
    - 所有检测到的 person 默认视为陌生人
    - 若 track_id 在会话级 known_targets 中，则排除
    - 未来：可插入人脸识别、人员库比对等策略链
    """

    def __init__(self) -> None:
        # 会话级已知人员 track_id 集合（人工标记后加入）
        self._known_track_ids: set[int] = set()

    def is_stranger(self, track_id: int) -> bool:
        """
        判断指定 track_id 是否为陌生人。

        Args:
            track_id: 目标跟踪 ID

        Returns:
            True 若为陌生人（需要跟踪的目标）
        """
        return track_id not in self._known_track_ids

    def mark_known(self, track_id: int, reason: str = "operator") -> None:
        """
        将 track_id 标记为已知人员。

        - 会话级有效，下次任务重启后失效
        - 不构成跨任务身份白名单
        """
        self._known_track_ids.add(track_id)
        logger.info(
            f"[StrangerPolicy] track_id={track_id} 标记为已知人员，原因: {reason}"
        )

    def unmark_known(self, track_id: int) -> None:
        """取消已知标记（误操作恢复）。"""
        self._known_track_ids.discard(track_id)

    def reset_session(self) -> None:
        """
        重置会话级已知人员列表（任务停止时调用）。

        调用后所有人员重新视为陌生人。
        """
        count = len(self._known_track_ids)
        self._known_track_ids.clear()
        if count:
            logger.info(f"[StrangerPolicy] 会话级已知列表已重置（清除 {count} 条）")

    @property
    def known_count(self) -> int:
        return len(self._known_track_ids)

    def get_known_ids(self) -> list[int]:
        return list(self._known_track_ids)


# ─── 全局单例 ────────────────────────────────────────────────────────────────

_stranger_policy: Optional[StrangerPolicy] = None


def get_stranger_policy() -> Optional[StrangerPolicy]:
    return _stranger_policy


def set_stranger_policy(policy: StrangerPolicy) -> None:
    global _stranger_policy
    _stranger_policy = policy


def is_authorized_person(detection: Any) -> bool:
    """仅已确认匹配到启用身份库的人员免于未授权告警。"""
    return (
        getattr(detection, "face_status", None) == "recognized"
        and getattr(detection, "identity_id", None) is not None
    )
