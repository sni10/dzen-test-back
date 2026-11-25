import logging

from celery import shared_task
from elasticsearch import ConnectionError as ApiConnectionError

from .attachments import processor_for
from .live import ChannelsNotifier
from .models import Attachment, Comment

logger = logging.getLogger(__name__)


@shared_task
def process_attachment(attachment_id: int) -> None:
    """Finish an uploaded attachment (resize an image) and mark it ready, or failed."""
    attachment = Attachment.objects.filter(pk=attachment_id, status=Attachment.Status.PROCESSING).first()
    if attachment is None:
        return  # deleted meanwhile, or already done by a redelivered task
    try:
        processor_for(attachment.kind).process(attachment)
        attachment.status = Attachment.Status.READY
    except Exception:
        logger.exception('Attachment %s could not be processed', attachment_id)
        attachment.status = Attachment.Status.FAILED
    attachment.save()
    ChannelsNotifier().attachment_updated(attachment)  # the SPA swaps the placeholder for the image


@shared_task(autoretry_for=(ConnectionError, ApiConnectionError), retry_backoff=True, max_retries=5)
def index_comments(comment_ids: list[int]) -> None:
    """Bring the search index in line with the database for these comments (saved, changed or deleted)."""
    from .container import search_index

    found = list(Comment.objects.filter(pk__in=comment_ids))
    index = search_index()
    if found:
        index.save(found)
    if missing := set(comment_ids) - {comment.pk for comment in found}:
        index.remove(sorted(missing))
