from django.core.cache import cache
from django.db import connection
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers, status
from rest_framework.response import Response
from rest_framework.views import APIView


class HealthView(APIView):
    """Liveness + dependencies: used by the Docker healthcheck and the deploy script."""

    @extend_schema(
        responses=inline_serializer('Health', {
            'status': serializers.ChoiceField(['ok', 'degraded']),
            'db': serializers.BooleanField(),
            'cache': serializers.BooleanField(),
        }),
    )
    def get(self, request):
        checks = {'db': self._db_ok(), 'cache': self._cache_ok()}
        healthy = all(checks.values())
        return Response(
            {'status': 'ok' if healthy else 'degraded', **checks},
            status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @staticmethod
    def _db_ok() -> bool:
        try:
            with connection.cursor() as cursor:
                cursor.execute('SELECT 1')
            return True
        except Exception:
            return False

    @staticmethod
    def _cache_ok() -> bool:
        try:
            cache.set('health', 1, timeout=5)
            return cache.get('health') == 1
        except Exception:
            return False
