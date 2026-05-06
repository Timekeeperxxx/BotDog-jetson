from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..config import settings
from ..logging_config import get_logger
from ..services_logs import write_log
from .schemas import AuthUser

auth_logger = get_logger("鉴权")

ROLE_LEVELS = {
    "viewer": 1,
    "operator": 2,
    "admin": 3,
}





def create_access_token(user: AuthUser) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "user_id": user.id,
        "sub": user.username,
        "role": user.role,
        "token_version": user.token_version,
        "exp": int((now + timedelta(minutes=settings.JWT_EXPIRE_MINUTES)).timestamp()),
    }
    header = {"alg": "HS256", "typ": "JWT"}
    return _encode_jwt(header, payload, settings.JWT_SECRET)


def decode_access_token(token: str) -> dict[str, Any]:
    payload = _decode_jwt(token, settings.JWT_SECRET)
    exp = int(payload.get("exp", 0))
    if exp <= int(datetime.now(timezone.utc).timestamp()):
        raise ValueError("token 已过期")
    username = str(payload.get("sub") or "").strip()
    role = str(payload.get("role") or "").strip()
    if not username or role not in ROLE_LEVELS:
        raise ValueError("token 载荷无效")
    return payload


def role_satisfies(role: str, required_role: str) -> bool:
    return ROLE_LEVELS.get(role, 0) >= ROLE_LEVELS.get(required_role, 999)


async def safe_write_audit_log(
    session: Any,
    *,
    level: str,
    module: str,
    message: str,
    task_id: int | None = None,
) -> None:
    if session is None:
        return
    try:
        await write_log(
            session,
            level=level,
            module=module,
            message=message,
            task_id=task_id,
        )
    except Exception as exc:  # noqa: BLE001
        auth_logger.warning("写入审计日志失败：{}", exc)


def _encode_jwt(header: dict[str, Any], payload: dict[str, Any], secret: str) -> str:
    header_segment = _b64url_encode(json.dumps(header, separators=(",", ":")).encode("utf-8"))
    payload_segment = _b64url_encode(json.dumps(payload, separators=(",", ":")).encode("utf-8"))
    signing_input = f"{header_segment}.{payload_segment}"
    signature = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    signature_segment = _b64url_encode(signature)
    return f"{signing_input}.{signature_segment}"


def _decode_jwt(token: str, secret: str) -> dict[str, Any]:
    try:
        header_segment, payload_segment, signature_segment = token.split(".")
    except ValueError as exc:
        raise ValueError("token 格式无效") from exc

    signing_input = f"{header_segment}.{payload_segment}"
    expected_signature = hmac.new(secret.encode("utf-8"), signing_input.encode("utf-8"), hashlib.sha256).digest()
    if not hmac.compare_digest(_b64url_encode(expected_signature), signature_segment):
        raise ValueError("token 签名无效")

    try:
        payload_raw = _b64url_decode(payload_segment)
        return json.loads(payload_raw.decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        raise ValueError("token 载荷解析失败") from exc


def _b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("ascii").rstrip("=")


def _b64url_decode(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)
