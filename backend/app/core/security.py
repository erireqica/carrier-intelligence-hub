import hashlib
import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type

password_hasher = PasswordHasher(type=Type.ID)
dummy_password_hash = password_hasher.hash("carrier-hub-timing-protection")

PUBLIC_EMAIL_PROVIDER_DOMAINS = frozenset(
    {
        "aol.com",
        "gmail.com",
        "googlemail.com",
        "hotmail.com",
        "icloud.com",
        "live.com",
        "outlook.com",
        "proton.me",
        "protonmail.com",
        "yahoo.com",
    }
)


def hash_password(password: str) -> str:
    return password_hasher.hash(password)


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return password_hasher.verify(password_hash, password)
    except InvalidHashError, VerifyMismatchError:
        return False


def new_session_token() -> str:
    return secrets.token_urlsafe(48)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def csrf_token_for_session(session_token: str) -> str:
    return hashlib.sha256(f"carrier-hub-csrf:{session_token}".encode()).hexdigest()


def normalize_email(email: str) -> str:
    return email.strip().casefold()


def normalize_domain(domain: str) -> str:
    return domain.strip().lower().lstrip("@.")
