from functools import cache

from captcha.container import captcha_service

from .services import AuthService


@cache
def auth_service() -> AuthService:
    return AuthService(captcha=captcha_service())
