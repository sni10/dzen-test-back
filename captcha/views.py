from django.utils.cache import add_never_cache_headers
from drf_spectacular.utils import extend_schema, inline_serializer
from rest_framework import serializers
from rest_framework.response import Response
from rest_framework.throttling import ScopedRateThrottle
from rest_framework.views import APIView

from .container import captcha_service


class CaptchaView(APIView):
    """A new CAPTCHA. Send `key` and the typed text with the form; each CAPTCHA is valid once, for 5 minutes."""

    throttle_classes = [ScopedRateThrottle]
    throttle_scope = 'captcha'

    @extend_schema(
        responses=inline_serializer('Captcha', {
            'key': serializers.CharField(),
            'image': serializers.CharField(help_text='PNG as a data: URI, ready for <img src>'),
            'ttl': serializers.IntegerField(help_text='Seconds until the CAPTCHA expires'),
        }),
    )
    def get(self, request):
        service = captcha_service()
        challenge = service.issue()
        response = Response({'key': challenge.key, 'image': challenge.image_data_uri, 'ttl': service.ttl})
        add_never_cache_headers(response)
        return response
