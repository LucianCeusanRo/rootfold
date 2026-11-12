from __future__ import annotations

import hashlib
import hmac
import secrets
from datetime import UTC, datetime, timedelta

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from rootfold.config import Settings
from rootfold.models import ApiKey, Operator

_bearer = HTTPBearer(auto_error=False)

PBKDF2_ROUNDS = 100_000


def hash_password(password: str, salt: bytes | None = None) -> str:
    salt = salt or secrets.token_bytes(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, PBKDF2_ROUNDS)
    return f"pbkdf2_sha256${PBKDF2_ROUNDS}${salt.hex()}${dk.hex()}"


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, rounds_s, salt_hex, hash_hex = stored.split("$")
        if algo != "pbkdf2_sha256":
            return False
        rounds = int(rounds_s)
    except ValueError:
        return False
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt_hex), rounds)
    return hmac.compare_digest(dk.hex(), hash_hex)


def hash_api_key(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def generate_api_key() -> str:
    return "rfk_" + secrets.token_urlsafe(32)


def create_access_token(username: str, settings: Settings, now: datetime) -> str:
    exp = now + timedelta(minutes=settings.jwt_expire_minutes)
    payload = {"sub": username, "iat": int(now.timestamp()), "exp": int(exp.timestamp())}
    return jwt.encode(payload, settings.jwt_secret, algorithm="HS256")


def decode_access_token(token: str, settings: Settings, now: datetime | None = None) -> str:
    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret,
            algorithms=["HS256"],
            options={"verify_exp": False, "verify_iat": False},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token") from exc
    sub = payload.get("sub")
    exp = payload.get("exp")
    if not sub:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token")
    if exp is not None:
        current = int((now or datetime.now(UTC)).timestamp())
        if int(exp) < current:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired")
    return str(sub)


def authenticate_operator(db: Session, username: str, password: str) -> Operator | None:
    op = db.query(Operator).filter(Operator.username == username).one_or_none()
    if op is None or not verify_password(password, op.password_hash):
        return None
    return op


def lookup_api_key(db: Session, raw: str, now: datetime) -> ApiKey | None:
    if not raw:
        return None
    row = db.query(ApiKey).filter(ApiKey.key_hash == hash_api_key(raw), ApiKey.revoked.is_(False)).one_or_none()
    if row is None:
        return None
    row.last_used_at = now
    return row


def require_operator(
    request: Request,
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> Operator:
    if creds is None or creds.scheme.lower() != "bearer":
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer token required")
    settings: Settings = request.app.state.settings
    db: Session = request.state.db
    username = decode_access_token(creds.credentials, settings, request.app.state.clock.now())
    op = db.query(Operator).filter(Operator.username == username).one_or_none()
    if op is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown operator")
    return op


def require_webhook_key(request: Request) -> ApiKey:
    raw = request.headers.get("x-api-key") or request.headers.get("X-API-Key")
    if not raw:
        # Also accept Authorization: Bearer for machine keys? No — keep it explicit.
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="X-API-Key required")
    db: Session = request.state.db
    now = request.app.state.clock.now()
    key = lookup_api_key(db, raw, now)
    if key is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid API key")
    return key
