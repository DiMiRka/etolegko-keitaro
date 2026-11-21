import base64
import hashlib
import hmac
import json
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass

COOKIE_NAME = "kw_session"
MIN_PASSWORD_LENGTH = 8
_SCRYPT = {"n": 2**14, "r": 8, "p": 1}


@dataclass(frozen=True)
class CurrentUser:
    id: int
    username: str


current_user: ContextVar[CurrentUser | None] = ContextVar("current_user", default=None)


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, dklen=32, **_SCRYPT)
    return "scrypt${n}${r}${p}${salt}${digest}".format(
        **_SCRYPT, salt=salt.hex(), digest=digest.hex()
    )


def verify_password(password: str, stored: str) -> bool:
    try:
        algo, n, r, p, salt, digest = stored.split("$")
        if algo != "scrypt":
            return False
        actual = hashlib.scrypt(
            password.encode(), salt=bytes.fromhex(salt), dklen=len(bytes.fromhex(digest)),
            n=int(n), r=int(r), p=int(p),
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(actual.hex(), digest)


def _b64(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def _unb64(data: str) -> bytes:
    return base64.urlsafe_b64decode(data + "=" * (-len(data) % 4))


def _sign(payload: str, secret: str) -> str:
    return _b64(hmac.new(secret.encode(), payload.encode(), hashlib.sha256).digest())


def make_token(user: CurrentUser, secret: str, ttl_seconds: int, now: float | None = None) -> str:
    body = {"uid": user.id, "u": user.username, "exp": int((now or time.time()) + ttl_seconds)}
    payload = _b64(json.dumps(body, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload, secret)}"


def read_token(token: str | None, secret: str, now: float | None = None) -> CurrentUser | None:
    if not token or "." not in token:
        return None
    payload, signature = token.rsplit(".", 1)
    if not hmac.compare_digest(signature, _sign(payload, secret)):
        return None
    try:
        body = json.loads(_unb64(payload))
        if body["exp"] < (now or time.time()):
            return None
        return CurrentUser(int(body["uid"]), str(body["u"]))
    except (ValueError, KeyError, TypeError):
        return None


def safe_next(path: str | None) -> str:
    if not path or not path.startswith("/") or path.startswith("//") or "\\" in path:
        return "/"
    return path
