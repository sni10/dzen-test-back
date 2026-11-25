from functools import cache

from captcha.container import captcha_service

from .password_reset import PasswordResetService
from .services import AuthService
from .tasks import send_password_reset


@cache
def auth_service() -> AuthService:
    return AuthService(captcha=captcha_service())


@cache
def password_reset_service() -> PasswordResetService:
    return PasswordResetService(send_email=send_password_reset.delay)
