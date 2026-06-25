from __future__ import annotations
from app.utils import env_int

import base64
import hashlib
import hmac
import json
import os
import time
from dataclasses import dataclass
from typing import Any

from fastapi import Depends, Header, HTTPException, WebSocket, status
from pydantic import BaseModel


class LoginRequest(BaseModel):
    username: str
    password: str


class AuthTokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    username: str


class CurrentUser(BaseModel):
    username: str


@dataclass(frozen=True)
class LocalAuthSettings:
    username: str
    password_hash: str
    secret: str
    expires_minutes: int


def load_auth_settings() -> LocalAuthSettings:
    username = os.getenv("LOCAL_AUTH_USERNAME", "admin")
    password_hash = os.getenv("LOCAL_AUTH_PASSWORD_HASH", "")
    raw_password = os.getenv("LOCAL_AUTH_PASSWORD", "admin")
    return LocalAuthSettings(
        username=username,
        password_hash=password_hash or hash_password(raw_password),
        secret=os.getenv("JWT_SECRET", "dev-local-jwt-secret-change-me"),
        expires_minutes=env_int("JWT_EXPIRES_MINUTES", 12 * 60),
    )


def hash_password(password: str, salt: str | None = None) -> str:
    salt_bytes = (salt or _b64url(os.urandom(16))).encode("utf-8")
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt_bytes, 120_000)
    return f"pbkdf2_sha256${salt_bytes.decode('utf-8')}${_b64url(digest)}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        algorithm, salt, expected = stored_hash.split("$", 2)
    except ValueError:
        return False
    if algorithm != "pbkdf2_sha256":
        return False
    candidate = hash_password(password, salt).split("$", 2)[2]
    return hmac.compare_digest(candidate, expected)


def authenticate_user(username: str, password: str) -> CurrentUser:
    settings = load_auth_settings()
    if not hmac.compare_digest(username, settings.username):
        raise _unauthorized()
    if not verify_password(password, settings.password_hash):
        raise _unauthorized()
    return CurrentUser(username=settings.username)


def create_access_token(user: CurrentUser) -> str:
    settings = load_auth_settings()
    now = int(time.time())
    payload = {
        "sub": user.username,
        "iat": now,
        "exp": now + settings.expires_minutes * 60,
    }
    return _encode_jwt(payload, settings.secret)


def current_user(authorization: str | None = Header(default=None)) -> CurrentUser:
    return user_from_authorization(authorization)


def user_from_authorization(authorization: str | None) -> CurrentUser:
    if not authorization or not authorization.startswith("Bearer "):
        raise _unauthorized()
    return user_from_token(authorization.removeprefix("Bearer ").strip())


def user_from_token(token: str | None) -> CurrentUser:
    if not token:
        raise _unauthorized()
    settings = load_auth_settings()
    try:
        payload = _decode_jwt(token, settings.secret)
    except ValueError as exc:
        raise _unauthorized() from exc
    username = str(payload.get("sub", ""))
    exp = int(payload.get("exp", 0))
    if exp < int(time.time()):
        raise _unauthorized()
    if not hmac.compare_digest(username, settings.username):
        raise _unauthorized()
    return CurrentUser(username=username)


async def websocket_user(websocket: WebSocket) -> CurrentUser:
    token = websocket.query_params.get("token")
    try:
        return user_from_token(token)
    except HTTPException:
        await websocket.close(code=status.WS_1008_POLICY_VIOLATION)
        raise


def require_user(_: CurrentUser = Depends(current_user)) -> None:
    return None


def _encode_jwt(payload: dict[str, Any], secret: str) -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    header_part = _b64json(header)
    payload_part = _b64json(payload)
    signature = hmac.new(secret.encode("utf-8"), f"{header_part}.{payload_part}".encode("utf-8"), hashlib.sha256)
    return f"{header_part}.{payload_part}.{_b64url(signature.digest())}"


def _decode_jwt(token: str, secret: str) -> dict[str, Any]:
    parts = token.split(".")
    if len(parts) != 3:
        raise ValueError("Malformed token")
    header_part, payload_part, signature_part = parts
    expected = hmac.new(secret.encode("utf-8"), f"{header_part}.{payload_part}".encode("utf-8"), hashlib.sha256)
    if not hmac.compare_digest(_b64url(expected.digest()), signature_part):
        raise ValueError("Invalid signature")
    header = _json_from_b64(header_part)
    if header.get("alg") != "HS256":
        raise ValueError("Unsupported token algorithm")
    return _json_from_b64(payload_part)


def _b64json(payload: dict[str, Any]) -> str:
    return _b64url(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _json_from_b64(value: str) -> dict[str, Any]:
    return json.loads(_b64decode(value).decode("utf-8"))


def _b64url(value: bytes) -> str:
    return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")


def _b64decode(value: str) -> bytes:
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(f"{value}{padding}")


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except ValueError:
        return default


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired credentials.",
        headers={"WWW-Authenticate": "Bearer"},
    )


def change_password(current_password: str, new_password: str) -> None:
    """Verify current password and update to new password.

    Updates ``os.environ`` so subsequent calls to ``load_auth_settings``
    pick up the new hash without a server restart.
    """
    settings = load_auth_settings()
    if not verify_password(current_password, settings.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect.")
    if len(new_password) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters.")
    new_hash = hash_password(new_password)
    os.environ["LOCAL_AUTH_PASSWORD_HASH"] = new_hash
    # Clear the plaintext env var so the hash takes precedence on next load
    os.environ.pop("LOCAL_AUTH_PASSWORD", None)
