"""启动摘要的统一数据结构与序列化工具。"""

from __future__ import annotations

import json
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping


@dataclass(frozen=True, slots=True)
class StartupSummaryEntry:
    """单个启动项。"""

    name: str
    status: str
    detail: str


class StartupSummary:
    """启动摘要容器。

    统一管理：
    - 启动项的写入顺序
    - 整体状态聚合
    - 快照序列化
    - 文本日志输出
    """

    def __init__(self, entries: Mapping[str, tuple[str, str]] | None = None) -> None:
        self._entries: OrderedDict[str, StartupSummaryEntry] = OrderedDict()
        if entries:
            for name, (status, detail) in entries.items():
                self.set(name, status, detail)

    def set(self, name: str, status: str, detail: str) -> None:
        self._entries[name] = StartupSummaryEntry(name=name, status=status, detail=detail)

    def items(self) -> list[StartupSummaryEntry]:
        return list(self._entries.values())

    def as_dict(self) -> dict[str, tuple[str, str]]:
        return {entry.name: (entry.status, entry.detail) for entry in self._entries.values()}

    def overall_status(self) -> str:
        statuses = [entry.status for entry in self._entries.values()]
        if "failed" in statuses:
            return "存在模块失败"
        if "degraded" in statuses:
            return "部分模块降级"
        if "waiting" in statuses:
            return "部分模块等待中"
        return "全部模块正常"

    def write_snapshot(self, snapshot_dir: Path) -> tuple[str, str]:
        generated_at = datetime.now(timezone.utc).isoformat()
        snapshot_path = snapshot_dir / "startup_summary.json"
        payload = {
            "generated_at": generated_at,
            "items": [
                {
                    "name": entry.name,
                    "status": entry.status,
                    "detail": entry.detail,
                }
                for entry in self._entries.values()
            ],
        }
        snapshot_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return generated_at, str(snapshot_path)


def coerce_startup_summary(summary: Mapping[str, tuple[str, str]] | StartupSummary | None) -> StartupSummary:
    """把旧的 dict 形式或新的容器统一成 StartupSummary。"""

    if isinstance(summary, StartupSummary):
        return summary
    return StartupSummary(summary or {})
