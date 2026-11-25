"""Forgotten password: a one-hour, one-time link by e-mail, then a new password.

Django's token generator signs the user's current password hash and last login into the token, so the link
dies as soon as it is used (the password changes) or the user signs in. Requests never reveal whether an
account exists for an e-mail.
"""
from collections.abc import Callable
from urllib.parse import urlencode

from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.cache import cache
from django.core.exceptions import ValidationError
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode
from rest_framework_simplejwt.token_blacklist.models import BlacklistedToken, OutstandingToken

from .models import User
from .services import AuthError

COOLDOWN_SECONDS = 60  # one e-mail per address per minute, whoever asks


def reset_link(user: User, reset_url: str) -> str:
    query = urlencode({
        'uid': urlsafe_base64_encode(force_bytes(user.pk)),
        'token': default_token_generator.make_token(user),
    })
    return f'{reset_url}?{query}'


def sign_out_everywhere(user: User) -> None:
    for token in OutstandingToken.objects.filter(user=user):
        BlacklistedToken.objects.get_or_create(token=token)


class PasswordResetService:
    def __init__(self, send_email: Callable[[int, str], None]):
        self.send_email = send_email  # queues the e-mail (a Celery task); builds the link itself

    def request(self, email: str, reset_url: str) -> None:
        """Quietly does nothing for unknown or inactive addresses and during the cooldown."""
        user = User.objects.filter(email__iexact=email.strip(), is_active=True).first()
        if user is None or not cache.add(f'password-reset:{user.pk}', 1, COOLDOWN_SECONDS):
            return
        self.send_email(user.pk, reset_url)

    @staticmethod
    def confirm(uid: str, token: str, password: str) -> User:
        try:
            user = User.objects.get(pk=force_str(urlsafe_base64_decode(uid)), is_active=True)
        except (User.DoesNotExist, ValueError, TypeError, OverflowError):
            user = None
        if user is None or not default_token_generator.check_token(user, token):
            raise AuthError('token', 'The link is invalid or expired, ask for a new one')
        try:
            validate_password(password, user=user)
        except ValidationError as error:
            raise AuthError('password', ' '.join(error.messages)) from None
        user.set_password(password)
        user.save(update_fields=['password'])
        sign_out_everywhere(user)  # whoever had the old password is out
        return user
