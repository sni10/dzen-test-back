from smtplib import SMTPException
from urllib.parse import urlsplit

from celery import shared_task
from django.core.mail import send_mail

from .models import User
from .password_reset import reset_link


@shared_task(autoretry_for=(SMTPException, OSError), retry_backoff=True, max_retries=3)
def send_password_reset(user_id: int, reset_url: str) -> None:
    """The link (with its secret token) is built here, so it never travels through the broker."""
    user = User.objects.filter(pk=user_id, is_active=True).first()
    if user is None:
        return
    site = urlsplit(reset_url).netloc
    send_mail(
        subject='Reset your password',
        message=(
            f'Hello, {user.username}!\n\n'
            f'Someone (hopefully you) asked to reset the password for your account on {site}.\n'
            f'Set a new password here:\n\n{reset_link(user, reset_url)}\n\n'
            'The link works for one hour and only once. If it was not you, just ignore this e-mail: '
            'your password stays the same.\n'
        ),
        from_email=None,  # DEFAULT_FROM_EMAIL
        recipient_list=[user.email],
    )
