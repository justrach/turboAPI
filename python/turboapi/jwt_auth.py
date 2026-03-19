"""
TurboAPI JWT Authentication

Drop-in JWT auth for TurboAPI/FastAPI — mirrors the python-jose / FastAPI docs pattern
but uses PyJWT directly (no extra deps beyond PyJWT + cryptography).

Usage:
    from turboapi.jwt_auth import (
        create_access_token, decode_token, JWTBearer,
        JWTSettings, TokenData
    )
    from turboapi import TurboAPI, Depends
    from turboapi.security import OAuth2PasswordBearer

    settings = JWTSettings(secret_key="your-secret", algorithm="HS256")
    oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/auth/token")

    @app.post("/auth/token")
    def login(form: OAuth2PasswordRequestForm = Depends()):
        user = authenticate_user(form.username, form.password)
        if not user:
            raise HTTPException(status_code=401, detail="Bad credentials")
        token = create_access_token({"sub": user.username}, settings=settings)
        return {"access_token": token, "token_type": "bearer"}

    async def get_current_user(token: str = Depends(oauth2_scheme)):
        return decode_token(token, settings=settings)

    @app.get("/me")
    def me(user: TokenData = Depends(get_current_user)):
        return {"username": user.sub}
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

# Lazy import — jwt is optional. ImportError is deferred to call time so that
# `from turboapi import TurboAPI` works even without PyJWT installed.
_jwt = None
_jwt_import_error: Exception | None = None
try:
    import jwt as _jwt  # type: ignore[no-redef]
    from jwt.exceptions import ExpiredSignatureError, InvalidTokenError
except ImportError:
    _jwt_import_error = ImportError(
        "PyJWT is required for JWT auth. Install it with: pip install PyJWT cryptography"
    )

    class ExpiredSignatureError(Exception):  # type: ignore[no-redef]
        pass

    class InvalidTokenError(Exception):  # type: ignore[no-redef]
        pass


def _require_jwt() -> None:
    """Raise at call time if PyJWT is not installed."""
    if _jwt_import_error is not None:
        raise _jwt_import_error


from .exceptions import HTTPException  # noqa: E402
from .security import SecurityBase  # noqa: E402

# ---------------------------------------------------------------------------
# Settings
# ---------------------------------------------------------------------------


@dataclass
class JWTSettings:
    """JWT configuration. Create once at app startup."""

    secret_key: str
    algorithm: str = "HS256"
    access_token_expire_seconds: int = 30 * 60  # 30 minutes
    refresh_token_expire_seconds: int = 7 * 24 * 3600  # 7 days
    # For RS256/ES256 pass public_key / private_key instead of secret_key
    private_key: str | None = None
    public_key: str | None = None


# ---------------------------------------------------------------------------
# Token data model
# ---------------------------------------------------------------------------


@dataclass
class TokenData:
    """Decoded JWT payload."""

    sub: str  # subject (usually user id / username)
    exp: int | None = None  # expiry unix timestamp
    scopes: list[str] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def is_expired(self) -> bool:
        if self.exp is None:
            return False
        return time.time() > self.exp


# ---------------------------------------------------------------------------
# Token creation
# ---------------------------------------------------------------------------


def create_access_token(
    data: dict[str, Any],
    *,
    settings: JWTSettings,
    expires_in: int | None = None,
) -> str:
    """
    Create a signed JWT access token.

    Args:
        data: Payload dict. Must include "sub" (subject).
        settings: JWTSettings instance.
        expires_in: Override expiry in seconds. Defaults to settings.access_token_expire_seconds.

    Returns:
        Encoded JWT string.
    """
    _require_jwt()
    payload = dict(data)
    expire = int(time.time()) + (expires_in or settings.access_token_expire_seconds)
    payload["exp"] = expire

    key = settings.private_key or settings.secret_key
    return _jwt.encode(payload, key, algorithm=settings.algorithm)  # type: ignore[union-attr]


def create_refresh_token(
    data: dict[str, Any],
    *,
    settings: JWTSettings,
    expires_in: int | None = None,
) -> str:
    _require_jwt()
    payload = dict(data)
    expire = int(time.time()) + (expires_in or settings.refresh_token_expire_seconds)
    payload["exp"] = expire
    payload["type"] = "refresh"

    key = settings.private_key or settings.secret_key
    return _jwt.encode(payload, key, algorithm=settings.algorithm)  # type: ignore[union-attr]
    return _jwt.encode(payload, key, algorithm=settings.algorithm)


# ---------------------------------------------------------------------------
# Token decoding / validation
# ---------------------------------------------------------------------------


def decode_token(
    token: str,
    *,
    settings: JWTSettings,
    required_scopes: list[str] | None = None,
) -> TokenData:
    """
    Decode and validate a JWT token.

    Raises HTTPException(401) on invalid/expired tokens.
    Raises HTTPException(403) on insufficient scopes.
    """
    _require_jwt()
    try:
        key = settings.public_key or settings.secret_key
        payload = _jwt.decode(token, key, algorithms=[settings.algorithm])  # type: ignore[union-attr]
    except ExpiredSignatureError:
        raise HTTPException(
            status_code=401,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except InvalidTokenError as e:
        raise HTTPException(
            status_code=401,
            detail=f"Invalid token: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )

    sub = payload.get("sub")
    if not sub:
        raise HTTPException(
            status_code=401,
            detail="Token missing subject (sub)",
            headers={"WWW-Authenticate": "Bearer"},
        )

    token_scopes: list[str] = payload.get("scopes", [])
    if required_scopes:
        missing = [s for s in required_scopes if s not in token_scopes]
        if missing:
            raise HTTPException(
                status_code=403,
                detail=f"Insufficient scopes. Required: {required_scopes}",
                headers={"WWW-Authenticate": f'Bearer scope="{" ".join(required_scopes)}"'},
            )

    extra = {k: v for k, v in payload.items() if k not in ("sub", "exp", "scopes", "type")}
    return TokenData(
        sub=str(sub),
        exp=payload.get("exp"),
        scopes=token_scopes,
        extra=extra,
    )


# ---------------------------------------------------------------------------
# JWTBearer — use as a Depends() security scheme
# ---------------------------------------------------------------------------


class JWTBearer(SecurityBase):
    """
    FastAPI/TurboAPI-compatible JWT security dependency.

    Usage:
        jwt = JWTBearer(settings=JWTSettings(secret_key="secret"))

        @app.get("/protected")
        def protected(user: TokenData = Depends(jwt)):
            return {"user": user.sub}
    """

    def __init__(
        self,
        *,
        settings: JWTSettings,
        required_scopes: list[str] | None = None,
        auto_error: bool = True,
    ):
        super().__init__(scheme_name="Bearer", auto_error=auto_error)
        self.settings = settings
        self.required_scopes = required_scopes

    def __call__(self, authorization: str | None = None) -> TokenData | None:
        if not authorization:
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Not authenticated",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None

        parts = authorization.split(" ", 1)
        if len(parts) != 2 or parts[0].lower() != "bearer":
            if self.auto_error:
                raise HTTPException(
                    status_code=401,
                    detail="Invalid authentication scheme. Expected: Bearer <token>",
                    headers={"WWW-Authenticate": "Bearer"},
                )
            return None

        return decode_token(
            parts[1],
            settings=self.settings,
            required_scopes=self.required_scopes,
        )


# ---------------------------------------------------------------------------
# Password hashing (replaces the insecure stubs in security.py)
# ---------------------------------------------------------------------------

try:
    from passlib.context import CryptContext as _CryptContext

    _pwd_context = _CryptContext(schemes=["bcrypt"], deprecated="auto")

    def hash_password(password: str) -> str:
        """Hash a password with bcrypt (requires passlib)."""
        return _pwd_context.hash(password)

    def verify_password(plain: str, hashed: str) -> bool:
        """Verify a password against a bcrypt hash (requires passlib)."""
        return _pwd_context.verify(plain, hashed)

except ImportError:
    import hashlib as _hashlib
    import hmac as _hmac

    def hash_password(password: str) -> str:  # type: ignore[misc]
        """SHA-256 fallback -- install passlib[bcrypt] for production use."""
        import secrets as _secrets

        salt = _secrets.token_hex(16)
        digest = _hashlib.sha256(f"{salt}{password}".encode()).hexdigest()
        return f"sha256${salt}${digest}"

    def verify_password(plain: str, hashed: str) -> bool:  # type: ignore[misc]
        """Verify SHA-256 hashed password."""
        try:
            _, salt, digest = hashed.split("$", 2)
            expected = _hashlib.sha256(f"{salt}{plain}".encode()).hexdigest()
            return _hmac.compare_digest(digest, expected)
        except Exception:
            return False


__all__ = [
    "JWTSettings",
    "TokenData",
    "JWTBearer",
    "create_access_token",
    "create_refresh_token",
    "decode_token",
    "hash_password",
    "verify_password",
]
