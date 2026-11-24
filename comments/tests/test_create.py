import uuid
from unittest import mock

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from captcha.generator import CaptchaGenerator
from captcha.service import CaptchaService
from captcha.tests.fakes import InMemoryCaptchaStore
from comments.markup import CommentMarkup
from comments.models import Comment
from comments.services import (
    Author, CaptchaInvalid, CommentService, InvalidMarkup, NewComment, ParentNotFound,
)
from common.guest import COOKIE_NAME

from .factories import make_comment


class FakeCaptcha:
    """Issues CAPTCHAs with a known answer on the in-memory store."""

    def __init__(self):
        self.generator = CaptchaGenerator()
        self.service = CaptchaService(InMemoryCaptchaStore(), self.generator)

    def new_key(self, answer='Ab3Cd') -> str:
        with mock.patch.object(self.generator, 'text', return_value=answer):
            return self.service.issue().key


class CommentServiceTests(TestCase):
    def setUp(self):
        self.captcha = FakeCaptcha()
        self.service = CommentService(CommentMarkup(), self.captcha.service, process_attachment=lambda pk: None)
        self.guest = Author(guest_key=uuid.uuid4(), ip='203.0.113.7', user_agent='Test/1.0')

    def data(self, **overrides) -> NewComment:
        fields = {
            'user_name': 'Anonym', 'email': 'anonym@example.com', 'text': 'Hello <i>world</i>',
            'captcha_key': self.captcha.new_key(), 'captcha_answer': 'ab3cd',
        }
        return NewComment(**{**fields, **overrides})

    def test_guest_comment_is_saved_with_client_identification(self):
        comment = self.service.create(self.data(home_page='https://example.com'), self.guest)

        comment.refresh_from_db()
        self.assertEqual((comment.user_name, comment.email), ('Anonym', 'anonym@example.com'))
        self.assertEqual(comment.home_page, 'https://example.com')
        self.assertEqual(comment.text, 'Hello <i>world</i>')
        self.assertEqual(comment.guest_key, self.guest.guest_key)
        self.assertEqual((comment.ip, comment.user_agent), ('203.0.113.7', 'Test/1.0'))
        self.assertIsNone(comment.user)
        self.assertTrue(comment.is_top_level)

    def test_text_is_sanitized(self):
        comment = self.service.create(self.data(text='1 < 2 & <a href="https://e.com">e</a>'), self.guest)

        self.assertTrue(comment.text.startswith('1 &lt; 2 &amp; <a href="https://e.com"'))
        self.assertIn('rel="nofollow ugc noopener noreferrer"', comment.text)

    def test_invalid_markup_is_rejected_and_keeps_the_captcha(self):
        key = self.captcha.new_key()

        with self.assertRaises(InvalidMarkup) as ctx:
            self.service.create(self.data(text='<b>x</b>', captcha_key=key), self.guest)

        self.assertEqual((ctx.exception.code, ctx.exception.position), ('unknown_tag', 0))
        self.service.create(self.data(captcha_key=key), self.guest)  # the CAPTCHA still works
        self.assertEqual(Comment.objects.count(), 1)

    def test_wrong_captcha(self):
        with self.assertRaises(CaptchaInvalid):
            self.service.create(self.data(captcha_answer='wrong'), self.guest)
        self.assertFalse(Comment.objects.exists())

    def test_captcha_is_single_use(self):
        key = self.captcha.new_key()
        self.service.create(self.data(captcha_key=key), self.guest)

        with self.assertRaises(CaptchaInvalid):
            self.service.create(self.data(captcha_key=key), self.guest)

    def test_reply_joins_the_thread_and_counts(self):
        root = self.service.create(self.data(), self.guest)
        reply = self.service.create(self.data(parent_id=root.pk), self.guest)
        deep = self.service.create(self.data(parent_id=reply.pk), self.guest)

        self.assertEqual((reply.root_id, reply.depth), (root.pk, 1))
        self.assertEqual((deep.root_id, deep.depth), (root.pk, 2))
        root.refresh_from_db()
        reply.refresh_from_db()
        self.assertEqual((root.replies_count, reply.replies_count), (1, 1))

    def test_reply_to_missing_parent(self):
        with self.assertRaises(ParentNotFound):
            self.service.create(self.data(parent_id=999999), self.guest)

    def test_cannot_reply_to_a_comment_the_author_cannot_see(self):
        hidden = make_comment(is_shadowed=True, guest_key=uuid.uuid4())

        with self.assertRaises(ParentNotFound):
            self.service.create(self.data(parent_id=hidden.pk), self.guest)

    def test_shadowed_guest_can_reply_to_own_comment(self):
        own = make_comment(is_shadowed=True, guest_key=self.guest.guest_key)

        reply = self.service.create(self.data(parent_id=own.pk), self.guest)

        self.assertEqual(reply.parent_id, own.pk)

    def test_registered_user_posts_under_profile_identity(self):
        user = User.objects.create_user('Rum8', 'rum@example.com', 'a-long-password-1')

        comment = self.service.create(self.data(user_name='Other', email='other@example.com'), Author(user=user))

        self.assertEqual((comment.user, comment.user_name, comment.email), (user, 'Rum8', 'rum@example.com'))
        self.assertIsNone(comment.guest_key)
        self.assertFalse(comment.is_shadowed)

    def test_shadowbanned_user_comment_is_shadowed(self):
        user = User.objects.create_user('shadow', 'shadow@example.com', 'a-long-password-1', is_shadowbanned=True)

        comment = self.service.create(self.data(), Author(user=user))

        self.assertTrue(comment.is_shadowed)

    def test_shadowed_reply_is_not_counted(self):
        user = User.objects.create_user('shadow', 'shadow@example.com', 'a-long-password-1', is_shadowbanned=True)
        root = make_comment()

        self.service.create(self.data(parent_id=root.pk), Author(user=user))

        root.refresh_from_db()
        self.assertEqual(root.replies_count, 0)

    def test_moderator_needs_no_captcha(self):
        admin = User.objects.create_user('mod', 'mod@example.com', 'a-long-password-1', role=User.Role.ADMIN)

        comment = self.service.create(self.data(captcha_key='', captcha_answer=''), Author(user=admin))

        self.assertEqual(comment.user, admin)


class CommentCreateApiTests(TestCase):
    url = reverse('comment-create')

    def setUp(self):
        cache.clear()  # throttle counters
        rates = mock.patch.dict('rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES',
                                {'comment_create': '1000/min'})
        rates.start()
        self.addCleanup(rates.stop)
        self.captcha = FakeCaptcha()
        patcher = mock.patch('comments.container.captcha_service', return_value=self.captcha.service)
        patcher.start()
        self.addCleanup(patcher.stop)
        from comments.container import comment_service
        comment_service.cache_clear()
        self.addCleanup(comment_service.cache_clear)

    def payload(self, **overrides) -> dict:
        return {
            'user_name': 'Anonym', 'email': 'anonym@example.com', 'home_page': '',
            'text': 'Hello <strong>world</strong>', 'captcha_key': self.captcha.new_key(), 'captcha_answer': 'Ab3Cd',
            **overrides,
        }

    def post(self, **overrides):
        return self.client.post(self.url, self.payload(**overrides), content_type='application/json',
                                HTTP_USER_AGENT='Browser/2.0')

    def test_created(self):
        response = self.post()

        self.assertEqual(response.status_code, 201)
        body = response.json()
        self.assertEqual(body['user_name'], 'Anonym')
        self.assertEqual(body['text'], 'Hello <strong>world</strong>')
        self.assertEqual((body['parent'], body['depth'], body['replies_count']), (None, 0, 0))
        for private in ('ip', 'user_agent', 'guest_key', 'is_shadowed', 'user'):
            self.assertNotIn(private, body)
        comment = Comment.objects.get()
        self.assertEqual((comment.ip, comment.user_agent), ('127.0.0.1', 'Browser/2.0'))

    def test_multipart_form_is_accepted(self):
        response = self.client.post(self.url, self.payload())

        self.assertEqual(response.status_code, 201)

    def test_guest_cookie_is_issued_once_and_identifies_the_author(self):
        first = self.post()
        cookie = first.cookies[COOKIE_NAME]
        self.assertTrue(cookie['httponly'])

        second = self.post()

        self.assertNotIn(COOKIE_NAME, second.cookies)
        keys = set(Comment.objects.values_list('guest_key', flat=True))
        self.assertEqual(keys, {uuid.UUID(cookie.value)})

    def test_reply(self):
        root = self.post().json()

        response = self.post(parent=root['id'])

        self.assertEqual(response.status_code, 201)
        self.assertEqual((response.json()['parent'], response.json()['root']), (root['id'], root['id']))

    def test_field_validation(self):
        cases = {
            'user_name': ['', 'a', 'bad name', 'юзер', 'x' * 51],
            'email': ['', 'not-an-email', 'a@'],
            'home_page': ['example.com', 'ftp://example.com', 'javascript:alert(1)'],
            'text': ['', '   ', 'x' * 5001],
            'captcha_answer': [''],
            'parent': ['abc', 0],
        }
        for field, values in cases.items():
            for value in values:
                with self.subTest(field=field, value=value):
                    response = self.post(**{field: value})
                    self.assertEqual(response.status_code, 400)
                    self.assertIn(field, response.json())
        self.assertFalse(Comment.objects.exists())

    def test_invalid_markup_reports_code_and_position(self):
        response = self.post(text='ok <i>unclosed')

        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.json()['markup'], {'code': 'unclosed_tag', 'position': 3})
        self.assertIn('text', response.json())

    def test_wrong_captcha(self):
        response = self.post(captcha_answer='wrong')

        self.assertEqual(response.status_code, 400)
        self.assertIn('captcha', response.json())

    def test_unknown_parent(self):
        response = self.post(parent=999999)

        self.assertEqual(response.status_code, 400)
        self.assertIn('parent', response.json())

    def test_xss_attempts_never_reach_the_database(self):
        for text in ('<script>alert(1)</script>', '<img src=x onerror=alert(1)>',
                     '<a href="javascript:alert(1)">x</a>', '<i onmouseover="x()">t</i>'):
            with self.subTest(text=text):
                self.assertEqual(self.post(text=text).status_code, 400)
        self.assertFalse(Comment.objects.exists())

    def test_rate_limited(self):
        with mock.patch.dict('rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES', {'comment_create': '2/min'}):
            codes = [self.post().status_code for _ in range(3)]

        self.assertEqual(codes, [201, 201, 429])
