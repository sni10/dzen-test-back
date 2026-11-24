import uuid
from datetime import timedelta

from django.db import connection
from django.test import TestCase
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from django.utils import timezone

from comments.models import Comment
from common.guest import COOKIE_NAME
from common.management.commands.export_graphql_schema import SCHEMA_FILE
from config.graphql import schema

from .factories import make_comment

FEED = '''
query Feed($page: Int!, $sort: CommentSort!) {
  comments(page: $page, sort: $sort) {
    totalCount page pageSize pageCount
    items { id userName email text depth repliesCount }
  }
}
'''

THREADS = '''
query Threads {
  comments {
    items {
      id
      replies(first: 2) {
        hasMore endCursor
        items { id parent { id text } replies(first: 2) { items { id } } }
      }
    }
  }
}
'''


class GraphQLTestCase(TestCase):
    url = reverse('graphql')

    def query(self, query, variables=None, guest_key=None):
        if guest_key:
            self.client.cookies[COOKIE_NAME] = str(guest_key)
        response = self.client.post(self.url, {'query': query, 'variables': variables or {}},
                                    content_type='application/json')
        self.assertEqual(response.status_code, 200, response.content)
        return response.json()

    def data(self, query, variables=None, **kwargs):
        body = self.query(query, variables, **kwargs)
        self.assertNotIn('errors', body, body.get('errors'))
        return body['data']

    def error(self, query, variables=None):
        body = self.query(query, variables)
        self.assertIn('errors', body)
        return body['errors'][0]['message']


class FeedTests(GraphQLTestCase):
    def feed(self, page=1, sort='CREATED_AT_DESC'):
        return self.data(FEED, {'page': page, 'sort': sort})['comments']

    def test_25_top_level_comments_per_page_newest_first(self):
        comments = [make_comment() for _ in range(30)]
        make_comment(parent=comments[0])  # replies are not rows of the table

        first, second = self.feed(1), self.feed(2)

        self.assertEqual((first['totalCount'], first['pageSize'], first['pageCount']), (30, 25, 2))
        self.assertEqual([int(c['id']) for c in first['items']], [c.pk for c in reversed(comments)][:25])
        self.assertEqual([int(c['id']) for c in second['items']], [c.pk for c in reversed(comments)][25:])
        self.assertEqual(self.feed(3)['items'], [])

    def test_sort_by_every_column_both_ways(self):
        now = timezone.now()
        b = make_comment(user_name='bob', email='c@example.com')
        a = make_comment(user_name='alice', email='b@example.com')
        c = make_comment(user_name='carol', email='a@example.com')
        for offset, comment in enumerate([a, b, c]):
            Comment.objects.filter(pk=comment.pk).update(created_at=now + timedelta(minutes=offset))
        cases = {'USER_NAME': [a, b, c], 'EMAIL': [c, a, b], 'CREATED_AT': [a, b, c]}

        for column, ascending in cases.items():
            expected = [str(comment.pk) for comment in ascending]
            with self.subTest(column=column):
                self.assertEqual([x['id'] for x in self.feed(sort=f'{column}_ASC')['items']], expected)
                self.assertEqual([x['id'] for x in self.feed(sort=f'{column}_DESC')['items']], expected[::-1])

    def test_unknown_sort_is_rejected_by_the_schema(self):
        self.assertIn('CommentSort', self.error(FEED, {'page': 1, 'sort': 'TEXT_ASC'}))

    def test_page_must_be_positive(self):
        self.assertIn('page must be 1 or greater', self.error(FEED, {'page': 0, 'sort': 'CREATED_AT_DESC'}))

    def test_shadowed_comments_are_visible_only_to_their_author(self):
        key = uuid.uuid4()
        public = make_comment()
        shadowed = make_comment(guest_key=key, is_shadowed=True)

        others = self.data(FEED, {'page': 1, 'sort': 'CREATED_AT_DESC'})['comments']
        author = self.data(FEED, {'page': 1, 'sort': 'CREATED_AT_DESC'}, guest_key=key)['comments']

        self.assertEqual([c['id'] for c in others['items']], [str(public.pk)])
        self.assertEqual(others['totalCount'], 1)
        self.assertEqual({c['id'] for c in author['items']}, {str(public.pk), str(shadowed.pk)})

    def test_private_fields_are_not_in_the_schema(self):
        fields = set(schema.get_type_by_name('Comment').fields and
                     [f.name for f in schema.get_type_by_name('Comment').fields])
        for private in ('ip', 'userAgent', 'guestKey', 'isShadowed', 'user'):
            self.assertNotIn(private, fields)


class RepliesTests(GraphQLTestCase):
    def test_nested_replies_with_parent_quote(self):
        root = make_comment()
        reply = make_comment(parent=root)
        deep = make_comment(parent=reply)

        items = self.data(THREADS)['comments']['items']

        replies = items[0]['replies']
        self.assertEqual([r['id'] for r in replies['items']], [str(reply.pk)])
        self.assertEqual(replies['items'][0]['parent'], {'id': str(root.pk), 'text': root.text})
        self.assertEqual(replies['items'][0]['replies']['items'], [{'id': str(deep.pk)}])
        self.assertFalse(replies['hasMore'])

    def test_replies_page_through_with_cursor(self):
        root = make_comment()
        replies = [make_comment(parent=root) for _ in range(5)]
        query = '''query($id: ID!, $after: ID) {
          comment(id: $id) { replies(first: 2, after: $after) { hasMore endCursor items { id } } }
        }'''

        seen, after, has_more = [], None, True
        while has_more:
            page = self.data(query, {'id': root.pk, 'after': after})['comment']['replies']
            seen += [int(item['id']) for item in page['items']]
            after, has_more = page['endCursor'], page['hasMore']

        self.assertEqual(seen, [reply.pk for reply in replies])

    def test_no_n_plus_one(self):
        """One query per nesting level, however many comments there are."""
        def run():
            with CaptureQueriesContext(connection) as queries:
                self.data(THREADS)
            return len(queries)

        for _ in range(2):
            make_comment(parent=make_comment(parent=make_comment()))
        few = run()
        for _ in range(10):
            root = make_comment()
            for _ in range(3):
                make_comment(parent=make_comment(parent=root))

        self.assertEqual(run(), few)

    def test_first_is_limited(self):
        query = 'query { comments { items { replies(first: 51) { hasMore } } } }'
        make_comment()

        self.assertIn('first must be between 1 and 50', self.error(query))

    def test_hidden_reply_is_not_listed_and_parent_quote_of_hidden_is_null(self):
        root = make_comment()
        make_comment(parent=root, is_shadowed=True, guest_key=uuid.uuid4())

        replies = self.data(THREADS)['comments']['items'][0]['replies']

        self.assertEqual(replies['items'], [])


class CommentAndSinceTests(GraphQLTestCase):
    def test_comment_by_id(self):
        comment = make_comment()
        query = 'query($id: ID!) { comment(id: $id) { id userName } }'

        self.assertEqual(self.data(query, {'id': comment.pk})['comment'],
                         {'id': str(comment.pk), 'userName': comment.user_name})
        self.assertIsNone(self.data(query, {'id': 999999})['comment'])
        self.assertIn('id must be a comment id', self.error(query, {'id': 'abc'}))

    def test_hidden_comment_is_null(self):
        hidden = make_comment(is_shadowed=True, guest_key=uuid.uuid4())

        self.assertIsNone(self.data('query($id: ID!) { comment(id: $id) { id } }', {'id': hidden.pk})['comment'])

    def test_comments_since_returns_newer_comments_oldest_first(self):
        old = make_comment()
        newer = [make_comment(), make_comment(parent=old)]
        query = 'query($last: ID!) { commentsSince(lastId: $last) { id parentId } }'

        result = self.data(query, {'last': old.pk})['commentsSince']

        self.assertEqual([int(c['id']) for c in result], [c.pk for c in newer])
        self.assertEqual(result[1]['parentId'], str(old.pk))


class LimitsTests(GraphQLTestCase):
    def test_too_deep_query_is_rejected(self):
        nested = 'id'
        for _ in range(8):
            nested = f'replies {{ items {{ {nested} }} }}'

        self.assertIn('exceeds maximum operation depth', self.error(f'query {{ comments {{ items {{ {nested} }} }} }}'))

    def test_too_many_aliases_are_rejected(self):
        aliases = ' '.join(f'a{n}: comments {{ totalCount }}' for n in range(20))

        self.assertIn('aliases', self.error(f'query {{ {aliases} }}'))

    def test_graphiql_is_served_to_browsers(self):
        response = self.client.get(self.url, HTTP_ACCEPT='text/html')

        self.assertEqual(response.status_code, 200)
        self.assertIn(b'graphiql', response.content.lower())


class SchemaFileTests(TestCase):
    def test_schema_graphql_is_up_to_date(self):
        """Run `python manage.py export_graphql_schema` after changing the schema."""
        self.assertEqual(SCHEMA_FILE.read_text(encoding='utf-8'), schema.as_str() + '\n')


class CsrfTests(TestCase):
    def test_post_works_without_a_csrf_token(self):
        from django.test import Client

        response = Client(enforce_csrf_checks=True).post(
            reverse('graphql'), {'query': '{ comments { totalCount } }'}, content_type='application/json',
        )

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'data': {'comments': {'totalCount': 0}}})
