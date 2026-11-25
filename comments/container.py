from functools import cache

from captcha.container import captcha_service

from .live import ChannelsNotifier
from .markup import CommentMarkup
from .reactions import ReactionService
from .services import CommentService
from .tasks import process_attachment


@cache
def comment_service() -> CommentService:
    return CommentService(
        markup=CommentMarkup(),
        captcha=captcha_service(),
        process_attachment=process_attachment.delay,
        notifier=notifier(),
    )


@cache
def notifier() -> ChannelsNotifier:
    return ChannelsNotifier()


@cache
def reaction_service() -> ReactionService:
    return ReactionService(notifier=notifier())
