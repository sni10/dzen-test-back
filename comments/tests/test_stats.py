import uuid

from django.core.cache import cache
from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from comments import stats
from comments.markup import CommentMarkup
from comments.models import Bookmark
from comments.services import Author, CommentService, NewComment
from comments.viewer import Viewer

from .factories import make_comment
from .test_create import FakeCaptcha, RecordingNotifier

QUERY = '{ stats { comments ufo shadowed myComments myBookmarks } }'


class StatsTests(TestCase):
    def setUp(self):
        cache.clear()
        self.user = User.objects.create_user('Rum8', 'rum@example.com', 'pw-long-enough-1')
        self.guest = uuid.uuid4()
        make_comment()
        make_comment(user=self.user)
        make_comment(is_ufo=True)
        make_comment(is_shadowed=True, guest_key=self.guest)
        make_comment(is_shadowed=True, guest_key=uuid.uuid4())
        Bookmark.objects.create(user=self.user, comment=make_comment())

    def test_a_guest_sees_public_counts_only(self):
        self.assertEqual(stats.stats_for(Viewer.anonymous()),
                         stats.Stats(comments=4, ufo=1, shadowed=None, my_comments=None, my_bookmarks=None))

    def test_a_shadowed_author_counts_own_hidden_comments_but_not_the_shadow_total(self):
        found = stats.stats_for(Viewer(guest_key=self.guest))

        self.assertEqual((found.comments, found.shadowed), (5, None))

    def test_a_signed_in_user_gets_own_counters(self):
        found = stats.stats_for(Viewer.of(self.user))

        self.assertEqual((found.comments, found.my_comments, found.my_bookmarks), (4, 1, 1))

    def test_a_moderator_sees_everything(self):
        found = stats.stats_for(Viewer(user_id=self.user.pk, is_moderator=True))

        self.assertEqual((found.comments, found.shadowed), (6, 2))

    def test_shared_counts_come_from_the_cache(self):
        stats.stats_for(Viewer.anonymous())

        with CaptureQueriesContext(connection) as queries:
            stats.stats_for(Viewer.anonymous())

        self.assertEqual(len(queries), 0)

    def test_a_new_comment_drops_the_cache(self):
        self.assertEqual(stats.stats_for(Viewer.anonymous()).comments, 4)
        captcha = FakeCaptcha()
        service = CommentService(CommentMarkup(), captcha.service, lambda pk: None, RecordingNotifier())

        with self.captureOnCommitCallbacks(execute=True):
            service.create(NewComment(user_name='Anonym', email='a@example.com', text='New',
                                      captcha_key=captcha.new_key(), captcha_answer='Ab3Cd'), Author())

        self.assertEqual(stats.stats_for(Viewer.anonymous()).comments, 5)

    def test_graphql(self):
        guest = self.client.post(reverse('graphql'), {'query': QUERY}, content_type='application/json').json()
        signed_in = self.client.post(reverse('graphql'), {'query': QUERY}, content_type='application/json',
                                     headers={'Authorization': f'Bearer {AccessToken.for_user(self.user)}'}).json()

        self.assertEqual(guest['data']['stats'],
                         {'comments': 4, 'ufo': 1, 'shadowed': None, 'myComments': None, 'myBookmarks': None})
        self.assertEqual(signed_in['data']['stats'],
                         {'comments': 4, 'ufo': 1, 'shadowed': None, 'myComments': 1, 'myBookmarks': 1})
