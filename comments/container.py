from functools import cache

from captcha.container import captcha_service

from .markup import CommentMarkup
from .services import CommentService


@cache
def comment_service() -> CommentService:
    return CommentService(markup=CommentMarkup(), captcha=captcha_service())
