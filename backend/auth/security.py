"""密码哈希与安全工具。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os

try:  # pragma: no cover - 运行环境可选依赖
    import bcrypt as _bcrypt
except ModuleNotFoundError:  # pragma: no cover - 无 bcrypt 时回退标准库
    _bcrypt = None

_PBKDF2_PREFIX = "pbkdf2_sha256"
_PBKDF2_ITERATIONS = 390000
_PBKDF2_SALT_BYTES = 16


def verify_password(plain_password: str, hashed_password: str) -> bool:
    if hashed_password.startswith(f"{_PBKDF2_PREFIX}$"):
        try:
            _, iterations_raw, salt_b64, hash_b64 = hashed_password.split("$", 3)
            iterations = int(iterations_raw)
            salt = base64.b64decode(salt_b64.encode("ascii"))
            expected = base64.b64decode(hash_b64.encode("ascii"))
        except (ValueError, TypeError, base64.binascii.Error):
            return False

        derived = hashlib.pbkdf2_hmac(
            "sha256",
            plain_password.encode("utf-8"),
            salt,
            iterations,
        )
        return hmac.compare_digest(derived, expected)

    if _bcrypt is None:
        return False

    try:
        return _bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))
    except ValueError:
        return False


def get_password_hash(password: str) -> str:
    if _bcrypt is not None:
        salt = _bcrypt.gensalt()
        return _bcrypt.hashpw(password.encode("utf-8"), salt).decode("utf-8")

    salt = os.urandom(_PBKDF2_SALT_BYTES)
    derived = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        _PBKDF2_ITERATIONS,
    )
    salt_b64 = base64.b64encode(salt).decode("ascii")
    hash_b64 = base64.b64encode(derived).decode("ascii")
    return f"{_PBKDF2_PREFIX}${_PBKDF2_ITERATIONS}${salt_b64}${hash_b64}"

def is_valid_password(password: str, username: str) -> tuple[bool, str]:
    """验证密码规则"""
    if len(password) < 8:
        return False, "密码长度必须至少为 8 位"
    if password == username:
        return False, "密码不能与用户名相同"
    if password.strip() == "":
        return False, "密码不能全为空格"
    if password.lower() in ["admin", "password", "12345678", "please_change_me"]:
        return False, "密码过于简单或包含被禁止的弱口令"
    return True, ""
