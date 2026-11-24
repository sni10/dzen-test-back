"""Wiring: the only place that knows the service runs on Redis. Tests replace the store with a fake."""
from functools import cache

import redis
from django.conf import settings

from .generator import CaptchaGenerator
from .service import CaptchaService
from .stores import RedisCaptchaStore


@cache
def redis_client() -> redis.Redis:
    return redis.Redis.from_url(settings.REDIS_URL)


@cache
def captcha_service() -> CaptchaService:
    return CaptchaService(
        store=RedisCaptchaStore(redis_client()),
        generator=CaptchaGenerator(length=settings.CAPTCHA_LENGTH),
        ttl=settings.CAPTCHA_TTL,
    )
