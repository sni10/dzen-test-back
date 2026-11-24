import logging

from celery import shared_task

from .attachments import processor_for
from .models import Attachment

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
