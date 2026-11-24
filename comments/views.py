from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from common.guest import client_ip, client_user_agent

from .container import comment_service
from .serializers import CommentCreateSerializer, CommentSerializer
from .services import Author, CommentError, InvalidMarkup


class CommentCreateView(APIView):
    """Post a comment or a reply. Reading goes through GraphQL."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'comment_create'

    @extend_schema(
        request=CommentCreateSerializer,
        responses={
            201: CommentSerializer,
            400: OpenApiResponse(description='Field errors: {"field": ["message"]}; invalid markup also returns '
                                             '"markup": {"code", "position"}; a wrong CAPTCHA — "captcha"'),
            429: OpenApiResponse(description='Too many comments, try later'),
        },
    )
    def post(self, request):
        serializer = CommentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        author = Author(
            user=request.user if getattr(request.user, 'is_authenticated', False) else None,
            guest_key=request.guest_key,
            ip=client_ip(request),
            user_agent=client_user_agent(request),
        )
        try:
            comment = comment_service().create(serializer.to_new_comment(), author)
        except CommentError as error:
            return Response(self._error_body(error), status=status.HTTP_400_BAD_REQUEST)

        return Response(CommentSerializer(comment).data, status=status.HTTP_201_CREATED)

    @staticmethod
    def _error_body(error: CommentError) -> dict:
        body = {error.field: [error.message]}
        if isinstance(error, InvalidMarkup):
            body['markup'] = {'code': error.code, 'position': error.position}
        return body
