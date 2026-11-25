"""Load test: what the SPA does, with the same GraphQL queries.

    uv run --group loadtest locust -f loadtest/locustfile.py --host http://localhost:8080

Posting needs the CAPTCHA answer: like a real client cannot, the test reads it from the local Redis
(REDIS_URL, default the compose one on 127.0.0.1:6380). No bypass in the application.
"""
import os
import random

import redis
from locust import HttpUser, between, events, task

REPLIES_PAGE = 10
SORTS = ['CREATED_AT_DESC', 'CREATED_AT_ASC', 'USER_NAME_ASC', 'USER_NAME_DESC', 'EMAIL_ASC', 'EMAIL_DESC']
WORDS = ['comment', 'reply', 'release', 'search', 'комментарий', 'ответ', 'релиз', 'поиск']
USER_AGENT = 'seed (locust)'  # `manage.py seed --clear` removes the posts of the load test too

FIELDS = """
  id userName email homePage text isUfo byModerator score repliesCount depth createdAt parentId rootId
  myVote bookmarked isMine originalText isShadowed
  attachments { id kind url originalName size width height status }
"""
REPLY_FIELDS = f'{FIELDS} parent {{ id userName text }}'
FEED = f"""
query Feed($page: Int!, $sort: CommentSort!, $first: Int!) {{
  comments(page: $page, sort: $sort) {{
    totalCount page pageSize pageCount
    items {{
      {FIELDS}
      replies(first: $first) {{
        hasMore endCursor
        items {{ {REPLY_FIELDS} replies(first: $first) {{ hasMore endCursor items {{ {REPLY_FIELDS} }} }} }}
      }}
    }}
  }}
}}"""
THREAD = f"""
query Thread($id: ID!, $first: Int!) {{
  comment(id: $id) {{
    {REPLY_FIELDS}
    replies(first: $first) {{
      hasMore endCursor
      items {{ {REPLY_FIELDS} replies(first: $first) {{ hasMore endCursor items {{ {REPLY_FIELDS} }} }} }}
    }}
  }}
}}"""
SEARCH = 'query($q: String!) { search(query: $q) { totalCount items { highlight comment { id } } } }'
STATS = 'query { stats { comments ufo shadowed myComments myBookmarks } }'

captchas = redis.Redis.from_url(os.environ.get('REDIS_URL', 'redis://127.0.0.1:6380/0'))
page_count = 1  # learnt from the first feed answer


@events.test_start.add_listener
def check_redis(**kwargs):
    captchas.ping()


class Visitor(HttpUser):
    """Mostly reads: the feed (first pages most), threads, search; sometimes posts."""

    wait_time = between(1, 4)

    def on_start(self):
        self.client.headers['User-Agent'] = USER_AGENT
        # Comments this visitor has seen: per visitor, as visibility is (a shadow-banned author sees own posts)
        self.seen_ids: list[str] = []

    def gql(self, name, query, variables=None):
        with self.client.post('/graphql', json={'query': query, 'variables': variables or {}}, name=name,
                              catch_response=True) as response:
            body = response.json() if response.ok else {}
            if body.get('errors'):
                response.failure(body['errors'][0]['message'])
            return body.get('data')

    @task(10)
    def feed_first_page(self):
        self.read_feed(1, 'CREATED_AT_DESC', 'feed: first page')

    @task(4)
    def feed_sorted(self):
        page = min(page_count, int(random.paretovariate(1.2)))  # near pages much more often than deep ones
        self.read_feed(page, random.choice(SORTS), 'feed: other sort / page')

    @task(1)
    def feed_deep_page(self):
        self.read_feed(random.randint(1, page_count), random.choice(SORTS), 'feed: random deep page')

    def read_feed(self, page, sort, name):
        global page_count
        data = self.gql(name, FEED, {'page': page, 'sort': sort, 'first': REPLIES_PAGE})
        if data:
            page_count = data['comments']['pageCount']
            self.seen_ids.extend(item['id'] for item in data['comments']['items'][:5])
            del self.seen_ids[:-100]

    @task(5)
    def thread(self):
        if self.seen_ids:
            self.gql('thread', THREAD, {'id': random.choice(self.seen_ids), 'first': REPLIES_PAGE})

    @task(3)
    def stats(self):
        self.gql('stats', STATS)

    @task(2)
    def search(self):
        self.gql('search', SEARCH, {'q': random.choice(WORDS)})

    @task(1)
    def post(self):
        key = self.client.get('/api/captcha/', name='captcha').json()['key']
        answer = captchas.get(f'captcha:{key}')
        reply_to = random.choice(self.seen_ids) if self.seen_ids and random.random() < 0.6 else None
        with self.client.post('/api/comments/', name='post comment' + (' (reply)' if reply_to else ''), json={
            'user_name': 'Locust', 'email': 'locust@example.com', 'parent': reply_to,
            'text': f'Load test <strong>{random.choice(WORDS)}</strong> {random.random():.6f}',
            'captcha_key': key, 'captcha_answer': answer.decode() if answer else '',
        }, catch_response=True) as response:
            if response.status_code == 400:
                response.failure(f'400 {response.text[:200]}')  # the reason, not just the code
