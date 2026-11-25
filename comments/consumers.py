from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from urllib.parse import parse_qs

from accounts.tokens import user_from_token
from common.guest import COOKIE_NAME, parse_guest_key

from .live import groups_for_viewer
from .viewer import Viewer


def viewer_from_scope(scope) -> Viewer:
    """The same identity as for HTTP. Browsers cannot set headers on a WebSocket, so the access token comes
    as ?token=; the guest is known by the cookie."""
    token = parse_qs(scope.get('query_string', b'').decode()).get('token', [None])[0]
    guest_key = parse_guest_key(scope.get('cookies', {}).get(COOKIE_NAME))
    return Viewer.of(user_from_token(token), guest_key)


class CommentsConsumer(AsyncJsonWebsocketConsumer):
    """`/ws/comments/`: server push only. Events: comment.created, attachment.updated."""

    async def connect(self):
        viewer = await database_sync_to_async(viewer_from_scope)(self.scope)
        self.live_groups = groups_for_viewer(viewer)
        for group in self.live_groups:
            await self.channel_layer.group_add(group, self.channel_name)
        await self.accept()

    async def disconnect(self, code):
        for group in getattr(self, 'live_groups', []):
            await self.channel_layer.group_discard(group, self.channel_name)

    async def receive_json(self, content, **kwargs):
        pass  # ponytail: nothing to receive yet; the SPA writes through REST / GraphQL

    async def live_event(self, message):
        await self.send_json(message['payload'])
