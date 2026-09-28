"""告警时间以 UTC 保存；帧时间由后端单调时钟映射，非摄像头曝光时间。"""
import time
from datetime import datetime, timezone


UNTIMED_EVENT_CODES = {"NAV_PATH_BLOCKED", "NAV_BLOCK_CLEARED"}

def observation_timing(observed: float | None, *, duration: float = 0.0,
                       threshold: float = 0.0, source: str = 'backend_frame_received') -> dict:
    if observed is None:
        return {'source': 'event_start_unavailable'}
    offset = time.time() - time.monotonic()
    start = observed - duration
    def iso(value):
        return datetime.fromtimestamp(value + offset, timezone.utc).isoformat(timespec='milliseconds').replace('+00:00', 'Z')
    return {'source': source, 'event_started_at': iso(start),
            'eligible_at': iso(start + threshold), 'duration_seconds': duration}


def log_alert_timing(evidence_id, event_code, message, timing, stage):
    if event_code in UNTIMED_EVENT_CODES:
        return
    import json
    from .logging_config import logger
    logger.bind(domain='告警日志', alert_log=True).info('{}', json.dumps({
        'stage': stage, 'evidence_id': evidence_id, 'event_code': event_code,
        'message': message, 'display_status': 'received' if timing.get('displayed_at') else 'awaiting_visible_page_receipt',
        **timing,
    }, ensure_ascii=False))
