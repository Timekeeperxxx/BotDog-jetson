"""
陌生人判定策略模块。

职责边界：
- 规则引擎判断检测到的目标是否为"陌生人"
- 人脸库识别成功的人员直接视为已知人员
- 保留会话级 known_targets 人工白名单作为兜底

注意：人脸库是跨任务身份白名单；session_known_targets 仍只在当前会话有效。
"""

from __future__ import annotations

from typing import Optional

from .logging_config import logger


class StrangerPolicy:
    """
    陌生人判定策略（默认拒绝）。

    当前策略：
    - face_status=recognized 且存在 identity_id：人员库授权人员，不跟踪
    - track_id 在会话级 known_targets 中：人工确认的已知人员，不跟踪
    - pending/unknown/unavailable/无脸结果：未完成授权确认，仍视为陌生人
    """

    def __init__(self) -> None:
        # 会话级已知人员 track_id 集合（人工标记后加入）
        self._known_track_ids: set[int] = set()

    def is_stranger(
        self,
        track_id: int,
        *,
        face_status: str | None = None,
        identity_id: int | None = None,
    ) -> bool:
        """
        判断指定 track_id 是否为陌生人。

        Args:
            track_id: 目标跟踪 ID

        人脸识别采用默认拒绝：只有明确匹配到人员库身份才算授权。检测中、
        无法识别或匹配失败均不能自动放行。

        Returns:
            True 若为未授权/陌生人（可进入现有跟踪流程）
        """
        if track_id in self._known_track_ids:
            return False
        if face_status == "recognized" and identity_id is not None:
            return False
        return True

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
