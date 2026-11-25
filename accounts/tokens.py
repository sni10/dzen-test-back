"""Who is calling: the user behind a JWT access token (GraphQL, WebSocket). Invalid or expired -> nobody;
the SPA refreshes the access token itself."""
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import AccessToken

from .models import User


def user_from_token(token: str | None) -> User | None:
    if not token:
        return None
    try:
        user_id = AccessToken(token)['user_id']
    except (TokenError, KeyError):
        return None
    return User.objects.filter(pk=user_id, is_active=True).first()


def user_from_request(request) -> User | None:
    header = request.META.get('HTTP_AUTHORIZATION', '')
    scheme, _, token = header.partition(' ')
    return user_from_token(token.strip()) if scheme.lower() == 'bearer' else None
