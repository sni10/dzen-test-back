"""ASGI entry point (uvicorn): HTTP goes to Django, WebSocket to Channels."""
import os

from django.core.asgi import get_asgi_application

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'config.settings')

django_application = get_asgi_application()  # set up Django before importing code that uses models

from channels.routing import ProtocolTypeRouter, URLRouter  # noqa: E402
from channels.security.websocket import AllowedHostsOriginValidator  # noqa: E402
from channels.sessions import CookieMiddleware  # noqa: E402
from django.urls import path  # noqa: E402

from comments.consumers import CommentsConsumer  # noqa: E402

websocket_urlpatterns = [path('ws/comments/', CommentsConsumer.as_asgi())]

application = ProtocolTypeRouter({
    'http': django_application,
    # Origin must be one of ALLOWED_HOSTS: another site cannot open a socket with the visitor's cookies.
    # Identity: the JWT in ?token= or the guest cookie (no session auth, as for the API).
    'websocket': AllowedHostsOriginValidator(CookieMiddleware(URLRouter(websocket_urlpatterns))),
})
