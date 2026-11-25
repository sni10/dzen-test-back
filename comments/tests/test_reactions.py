import uuid

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from comments.models import Bookmark, Comment, CommentVote
from comments.reactions import ReactionError, ReactionService

from .factories import make_comment
from .test_create import RecordingNotifier

PASSWORD = 'correct-horse-battery-9'


def make_user(name, **fields):
    return User.objects.create_user(name, f'{name.lower()}@example.com', PASSWORD, **fields)


class VoteServiceTests(TestCase):
    def setUp(self):
        self.notifier = RecordingNotifier()
        self.service = ReactionService(self.notifier)
        self.author = make_user('Author')
        self.voter = make_user('Voter')
        self.comment = make_comment(user=self.author)

    def vote(self, value, user=None):
        with self.captureOnCommitCallbacks(execute=True):
            return self.service.vote(user or self.voter, self.comment.pk, value)

    def score(self):
        return Comment.objects.get(pk=self.comment.pk).score

    def test_up_down_and_back(self):
        self.assertEqual((self.vote(1).score, self.score()), (1, 1))
        self.assertEqual(self.vote(-1).score, -1)  # changed its mind: -1 - (+1) = -2
        self.assertEqual(self.vote(None).score, 0)
        self.assertFalse(CommentVote.objects.exists())

    def test_the_same_vote_twice_counts_once(self):
        self.vote(1)
        result = self.vote(1)

        self.assertEqual((result.score, result.my_vote), (1, 1))
        self.assertEqual(CommentVote.objects.count(), 1)

    def test_many_voters(self):
        for n in range(3):
            self.vote(1, make_user(f'Up{n}'))
        self.vote(-1, make_user('Down'))

        self.assertEqual(self.score(), 2)

    def test_score_changes_are_broadcast_after_commit(self):
        self.vote(1)
        self.vote(1)  # nothing changed: no event

        self.assertEqual(self.notifier.scores, [self.comment.pk])

    def test_cannot_vote_for_own_comment(self):
        with self.assertRaises(ReactionError):
            self.service.vote(self.author, self.comment.pk, 1)

    def test_only_plus_or_minus_one(self):
        with self.assertRaises(ReactionError):
            self.service.vote(self.voter, self.comment.pk, 5)

    def test_invisible_or_missing_comment(self):
        hidden = make_comment(is_shadowed=True, guest_key=uuid.uuid4())
        for comment_id in (hidden.pk, 999999):
            with self.subTest(comment_id=comment_id), self.assertRaises(ReactionError):
                self.service.vote(self.voter, comment_id, 1)

    def test_shadowbanned_vote_is_kept_but_not_counted(self):
        shadow = make_user('Shadow', is_shadowbanned=True)

        result = self.vote(1, shadow)

        self.assertEqual((result.score, result.my_vote), (0, 1))
        self.assertTrue(CommentVote.objects.filter(user=shadow).exists())
        self.assertEqual(self.notifier.scores, [])

    def test_bookmarks(self):
        self.assertTrue(self.service.set_bookmark(self.voter, self.comment.pk, True))
        self.assertTrue(self.service.set_bookmark(self.voter, self.comment.pk, True))  # idempotent
        self.assertEqual(Bookmark.objects.count(), 1)
        self.assertFalse(self.service.set_bookmark(self.voter, self.comment.pk, False))
        self.assertFalse(Bookmark.objects.exists())


class ReactionsGraphQLTests(TestCase):
    def setUp(self):
        self.author = make_user('Author')
        self.voter = make_user('Voter')
        self.comment = make_comment(user=self.author)

    def gql(self, query, variables=None, user=None):
        headers = {'Authorization': f'Bearer {AccessToken.for_user(user)}'} if user else {}
        return self.client.post(reverse('graphql'), {'query': query, 'variables': variables or {}},
                                content_type='application/json', headers=headers).json()

    def test_vote_and_see_my_vote(self):
        voted = self.gql('mutation($id: ID!) { vote(commentId: $id, value: 1) { commentId score myVote } }',
                         {'id': self.comment.pk}, self.voter)
        mine = self.gql('{ comments { items { score myVote bookmarked } } }', user=self.voter)
        guest = self.gql('{ comments { items { score myVote bookmarked } } }')

        self.assertEqual(voted['data']['vote'], {'commentId': str(self.comment.pk), 'score': 1, 'myVote': 1})
        self.assertEqual(mine['data']['comments']['items'], [{'score': 1, 'myVote': 1, 'bookmarked': False}])
        self.assertEqual(guest['data']['comments']['items'], [{'score': 1, 'myVote': None, 'bookmarked': False}])

    def test_is_mine(self):
        query = '{ comments { items { isMine } } }'

        self.assertTrue(self.gql(query, user=self.author)['data']['comments']['items'][0]['isMine'])
        self.assertFalse(self.gql(query, user=self.voter)['data']['comments']['items'][0]['isMine'])
        self.assertFalse(self.gql(query)['data']['comments']['items'][0]['isMine'])

    def test_unvote(self):
        self.gql('mutation($id: ID!) { vote(commentId: $id, value: -1) { score } }', {'id': self.comment.pk},
                 self.voter)

        result = self.gql('mutation($id: ID!) { unvote(commentId: $id) { score myVote } }', {'id': self.comment.pk},
                          self.voter)

        self.assertEqual(result['data']['unvote'], {'score': 0, 'myVote': None})

    def test_errors(self):
        guest = self.gql('mutation($id: ID!) { vote(commentId: $id, value: 1) { score } }', {'id': self.comment.pk})
        own = self.gql('mutation($id: ID!) { vote(commentId: $id, value: 1) { score } }', {'id': self.comment.pk},
                       self.author)

        self.assertEqual(guest['errors'][0]['extensions']['code'], 'UNAUTHENTICATED')
        self.assertEqual(own['errors'][0]['message'], 'You cannot vote for your own comment')

    def test_bookmarks_in_the_cabinet(self):
        older = make_comment()
        for comment in (older, self.comment):
            self.gql('mutation($id: ID!) { bookmark(commentId: $id) }', {'id': comment.pk}, self.voter)

        page = self.gql('{ myBookmarks { totalCount items { id bookmarked } } }', user=self.voter)['data']

        self.assertEqual(page['myBookmarks']['totalCount'], 2)
        self.assertEqual([c['id'] for c in page['myBookmarks']['items']], [str(self.comment.pk), str(older.pk)])
        self.assertTrue(all(c['bookmarked'] for c in page['myBookmarks']['items']))
        self.gql('mutation($id: ID!) { unbookmark(commentId: $id) }', {'id': older.pk}, self.voter)
        self.assertEqual(self.gql('{ myBookmarks { totalCount } }', user=self.voter)['data']['myBookmarks'],
                         {'totalCount': 1})

    def test_my_vote_and_bookmarks_do_not_add_a_query_per_comment(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.gql('{ comments { items { myVote bookmarked replies { items { myVote bookmarked } } } } }',
                         user=self.voter)
            return len(queries)

        make_comment(parent=self.comment)  # every level present in the baseline
        few = count()
        for _ in range(8):
            make_comment(parent=make_comment())

        self.assertEqual(count(), few)
