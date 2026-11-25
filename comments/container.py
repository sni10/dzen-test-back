from functools import cache

from django.conf import settings
from elasticsearch import Elasticsearch

from captcha.container import captcha_service

from .live import ChannelsNotifier
from .markup import CommentMarkup
from .reactions import ReactionService
from .services import CommentService
from .search import ElasticsearchIndex
from .tasks import index_comments, process_attachment


@cache
def comment_service() -> CommentService:
    return CommentService(
        markup=CommentMarkup(),
        captcha=captcha_service(),
        process_attachment=process_attachment.delay,
        notifier=notifier(),
        index_comments=index_comments.delay,
    )


@cache
def notifier() -> ChannelsNotifier:
    return ChannelsNotifier()


@cache
def reaction_service() -> ReactionService:
    return ReactionService(notifier=notifier())


@cache
def search_index() -> ElasticsearchIndex:
    client = Elasticsearch(settings.ELASTICSEARCH_URL, request_timeout=5, retry_on_timeout=True, max_retries=2)
    return ElasticsearchIndex(client, settings.ELASTICSEARCH_INDEX)
