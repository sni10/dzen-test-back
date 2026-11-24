import uuid
from unittest import mock

from asgiref.sync import sync_to_async
from channels.testing import WebsocketCommunicator
from django.core.files.base import ContentFile
from django.test import TestCase, TransactionTestCase, override_settings

from accounts.models import User
from comments.live import (
    MODERATORS, PUBLIC, ChannelsNotifier, comment_payload, groups_for_comment, groups_for_viewer,
)
from comments.markup import CommentMarkup
from comments.models import Attachment
from comments.services import Author, CommentService, NewComment
from comments.viewer import Viewer
from common.guest import COOKIE_NAME
from config.asgi import application

from .factories import make_comment
from .test_attachments import MEDIA_ROOT, image_bytes
from .test_create import FakeCaptcha, RecordingNotifier

IN_MEMORY = {'default': {'BACKEND': 'channels.layers.InMemoryChannelLayer'}}


class GroupsTests(TestCase):
    def test_viewer_groups(self):
        key = uuid.uuid4()
        self.assertEqual(groups_for_viewer(Viewer()), [PUBLIC])
        self.assertEqual(groups_for_viewer(Viewer(guest_key=key)), [PUBLIC, f'comments.guest.{key}'])
        self.assertEqual(groups_for_viewer(Viewer(user_id=5, is_moderator=True)),
                         [PUBLIC, MODERATORS, 'comments.user.5'])

    def test_public_comment_goes_to_everyone(self):
        self.assertEqual(groups_for_comment(make_comment()), [PUBLIC])

    def test_shadowed_comment_goes_only_to_its_author_and_moderators(self):
        key = uuid.uuid4()
        user = User.objects.create_user('shadow', 's@example.com', 'a-long-password-1')

        self.assertEqual(groups_for_comment(make_comment(is_shadowed=True, guest_key=key)),
                         [MODERATORS, f'comments.guest.{key}'])
        self.assertEqual(groups_for_comment(make_comment(is_shadowed=True, user=user)),
                         [MODERATORS, f'comments.user.{user.pk}'])


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class PayloadTests(TestCase):
    def test_same_fields_as_the_graphql_comment(self):
        root = make_comment(text='Root')
        reply = make_comment(parent=root, text='Reply')
        attachment = Attachment(comment=reply, kind='image', original_name='a.png', size=1, status='processing')
        attachment.file.save('a.png', ContentFile(b'x'), save=False)
        attachment.save()

        payload = comment_payload(reply)

        self.assertEqual(payload['id'], str(reply.pk))
        self.assertEqual((payload['parentId'], payload['rootId']), (str(root.pk), str(root.pk)))
        self.assertEqual(payload['parent'], {'id': str(root.pk), 'userName': root.user_name, 'text': 'Root'})
        self.assertEqual(payload['attachments'][0]['status'], 'processing')
        self.assertEqual(payload['replies'], {'items': [], 'hasMore': False, 'endCursor': None})
        for private in ('ip', 'userAgent', 'guestKey', 'isShadowed'):
            self.assertNotIn(private, payload)

    def test_moderator_hidden_comment_has_no_attachments(self):
        comment = make_comment(is_ufo=True)
        Attachment.objects.create(comment=comment, kind='text', file='x.txt', original_name='x.txt', size=1)

        self.assertEqual(comment_payload(comment)['attachments'], [])


class ServiceNotifiesTests(TestCase):
    def test_created_comment_is_broadcast_after_commit(self):
        captcha, notifier = FakeCaptcha(), RecordingNotifier()
        service = CommentService(CommentMarkup(), captcha.service, lambda pk: None, notifier)
        data = NewComment(user_name='Anonym', email='a@example.com', text='Hi', captcha_key=captcha.new_key(),
                          captcha_answer='Ab3Cd')

        with self.captureOnCommitCallbacks() as callbacks:
            comment = service.create(data, Author())
            self.assertEqual(notifier.created, [])  # nothing before the commit
        for callback in callbacks:
            callback()

        self.assertEqual(notifier.created, [comment])


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class TaskNotifiesTests(TestCase):
    def test_processed_attachment_is_broadcast(self):
        from comments.tasks import process_attachment

        attachment = Attachment(comment=make_comment(), kind='image', original_name='a.jpg', size=1)
        attachment.file.save('a.jpg', ContentFile(image_bytes()), save=False)
        attachment.save()

        with mock.patch.object(ChannelsNotifier, 'attachment_updated') as notified:
            process_attachment(attachment.pk)

        self.assertEqual(notified.call_args.args[0].status, 'ready')


@override_settings(CHANNEL_LAYERS=IN_MEMORY, ALLOWED_HOSTS=['testserver', 'localhost'])
class WebSocketTests(TransactionTestCase):
    """Through the real ASGI application: origin check, cookies, groups, events.

    TransactionTestCase: the consumer closes stale DB connections (database_sync_to_async), which would
    break the per-test transaction of TestCase.
    """

    async def connect(self, origin='http://localhost', guest_key=None):
        headers = [(b'origin', origin.encode())]
        if guest_key:
            headers.append((b'cookie', f'{COOKIE_NAME}={guest_key}'.encode()))
        communicator = WebsocketCommunicator(application, '/ws/comments/', headers=headers)
        connected, _ = await communicator.connect()
        return communicator, connected

    async def test_public_comment_reaches_every_connection(self):
        first, ok_first = await self.connect()
        second, ok_second = await self.connect(guest_key=uuid.uuid4())
        self.assertTrue(ok_first and ok_second)

        comment = await sync_to_async(make_comment)(text='Live!')
        await sync_to_async(ChannelsNotifier().comment_created)(comment)

        for communicator in (first, second):
            event = await communicator.receive_json_from(timeout=2)
            self.assertEqual((event['type'], event['comment']['id'], event['comment']['text']),
                             ('comment.created', str(comment.pk), 'Live!'))
            await communicator.disconnect()

    async def test_shadowed_comment_reaches_only_its_author(self):
        key = uuid.uuid4()
        author, _ = await self.connect(guest_key=key)
        stranger, _ = await self.connect(guest_key=uuid.uuid4())

        comment = await sync_to_async(make_comment)(is_shadowed=True, guest_key=key)
        await sync_to_async(ChannelsNotifier().comment_created)(comment)

        self.assertEqual((await author.receive_json_from(timeout=2))['comment']['id'], str(comment.pk))
        self.assertTrue(await stranger.receive_nothing(timeout=0.3))
        await author.disconnect()
        await stranger.disconnect()

    async def test_attachment_update_event(self):
        communicator, _ = await self.connect()

        def make_attachment():
            attachment = Attachment.objects.create(comment=make_comment(), kind='text', file='x.txt',
                                                   original_name='x.txt', size=3, status='ready')
            ChannelsNotifier().attachment_updated(attachment)
            return attachment

        attachment = await sync_to_async(make_attachment)()

        event = await communicator.receive_json_from(timeout=2)
        self.assertEqual(event['type'], 'attachment.updated')
        self.assertEqual(event['commentId'], str(attachment.comment_id))
        self.assertEqual(event['attachment']['status'], 'ready')
        await communicator.disconnect()

    async def test_other_sites_cannot_connect(self):
        communicator, connected = await self.connect(origin='https://evil.example')

        self.assertFalse(connected)

    async def test_messages_from_the_client_are_ignored(self):
        communicator, _ = await self.connect()

        await communicator.send_json_to({'type': 'anything'})

        self.assertTrue(await communicator.receive_nothing(timeout=0.2))
        await communicator.disconnect()


class BroadcastFailureTests(TestCase):
    def test_a_failed_broadcast_does_not_raise(self):
        with mock.patch('comments.live.get_channel_layer', side_effect=ConnectionError), \
                self.assertLogs('comments.live', 'ERROR'):
            ChannelsNotifier().comment_created(make_comment())
