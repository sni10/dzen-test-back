"""Full-text search over comments (Elasticsearch).

The index holds the plain text (HTML stripped) analysed for Russian and English, the author's name, and the
fields needed for the same visibility rules as the feed: shadowed comments are found only by their author and
moderators; the text of a comment hidden by a moderator is not indexed at all.
"""
import html
from dataclasses import dataclass
from typing import Protocol

from django.utils.html import strip_tags
from elasticsearch import Elasticsearch, NotFoundError
from elasticsearch.helpers import bulk

from .models import Comment
from .viewer import Viewer

PAGE_SIZE = 25
HIGHLIGHT_TAG = 'mark'

MAPPINGS = {
    'properties': {
        # one text, three ways: "комментарии" finds "комментарий", "replies" finds "reply"
        'text': {'type': 'text', 'fields': {'ru': {'type': 'text', 'analyzer': 'russian'},
                                            'en': {'type': 'text', 'analyzer': 'english'}}},
        'user_name': {'type': 'text', 'fields': {'keyword': {'type': 'keyword'}}},
        'is_shadowed': {'type': 'boolean'},
        'user_id': {'type': 'long'},
        'guest_key': {'type': 'keyword'},
        'created_at': {'type': 'date'},
    },
}


def document(comment: Comment) -> dict:
    return {
        'text': '' if comment.is_ufo else html.unescape(strip_tags(comment.text)),
        'user_name': comment.user_name,
        'is_shadowed': comment.is_shadowed,
        'user_id': comment.user_id,
        'guest_key': str(comment.guest_key) if comment.guest_key else None,
        'created_at': comment.created_at.isoformat(),
    }


def visibility_filter(viewer: Viewer) -> list[dict]:
    """The same rule as CommentQuerySet.visible_to, in the query language of the index."""
    if viewer.is_moderator:
        return []
    allowed = [{'term': {'is_shadowed': False}}]
    if viewer.user_id is not None:
        allowed.append({'term': {'user_id': viewer.user_id}})
    if viewer.guest_key is not None:
        allowed.append({'term': {'guest_key': str(viewer.guest_key)}})
    return [{'bool': {'should': allowed, 'minimum_should_match': 1}}]


@dataclass(frozen=True)
class SearchResult:
    ids: list[int]
    highlights: dict[int, str]  # comment id -> an HTML snippet: escaped text with <mark> around matches
    total: int


class SearchIndex(Protocol):
    def save(self, comments: list[Comment]) -> None: ...

    def remove(self, ids: list[int]) -> None: ...

    def search(self, query: str, viewer: Viewer, page: int) -> SearchResult: ...


class ElasticsearchIndex:
    def __init__(self, client: Elasticsearch, index: str):
        self.client = client
        self.index = index

    def ensure(self) -> None:
        if not self.client.indices.exists(index=self.index):
            self.client.indices.create(index=self.index, mappings=MAPPINGS)

    def recreate(self) -> None:
        self.client.indices.delete(index=self.index, ignore_unavailable=True)
        self.ensure()

    def save(self, comments: list[Comment], wait: bool = True) -> None:
        """`wait`: searchable when this returns (a new comment); a bulk reindex skips that per batch."""
        self.ensure()
        bulk(self.client, ({'_index': self.index, '_id': c.pk, '_source': document(c)} for c in comments),
             refresh='wait_for' if wait else False)

    def remove(self, ids: list[int]) -> None:
        for comment_id in ids:
            try:
                self.client.delete(index=self.index, id=comment_id, refresh='wait_for')
            except NotFoundError:
                pass

    def search(self, query: str, viewer: Viewer, page: int) -> SearchResult:
        self.ensure()
        response = self.client.search(
            index=self.index,
            query={'bool': {
                'must': {'multi_match': {'query': query, 'fields': ['text', 'text.ru', 'text.en', 'user_name^2'],
                                         'operator': 'and'}},
                'filter': visibility_filter(viewer),
            }},
            highlight={
                'encoder': 'html',  # escapes the text around the tags: the snippet is safe to render
                'pre_tags': [f'<{HIGHLIGHT_TAG}>'],
                'post_tags': [f'</{HIGHLIGHT_TAG}>'],
                'fields': {'text': {}, 'text.ru': {}, 'text.en': {}},
                'require_field_match': False,
                'fragment_size': 160,
                'number_of_fragments': 1,
            },
            sort=['_score', {'created_at': 'desc'}],
            from_=(page - 1) * PAGE_SIZE,
            size=PAGE_SIZE,
            track_total_hits=True,
        )
        hits = response['hits']['hits']
        highlights = {}
        for hit in hits:
            fragments = next((value for value in hit.get('highlight', {}).values() if value), None)
            if fragments:
                highlights[int(hit['_id'])] = fragments[0]
        return SearchResult([int(hit['_id']) for hit in hits], highlights, response['hits']['total']['value'])
