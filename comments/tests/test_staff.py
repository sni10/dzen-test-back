from importlib import import_module

from django.apps import apps
from django.test import TestCase
from django.urls import reverse

from accounts.models import User
from comments.live import comment_payload
from comments.markup import CommentMarkup
from comments.models import Comment
from comments.services import Author, CommentService, NewComment

from .factories import make_comment
from .test_create import FakeCaptcha, RecordingNotifier


class StaffCommentTests(TestCase):
    def setUp(self):
        captcha = FakeCaptcha()
        self.captcha = captcha
        self.service = CommentService(CommentMarkup(), captcha.service, lambda pk: None, RecordingNotifier())

    def post(self, user):
        return self.service.create(NewComment(user_name='x', email='x@example.com', text='Hello',
                                              captcha_key=self.captcha.new_key(), captcha_answer='Ab3Cd'),
                                   Author(user=user))

    def test_a_moderator_posts_as_the_administration(self):
        moderator = User.objects.create_user('Mod', 'mod@example.com', 'pw', role=User.Role.ADMIN)
        superuser = User.objects.create_user('Root', 'root@example.com', 'pw', is_superuser=True)
        regular = User.objects.create_user('Rum8', 'rum@example.com', 'pw')

        self.assertEqual([self.post(u).by_moderator for u in (moderator, superuser, regular)], [True, True, False])

    def test_a_later_role_change_does_not_rewrite_old_comments(self):
        moderator = User.objects.create_user('Mod', 'mod@example.com', 'pw', role=User.Role.ADMIN)
        comment = self.post(moderator)
        User.objects.filter(pk=moderator.pk).update(role=User.Role.USER)

        comment.refresh_from_db()
        self.assertTrue(comment.by_moderator)

    def test_exposed_in_graphql_rest_and_live_payloads(self):
        comment = make_comment(by_moderator=True)

        data = self.client.post(reverse('graphql'), {'query': '{ comments { items { byModerator } } }'},
                                content_type='application/json').json()

        self.assertEqual(data['data']['comments']['items'], [{'byModerator': True}])
        self.assertTrue(comment_payload(comment)['byModerator'])

    def test_the_migration_marks_existing_moderator_comments(self):
        moderator = User.objects.create_user('Mod', 'mod@example.com', 'pw', role=User.Role.ADMIN)
        old = make_comment(user=moderator)
        other = make_comment()

        import_module('comments.migrations.0002_by_moderator').mark_moderators_comments(apps, None)

        self.assertEqual(set(Comment.objects.filter(by_moderator=True)), {old})
        other.refresh_from_db()
        self.assertFalse(other.by_moderator)
