"""Where CAPTCHA answers live between "issued" and "checked". The service depends only on the protocol."""
from typing import Protocol

import redis


class CaptchaStore(Protocol):
    def save(self, key: str, answer: str, ttl: int) -> None:
        """Remember the answer for `ttl` seconds."""

    def pop(self, key: str) -> str | None:
        """Return the answer and forget it (one attempt per CAPTCHA); None if unknown or expired."""


class RedisCaptchaStore:
    """Redis expires answers by itself (TTL) and GETDEL makes reading + deleting atomic,
    so one solved CAPTCHA cannot be replayed even by two simultaneous requests."""

    prefix = 'captcha:'

    def __init__(self, client: redis.Redis):
        self.client = client

    def save(self, key: str, answer: str, ttl: int) -> None:
        self.client.set(self.prefix + key, answer, ex=ttl)

    def pop(self, key: str) -> str | None:
        value = self.client.getdel(self.prefix + key)
        return value.decode() if isinstance(value, bytes) else value
