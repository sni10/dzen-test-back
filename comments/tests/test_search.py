import uuid
from unittest import mock

from django.test import TestCase, override_settings
from django.urls import reverse
from rest_framework_simplejwt.tokens import AccessToken

from accounts.models import User
from comments.container import search_index
from comments.markup import CommentMarkup
from comments.models import Comment
from comments.search import document, visibility_filter
from comments.services import Author, CommentService, NewComment
from comments.tasks import index_comments
from comments.viewer import Viewer
from moderation.services import ModerationService

from .factories import make_comment
from .test_create import FakeCaptcha, RecordingNotifier


class DocumentTests(TestCase):
    def test_plain_text_without_tags_and_entities(self):
        comment = make_comment(text='Say <strong>hi</strong> &amp; 1 &lt; 2 <a href="https://e.com">link</a>')

        self.assertEqual(document(comment)['text'], 'Say hi & 1 < 2 link')

    def test_a_ufo_comment_is_not_searchable(self):
        self.assertEqual(document(make_comment(text='secret', is_ufo=True))['text'], '')

    def test_visibility_filter(self):
        key = uuid.uuid4()
        self.assertEqual(visibility_filter(Viewer(is_moderator=True)), [])
        [rule] = visibility_filter(Viewer(user_id=7, guest_key=key))
        self.assertEqual(rule['bool']['should'], [
            {'term': {'is_shadowed': False}}, {'term': {'user_id': 7}}, {'term': {'guest_key': str(key)}},
        ])


class ElasticsearchTestCase(TestCase):
    """Against the real cluster (compose locally, a service in CI), each class in its own index."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.isolated = override_settings(ELASTICSEARCH_INDEX=f'test-comments-{uuid.uuid4().hex}')
        cls.isolated.enable()
        search_index.cache_clear()

    @classmethod
    def tearDownClass(cls):
        search_index().client.indices.delete(index=search_index().index, ignore_unavailable=True)
        cls.isolated.disable()
        search_index.cache_clear()
        super().tearDownClass()

    def setUp(self):
        search_index().recreate()

    def index(self, *comments):
        search_index().save(list(comments))

    def ids(self, query, viewer=None):
        return search_index().search(query, viewer or Viewer.anonymous(), 1).ids


class SearchIndexTests(ElasticsearchTestCase):
    def test_russian_and_english_word_forms(self):
        ru = make_comment(text='Интересные комментарии к статье')
        en = make_comment(text='Two replies were posted')
        self.index(ru, en)

        self.assertEqual(self.ids('комментарий'), [ru.pk])
        self.assertEqual(self.ids('reply'), [en.pk])
        self.assertEqual(self.ids('nothing like this'), [])

    def test_by_author_name(self):
        comment = make_comment(user_name='Rum8', text='Hello')
        self.index(comment)

        self.assertEqual(self.ids('rum8'), [comment.pk])

    def test_highlight_is_escaped_html_with_marks(self):
        comment = make_comment(text='Proof: 1 &lt; 2 &amp; <i>search</i> works')
        self.index(comment)

        found = search_index().search('search', Viewer.anonymous(), 1)

        self.assertEqual(found.highlights[comment.pk], 'Proof: 1 &lt; 2 &amp; <mark>search</mark> works')

    def test_shadowed_comments_are_found_only_by_the_author_and_moderators(self):
        key = uuid.uuid4()
        hidden = make_comment(text='hidden spam', is_shadowed=True, guest_key=key)
        self.index(hidden)

        self.assertEqual(self.ids('spam'), [])
        self.assertEqual(self.ids('spam', Viewer(guest_key=uuid.uuid4())), [])
        self.assertEqual(self.ids('spam', Viewer(guest_key=key)), [hidden.pk])
        self.assertEqual(self.ids('spam', Viewer(is_moderator=True)), [hidden.pk])

    def test_the_task_saves_and_removes(self):
        kept = make_comment(text='keep this one')
        gone = make_comment(text='remove this one')
        self.index(kept, gone)
        gone_id = gone.pk
        gone.delete()

        index_comments([kept.pk, gone_id])

        self.assertEqual(self.ids('one'), [kept.pk])


class SearchHooksTests(ElasticsearchTestCase):
    def test_a_new_comment_is_indexed_after_commit(self):
        captcha = FakeCaptcha()
        indexed = []
        service = CommentService(CommentMarkup(), captcha.service, lambda pk: None, RecordingNotifier(),
                                 indexed.extend)

        with self.captureOnCommitCallbacks(execute=True):
            comment = service.create(NewComment(user_name='Anonym', email='a@example.com', text='Fresh',
                                                captcha_key=captcha.new_key(), captcha_answer='Ab3Cd'), Author())

        self.assertEqual(indexed, [comment.pk])

    def test_moderation_reindexes_what_it_changes(self):
        moderator = User.objects.create_user('Mod', 'mod@example.com', 'pw', role=User.Role.ADMIN)
        author = User.objects.create_user('Spam', 'spam@example.com', 'pw')
        first, second = make_comment(user=author, text='buy now'), make_comment(user=author, text='buy more')
        indexed = []
        service = ModerationService(RecordingNotifier(), indexed.extend)

        with self.captureOnCommitCallbacks(execute=True):
            service.ufo(moderator, first.pk)
            service.shadowban(moderator, first.pk)

        self.assertEqual(sorted(indexed), sorted([first.pk, first.pk, second.pk]))
        index_comments(indexed)
        self.assertEqual(self.ids('buy'), [])  # the UFO text is gone, the banned author's comments hidden


class SearchGraphQLTests(ElasticsearchTestCase):
    query = 'query($q: String!) { search(query: $q) { totalCount items { highlight comment { id text } } } }'

    def search(self, q, user=None):
        headers = {'Authorization': f'Bearer {AccessToken.for_user(user)}'} if user else {}
        return self.client.post(reverse('graphql'), {'query': self.query, 'variables': {'q': q}},
                                content_type='application/json', headers=headers).json()

    def test_results_with_highlights(self):
        comment = make_comment(text='GraphQL search works')
        self.index(comment)

        result = self.search('search')['data']['search']

        self.assertEqual(result['totalCount'], 1)
        self.assertEqual(result['items'][0]['comment']['id'], str(comment.pk))
        self.assertEqual(result['items'][0]['highlight'], 'GraphQL <mark>search</mark> works')

    def test_the_database_has_the_last_word_on_visibility(self):
        comment = make_comment(text='stale index entry')
        self.index(comment)
        Comment.objects.filter(pk=comment.pk).update(is_shadowed=True)  # not re-indexed yet

        self.assertEqual(self.search('stale')['data']['search']['items'], [])

    def test_bad_queries(self):
        self.assertEqual(self.search('   ')['errors'][0]['message'], 'Type something to search for')
        self.assertIn('At most', self.search('x' * 201)['errors'][0]['message'])

    def test_unavailable_search_is_reported(self):
        with mock.patch('comments.container.search_index', side_effect=ConnectionError):
            result = self.search('anything')

        self.assertEqual(result['errors'][0]['extensions']['code'], 'SEARCH_UNAVAILABLE')
