from channels.db import database_sync_to_async
from channels.generic.websocket import AsyncJsonWebsocketConsumer

from common.guest import COOKIE_NAME, parse_guest_key

from .live import groups_for_viewer
from .viewer import Viewer


def viewer_from_scope(scope) -> Viewer:
    """The same identity as for HTTP: the signed-in user (session), otherwise the guest cookie."""
    user = scope.get('user')
    if user is not None and user.is_authenticated:
        return Viewer(user_id=user.pk, is_moderator=user.is_moderator)
    return Viewer(guest_key=parse_guest_key(scope.get('cookies', {}).get(COOKIE_NAME)))


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
