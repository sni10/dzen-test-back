"""Live updates over WebSocket: who receives which event, the event payloads and the sender.

Payloads use the same field names as the GraphQL `Comment` type, so the SPA handles both the same way.
Visibility follows `visible_to`: a shadowed comment goes only to its author and to moderators.
"""
import logging
from typing import Protocol

from asgiref.sync import async_to_sync
from channels.layers import get_channel_layer

from .models import Attachment, Comment
from .viewer import Viewer

logger = logging.getLogger(__name__)

PUBLIC = 'comments'
MODERATORS = 'comments.moderators'


def author_group(user_id: int | None = None, guest_key=None) -> str | None:
    if user_id is not None:
        return f'comments.user.{user_id}'
    if guest_key is not None:
        return f'comments.guest.{guest_key}'
    return None


def groups_for_viewer(viewer: Viewer) -> list[str]:
    """Groups a connection joins: everyone gets public events, plus own shadowed ones, moderators all."""
    groups = [PUBLIC]
    if viewer.is_moderator:
        groups.append(MODERATORS)
    if own := author_group(viewer.user_id, viewer.guest_key):
        groups.append(own)
    return groups


def groups_for_comment(comment: Comment) -> list[str]:
    if not comment.is_shadowed:
        return [PUBLIC]
    own = author_group(comment.user_id) if comment.user_id else author_group(guest_key=comment.guest_key)
    return [MODERATORS] + ([own] if own else [])


def attachment_payload(attachment: Attachment) -> dict:
    return {
        'id': str(attachment.pk),
        'kind': attachment.kind,
        'url': attachment.file.url,
        'originalName': attachment.original_name,
        'size': attachment.size,
        'width': attachment.width,
        'height': attachment.height,
        'status': attachment.status,
    }


def comment_payload(comment: Comment) -> dict:
    parent = comment.parent
    return {
        'id': str(comment.pk),
        'userName': comment.user_name,
        'email': comment.email,
        'homePage': comment.home_page,
        'text': comment.text,
        'isUfo': comment.is_ufo,
        'score': comment.score,
        'repliesCount': comment.replies_count,
        'depth': comment.depth,
        'createdAt': comment.created_at.isoformat(),
        'parentId': str(comment.parent_id) if comment.parent_id else None,
        'rootId': str(comment.root_id) if comment.root_id else None,
        'parent': {'id': str(parent.pk), 'userName': parent.user_name, 'text': parent.text} if parent else None,
        'attachments': [] if comment.is_ufo else [attachment_payload(a) for a in comment.attachments.all()],
        'replies': {'items': [], 'hasMore': False, 'endCursor': None},
    }


class Notifier(Protocol):
    def comment_created(self, comment: Comment) -> None: ...

    def attachment_updated(self, attachment: Attachment) -> None: ...


class ChannelsNotifier:
    """Sends events through the Channels layer (Redis): from the web process and from Celery workers alike."""

    def comment_created(self, comment: Comment) -> None:
        self._send(groups_for_comment(comment), {'type': 'comment.created', 'comment': comment_payload(comment)})

    def attachment_updated(self, attachment: Attachment) -> None:
        comment = attachment.comment
        payload = {
            'type': 'attachment.updated',
            'commentId': str(comment.pk),
            'attachment': attachment_payload(attachment),
        }
        self._send(groups_for_comment(comment), payload)

    @staticmethod
    def _send(groups: list[str], payload: dict) -> None:
        """A failed broadcast must not fail the request or the task: clients catch up on reconnect."""
        try:
            layer = get_channel_layer()
            for group in groups:
                async_to_sync(layer.group_send)(group, {'type': 'live.event', 'payload': payload})
        except Exception:
            logger.exception('Live event %s was not sent', payload['type'])
