"""/api/auth/: register, login, refresh, logout.

The access token goes back in the body (the SPA keeps it in memory, sends `Authorization: Bearer`).
The refresh token lives in an httpOnly cookie limited to /api/auth/, so scripts cannot read it and other
endpoints never receive it; it is rotated on every refresh and blacklisted when used or on logout.
"""
from urllib.parse import urlsplit

from django.conf import settings
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView
from rest_framework_simplejwt.exceptions import TokenError
from rest_framework_simplejwt.tokens import RefreshToken

from common.guest import forget_guest

from .container import auth_service, password_reset_service
from .models import User

from .serializers import (
    LoginSerializer, MeSerializer, PasswordResetConfirmSerializer, PasswordResetSerializer, RegisterSerializer,
    SessionSerializer,
)
from .services import AuthError

REFRESH_COOKIE = 'refresh_token'
REFRESH_COOKIE_PATH = '/api/auth/'


def set_refresh_cookie(response, refresh: RefreshToken) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        str(refresh),
        max_age=int(settings.SIMPLE_JWT['REFRESH_TOKEN_LIFETIME'].total_seconds()),
        path=REFRESH_COOKIE_PATH,
        httponly=True,
        secure=not settings.DEBUG,
        samesite='Lax',
    )


def session_response(user: User, refresh: RefreshToken, code=status.HTTP_200_OK) -> Response:
    response = Response({'access': str(refresh.access_token), 'user': MeSerializer(user).data}, status=code)
    set_refresh_cookie(response, refresh)
    return response


def new_session_response(user: User, code=status.HTTP_200_OK) -> Response:
    """Registration and sign-in: a new session, and the guest identity of this browser ends"""
    response = session_response(user, RefreshToken.for_user(user), code)
    forget_guest(response)
    return response


def error_response(error: AuthError) -> Response:
    return Response({error.field: [error.message]}, status=status.HTTP_400_BAD_REQUEST)


def unauthorized(message: str) -> Response:
    response = Response({'detail': message}, status=status.HTTP_401_UNAUTHORIZED)
    response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
    return response


def same_origin(request) -> bool:
    """The refresh cookie is SameSite=Lax already; a foreign Origin is refused as well."""
    origin = request.headers.get('Origin')
    return origin is None or urlsplit(origin).netloc == request.get_host()


class RegisterView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_register'

    @extend_schema(request=RegisterSerializer, responses={201: SessionSerializer, 400: OpenApiResponse(
        description='{"field": ["message"]}; a wrong CAPTCHA — "captcha"')})
    def post(self, request):
        serializer = RegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = auth_service().register(**serializer.validated_data)
        except AuthError as error:
            return error_response(error)
        return new_session_response(user, status.HTTP_201_CREATED)


class LoginView(APIView):
    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_login'

    @extend_schema(request=LoginSerializer, responses={200: SessionSerializer, 400: OpenApiResponse(
        description='{"non_field_errors": ["Wrong name, e-mail or password"]}')})
    def post(self, request):
        serializer = LoginSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = auth_service().authenticate(**serializer.validated_data)
        except AuthError as error:
            return error_response(error)
        return new_session_response(user)


class RefreshView(APIView):
    """A new access token (and a new refresh cookie) from the refresh cookie."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_refresh'

    @extend_schema(request=None, responses={200: SessionSerializer, 401: OpenApiResponse(
        description='No valid refresh cookie: sign in again')})
    def post(self, request):
        if not same_origin(request):
            return Response({'detail': 'Cross-site request refused'}, status=status.HTTP_403_FORBIDDEN)
        try:
            old = RefreshToken(request.COOKIES.get(REFRESH_COOKIE, ''))
            user = User.objects.filter(pk=old['user_id'], is_active=True).first()
            if user is None:
                raise TokenError('User not found')
            old.blacklist()  # one use only: a stolen copy stops working once the owner refreshes
        except TokenError:
            return unauthorized('Session expired, sign in again')
        return session_response(user, RefreshToken.for_user(user))


class LogoutView(APIView):
    @extend_schema(request=None, responses={204: None})
    def post(self, request):
        try:
            RefreshToken(request.COOKIES.get(REFRESH_COOKIE, '')).blacklist()
        except TokenError:
            pass  # already expired or missing: nothing to revoke
        response = Response(status=status.HTTP_204_NO_CONTENT)
        response.delete_cookie(REFRESH_COOKIE, path=REFRESH_COOKIE_PATH)
        forget_guest(response)
        return response


class PasswordResetView(APIView):
    """E-mail a one-hour reset link. The same answer whether or not the address has an account."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset'

    @extend_schema(request=PasswordResetSerializer, responses={202: None})
    def post(self, request):
        serializer = PasswordResetSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        # The link leads to the SPA on this same origin (Caddy routes /reset-password to the front)
        password_reset_service().request(serializer.validated_data['email'],
                                         request.build_absolute_uri('/reset-password'))
        return Response({'detail': 'If an account uses this e-mail, a link is on its way'},
                        status=status.HTTP_202_ACCEPTED)


class PasswordResetConfirmView(APIView):
    """Set a new password from the link; signs out every session and signs this browser in."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'auth_password_reset_confirm'

    @extend_schema(request=PasswordResetConfirmSerializer, responses={200: SessionSerializer, 400: OpenApiResponse(
        description='{"token": [...]} for a bad or used link, {"password": [...]} for a weak password')})
    def post(self, request):
        serializer = PasswordResetConfirmSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        try:
            user = password_reset_service().confirm(**serializer.validated_data)
        except AuthError as error:
            return error_response(error)
        return session_response(user, RefreshToken.for_user(user))
