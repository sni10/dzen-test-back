import uuid

from django.core.cache import cache
from django.test import TestCase
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from comments import stats
from comments.live import comment_payload
from comments.markup import CommentMarkup
from comments.models import Comment, CommentVote
from comments.reactions import ReactionService
from comments.services import Author, CommentService, NewComment
from comments.tests.factories import make_comment
from comments.tests.test_create import FakeCaptcha, RecordingNotifier
from comments.viewer import Viewer
from moderation.models import ModerationAction, ShadowBan
from moderation.services import ModerationError, ModerationService

PASSWORD = 'pw-long-enough-1'


def make_user(name, **fields):
    return User.objects.create_user(name, f'{name.lower()}@example.com', PASSWORD, **fields)


class ServiceTestCase(TestCase):
    def setUp(self):
        cache.clear()
        self.notifier = RecordingNotifier()
        self.service = ModerationService(self.notifier)
        self.moderator = make_user('Mod', role=User.Role.ADMIN)

    def run_committed(self, fn, *args, **kwargs):
        with self.captureOnCommitCallbacks(execute=True):
            return fn(*args, **kwargs)


class UfoTests(ServiceTestCase):
    def test_hide_and_restore(self):
        comment = make_comment(text='Rude words')

        self.run_committed(self.service.ufo, self.moderator, comment.pk, 'spam')

        comment.refresh_from_db()
        self.assertTrue(comment.is_ufo)
        self.assertEqual(comment.text, 'Rude words')  # kept: "restore" brings it back
        action = ModerationAction.objects.get(kind='ufo')
        self.assertEqual((action.original_text, action.reason, action.moderator), ('Rude words', 'spam',
                                                                                   self.moderator))
        self.assertEqual(self.notifier.changed, [comment])

        self.run_committed(self.service.restore, self.moderator, comment.pk)
        comment.refresh_from_db()
        self.assertFalse(comment.is_ufo)

    def test_the_hidden_text_never_leaves_the_server(self):
        parent = make_comment(text='Secret', is_ufo=True)
        reply = make_comment(parent=parent)

        self.assertEqual(comment_payload(parent)['text'], '')
        self.assertEqual(comment_payload(reply)['parent']['text'], '')

    def test_twice_is_an_error(self):
        comment = make_comment(is_ufo=True)
        with self.assertRaises(ModerationError):
            self.service.ufo(self.moderator, comment.pk)
        with self.assertRaises(ModerationError):
            self.service.restore(self.moderator, make_comment().pk)

    def test_ufo_count_in_stats(self):
        stats.stats_for(Viewer.anonymous())  # cached
        self.run_committed(self.service.ufo, self.moderator, make_comment().pk)

        self.assertEqual(stats.stats_for(Viewer.anonymous()).ufo, 1)


class ShadowBanTests(ServiceTestCase):
    def test_ban_a_user_hides_past_comments_and_recounts(self):
        author = make_user('Spammer')
        voter = make_user('Voter')
        root = make_comment()
        reply = make_comment(parent=root, user=author)
        Comment.objects.filter(pk=root.pk).update(replies_count=1)
        target = make_comment()
        ReactionService(RecordingNotifier()).vote(author, target.pk, 1)
        ReactionService(RecordingNotifier()).vote(voter, target.pk, 1)

        ban = self.run_committed(self.service.shadowban, self.moderator, reply.pk, True, 'spam')

        author.refresh_from_db()
        reply.refresh_from_db()
        root.refresh_from_db()
        target.refresh_from_db()
        self.assertTrue(author.is_shadowbanned)
        self.assertTrue(reply.is_shadowed)
        self.assertEqual(root.replies_count, 0)  # the hidden reply is no longer counted
        self.assertEqual(target.score, 1)  # only the voter's vote counts now
        self.assertEqual((ban.user, ban.user_name, ban.reason), (author, 'Spammer', 'spam'))
        self.assertEqual(Comment.objects.visible_to(Viewer.anonymous()).filter(pk=reply.pk).count(), 0)
        self.assertEqual(Comment.objects.visible_to(Viewer.of(author)).filter(pk=reply.pk).count(), 1)

    def test_without_hide_past_old_comments_stay(self):
        author = make_user('Spammer')
        old = make_comment(user=author)

        ban = self.service.shadowban(self.moderator, old.pk, hide_past=False)

        old.refresh_from_db()
        self.assertFalse(old.is_shadowed)
        self.assertEqual(ban.changed_comment_ids, [])

    def test_ban_and_unban_report_every_changed_comment(self):
        """The page marks all of the author's comments, not only the one the moderator clicked"""
        author = make_user('Spammer')
        first, second = make_comment(user=author), make_comment(user=author)
        make_comment()  # someone else's

        ban = self.service.shadowban(self.moderator, first.pk)
        self.assertCountEqual(ban.changed_comment_ids, [first.pk, second.pk])

        lifted = self.service.unban(self.moderator, ban.pk)
        self.assertCountEqual(lifted.changed_comment_ids, [first.pk, second.pk])

    def test_a_banned_guest_is_recognised_by_cookie_or_email(self):
        key = uuid.uuid4()
        old = make_comment(guest_key=key, email='troll@example.com')
        self.service.shadowban(self.moderator, old.pk)
        captcha = FakeCaptcha()
        comments = CommentService(CommentMarkup(), captcha.service, lambda pk: None, RecordingNotifier())

        def post(guest_key, email):
            return comments.create(NewComment(user_name='Troll', email=email, text='again',
                                              captcha_key=captcha.new_key(), captcha_answer='Ab3Cd'),
                                   Author(guest_key=guest_key))

        self.assertTrue(post(key, 'new@example.com').is_shadowed)  # same cookie
        self.assertTrue(post(uuid.uuid4(), 'TROLL@example.com').is_shadowed)  # cleared cookie, same e-mail
        self.assertFalse(post(uuid.uuid4(), 'someone@example.com').is_shadowed)

    def test_a_guest_without_a_cookie_is_matched_by_email_only(self):
        """Old or imported comments have no guest_key: banning one must not hit every such comment"""
        target = make_comment(email='troll@example.com')
        same_email = make_comment(email='TROLL@example.com')
        stranger = make_comment(email='someone@example.com')

        self.service.shadowban(self.moderator, target.pk)

        shadowed = set(Comment.objects.filter(is_shadowed=True).values_list('pk', flat=True))
        self.assertEqual(shadowed, {target.pk, same_email.pk})
        self.assertFalse(ShadowBan.objects.matching_guest(None, 'someone@example.com').exists())
        stranger.refresh_from_db()
        self.assertFalse(stranger.is_shadowed)

    def test_unban_brings_everything_back(self):
        author = make_user('Spammer')
        comment = make_comment(user=author)
        target = make_comment()
        CommentVote.objects.create(comment=target, user=author, value=1)
        ban = self.service.shadowban(self.moderator, comment.pk)

        self.run_committed(self.service.unban, self.moderator, ban.pk)

        author.refresh_from_db()
        comment.refresh_from_db()
        target.refresh_from_db()
        ban.refresh_from_db()
        self.assertFalse(author.is_shadowbanned)
        self.assertFalse(comment.is_shadowed)
        self.assertEqual(target.score, 1)
        self.assertIsNotNone(ban.lifted_at)
        with self.assertRaises(ModerationError):
            self.service.unban(self.moderator, ban.pk)  # not active anymore

    def test_rules(self):
        other_moderator = make_user('Mod2', role=User.Role.ADMIN)
        author = make_user('Spammer')
        comment = make_comment(user=author)
        self.service.shadowban(self.moderator, comment.pk)

        with self.assertRaises(ModerationError):
            self.service.shadowban(self.moderator, comment.pk)  # already banned
        with self.assertRaises(ModerationError):
            self.service.shadowban(self.moderator, make_comment(user=other_moderator).pk)
        with self.assertRaises(ModerationError):
            self.service.shadowban(self.moderator, 999999)
        self.assertEqual(ShadowBan.objects.count(), 1)


class GraphQLTests(TestCase):
    def setUp(self):
        cache.clear()
        self.moderator = make_user('Mod', role=User.Role.ADMIN)
        self.user = make_user('Rum8')
        self.comment = make_comment(text='Original text')

    def gql(self, query, variables=None, user=None):
        headers = {'Authorization': f'Bearer {AccessToken.for_user(user)}'} if user else {}
        return self.client.post(reverse('graphql'), {'query': query, 'variables': variables or {}},
                                content_type='application/json', headers=headers).json()

    def test_moderators_only(self):
        mutation = 'mutation($id: ID!) { ufoComment(commentId: $id) { id } }'

        self.assertEqual(self.gql(mutation, {'id': self.comment.pk})['errors'][0]['extensions']['code'],
                         'UNAUTHENTICATED')
        self.assertEqual(self.gql(mutation, {'id': self.comment.pk}, self.user)['errors'][0]['extensions']['code'],
                         'FORBIDDEN')
        self.assertEqual(self.gql('{ shadowBans { id } }', user=self.user)['errors'][0]['extensions']['code'],
                         'FORBIDDEN')

    def test_ufo_hides_the_text_from_everyone_but_moderators(self):
        hidden = self.gql('mutation($id: ID!) { ufoComment(commentId: $id, reason: "rude") { isUfo text } }',
                          {'id': self.comment.pk}, self.moderator)
        query = '{ comments { items { text isUfo originalText isShadowed } } }'

        self.assertEqual(hidden['data']['ufoComment'], {'isUfo': True, 'text': ''})
        self.assertEqual(self.gql(query)['data']['comments']['items'],
                         [{'text': '', 'isUfo': True, 'originalText': None, 'isShadowed': None}])
        self.assertEqual(self.gql(query, user=self.moderator)['data']['comments']['items'],
                         [{'text': '', 'isUfo': True, 'originalText': 'Original text', 'isShadowed': False}])

    def test_ban_list_and_unban(self):
        authored = make_comment(user=self.user)
        ban = self.gql('mutation($id: ID!) { shadowban(commentId: $id, reason: "spam") { id userName isGuest '
                       'commentsCount commentIds } }', {'id': authored.pk}, self.moderator)['data']['shadowban']

        self.assertEqual({k: ban[k] for k in ('userName', 'isGuest', 'commentsCount', 'commentIds')},
                         {'userName': 'Rum8', 'isGuest': False, 'commentsCount': 1, 'commentIds': [str(authored.pk)]})
        self.assertEqual(self.gql('{ shadowBans { id commentIds } }', user=self.moderator)['data']['shadowBans'],
                         [{'id': ban['id'], 'commentIds': []}])
        lifted = self.gql('mutation($id: ID!) { unban(banId: $id) { liftedAt commentIds } }', {'id': ban['id']},
                          self.moderator)['data']['unban']
        self.assertIsNotNone(lifted['liftedAt'])
        self.assertEqual(lifted['commentIds'], [str(authored.pk)])
        self.assertEqual(self.gql('{ shadowBans { id } }', user=self.moderator)['data']['shadowBans'], [])

    def test_errors_come_back_readable(self):
        result = self.gql('mutation($id: ID!) { restoreComment(commentId: $id) { id } }', {'id': self.comment.pk},
                          self.moderator)

        self.assertEqual(result['errors'][0]['message'], 'The comment is not hidden')
