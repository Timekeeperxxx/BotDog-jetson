"""Bounded save telemetry reader; progress never determines saved=True."""
import json
from math import isfinite
from pathlib import Path
import re
import time

PROGRESS_FILE = '.mapping_save_progress.json'


def _json(path, limit=16384):
    try:
        with Path(path).open(encoding='utf-8') as stream:
            result = json.loads(stream.read(limit))
        return result if isinstance(result, dict) else {}
    except (OSError, ValueError, UnicodeError):
        return {}


def _number(value):
    try:
        if isinstance(value, (int, float)) and not isinstance(value, bool) and isfinite(value):
            return float(value)
    except (OverflowError, ValueError):
        pass
    return None


def save_fields(session):
    now = time.time()
    started = session.stop_requested_at
    elapsed = max(0, now-started) if started is not None else 0
    progress = {
        'stage': 'stopping', 'label': '等待保存开始',
        'detail': '已请求结束建图，等待脚本开始保存',
        'stage_started_at': started, 'stage_elapsed_seconds': elapsed,
        'updated_at': None, 'update_age_seconds': None,
        'completed': None, 'total': None, 'unit': None, 'baseline_saved': False,
    }
    raw = _json(session.map_dir/PROGRESS_FILE)
    updated = _number(raw.get('updated_at'))
    phase_started = _number(raw.get('stage_started_at'))
    stage = raw.get('stage')
    if (updated is not None and updated >= (started or session.started_at)-2
            and updated <= now+5 and phase_started is not None
            and 0 < phase_started <= updated
            and isinstance(stage, str) and re.fullmatch(r'[a-z_]{1,48}', stage)):
        progress.update(
            stage=stage, label=str(raw.get('label') or '保存地图')[:100],
            detail=str(raw.get('detail') or '')[:500], stage_started_at=phase_started,
            stage_elapsed_seconds=max(0, now-phase_started), updated_at=updated,
            update_age_seconds=max(0, now-updated),
            baseline_saved=raw.get('baseline_saved') is True,
        )
        completed, total = raw.get('completed'), raw.get('total')
        if (type(completed) is int and type(total) is int
                and 0 <= completed <= total and 0 < total <= 10**9):
            progress.update(completed=completed, total=total,
                            unit=str(raw.get('unit') or '项')[:24])
    return {
        'save_started_at': started, 'save_elapsed_seconds': elapsed,
        # A live process is a heartbeat, not evidence of numerical progress.
        'save_worker_alive': session.is_running(), 'save_progress': progress,
    }


def refinement_fields(map_dir, saved):
    if not saved:
        return {'height_refinement_state': 'failed', 'height_refinement_reason': None}
    raw = _json(Path(map_dir)/'.height_refinement/result.json', 65536)
    state = raw.get('state')
    if state not in ('height_refined', 'baseline_saved'):
        state = 'unknown'
    reason = str(raw.get('reason') or '')[:1000] or None
    return {'height_refinement_state': state, 'height_refinement_reason': reason}
