"""Guest identification: a random UUID in an httpOnly cookie.

It lets a guest see their own shadow-banned comments and lets moderators ban a guest. It is not a login:
clearing cookies gives a new identity, which is acceptable for guests.
"""
import uuid

from django.conf import settings

COOKIE_NAME = 'guest_key'
COOKIE_MAX_AGE = 60 * 60 * 24 * 365


def parse_guest_key(value: str | None) -> uuid.UUID | None:
    try:
        return uuid.UUID(value) if value else None
    except ValueError:
        return None


class GuestKeyMiddleware:
    """Sets `request.guest_key`; issues the cookie on the first request that does not have a valid one."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        key = parse_guest_key(request.COOKIES.get(COOKIE_NAME))
        is_new = key is None
        request.guest_key = key or uuid.uuid4()

        response = self.get_response(request)

        if is_new:
            response.set_cookie(
                COOKIE_NAME,
                str(request.guest_key),
                max_age=COOKIE_MAX_AGE,
                httponly=True,
                secure=not settings.DEBUG,
                samesite='Lax',  # the front and the API are served from the same site (subdomains)
            )
        return response


def forget_guest(response) -> None:
    """Signing in or out ends the guest identity of this browser: the next request gets a new one.

    Otherwise, after signing out, the browser would again be the guest who wrote here before and would see
    that guest's shadow-banned comments — confusing when a moderator banned that guest from the same browser.
    """
    response.delete_cookie(COOKIE_NAME, samesite='Lax')


def client_ip(request) -> str | None:
    """uvicorn --proxy-headers already puts the real client address (from Caddy's X-Forwarded-For) here."""
    return request.META.get('REMOTE_ADDR') or None


def client_user_agent(request) -> str:
    return request.META.get('HTTP_USER_AGENT', '')[:255]
