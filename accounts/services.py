"""Registration and sign-in. Tokens: a short-lived access token for the Authorization header and a
long-lived refresh token kept in an httpOnly cookie (see accounts/views.py)."""
from django.contrib.auth.hashers import make_password
from django.db import IntegrityError, transaction
from django.db.models import Q

from captcha.service import CaptchaService

from .models import User


class AuthError(Exception):
    """A rule violation reported to the client as a field error."""

    def __init__(self, field: str, message: str):
        super().__init__(message)
        self.field = field
        self.message = message


class AuthService:
    def __init__(self, captcha: CaptchaService):
        self.captcha = captcha

    def register(self, username: str, email: str, password: str, captcha_key: str, captcha_answer: str) -> User:
        """Field formats and password strength are checked by the serializer; uniqueness here, CAPTCHA last."""
        if User.objects.filter(username__iexact=username).exists():
            raise AuthError('username', 'This name is taken')
        if User.objects.filter(email__iexact=email).exists():
            raise AuthError('email', 'An account with this e-mail already exists')
        if not self.captcha.verify(captcha_key, captcha_answer):
            raise AuthError('captcha', 'Wrong or expired CAPTCHA, enter the new one')
        try:
            with transaction.atomic():
                return User.objects.create_user(username=username, email=email.lower(), password=password)
        except IntegrityError:  # registered by a parallel request in the meantime
            raise AuthError('username', 'This name or e-mail is taken') from None

    @staticmethod
    def authenticate(login: str, password: str) -> User:
        """By user name or e-mail. One message for every failure: it must not reveal which accounts exist."""
        user = User.objects.filter(Q(username__iexact=login) | Q(email__iexact=login)).first()
        if user is None:
            make_password(password)  # spend the same time as a real check
        elif user.is_active and user.check_password(password):
            return user
        raise AuthError('non_field_errors', 'Wrong name, e-mail or password')
