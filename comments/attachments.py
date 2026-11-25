"""Comment attachments: an image (JPG / GIF / PNG, fitted into 320x240) or a TXT file (up to 100 KB).

A processor per kind: `inspect` checks an upload before anything is saved (by content, not by the file
name), `process` finishes a saved attachment. A new kind is a new processor in PROCESSORS.
"""
import io
from abc import ABC, abstractmethod
from dataclasses import dataclass

from django.core.files.base import ContentFile
from django.core.files.uploadedfile import UploadedFile
from PIL import Image, ImageOps, ImageSequence, UnidentifiedImageError

from .models import Attachment

MAX_BOX = (320, 240)
MAX_IMAGE_BYTES = 5 * 1024 * 1024
MAX_IMAGE_PIXELS = 40_000_000  # decompression bombs: a small file that unpacks into gigabytes
MAX_TEXT_BYTES = 100 * 1024
IMAGE_FORMATS = {'JPEG': 'jpg', 'PNG': 'png', 'GIF': 'gif'}


class AttachmentRejected(ValueError):
    pass


@dataclass(frozen=True)
class CheckedUpload:
    kind: str
    extension: str  # of the stored file, from the detected format
    needs_processing: bool


class AttachmentProcessor(ABC):
    kind: str

    @abstractmethod
    def accepts(self, upload: UploadedFile) -> bool: ...

    @abstractmethod
    def inspect(self, upload: UploadedFile) -> CheckedUpload: ...

    def process(self, attachment: Attachment) -> None:
        """Finish a saved attachment in the background (nothing to do by default)."""


class TextProcessor(AttachmentProcessor):
    kind = Attachment.Kind.TEXT

    def accepts(self, upload):
        return (upload.name or '').lower().endswith('.txt')

    def inspect(self, upload):
        if upload.size > MAX_TEXT_BYTES:
            raise AttachmentRejected('A text file must be at most 100 KB')
        upload.seek(0)
        data = upload.read()
        upload.seek(0)
        if not data.strip():
            raise AttachmentRejected('The text file is empty')
        try:
            data.decode('utf-8-sig')
        except UnicodeDecodeError:
            raise AttachmentRejected('The text file must be in UTF-8') from None
        return CheckedUpload(self.kind, 'txt', needs_processing=False)


class ImageProcessor(AttachmentProcessor):
    kind = Attachment.Kind.IMAGE

    def accepts(self, upload):
        return True  # anything that is not .txt must be an image

    def inspect(self, upload):
        if upload.size > MAX_IMAGE_BYTES:
            raise AttachmentRejected('An image must be at most 5 MB')
        upload.seek(0)
        try:
            with Image.open(upload) as image:
                image_format = image.format
                width, height = image.size
                image.verify()
        except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError):
            raise AttachmentRejected('Attach a JPG, GIF or PNG image or a TXT file') from None
        finally:
            upload.seek(0)
        if image_format not in IMAGE_FORMATS:
            raise AttachmentRejected('Only JPG, GIF and PNG images are allowed')
        if width * height > MAX_IMAGE_PIXELS:
            raise AttachmentRejected('The image is too large')
        return CheckedUpload(self.kind, IMAGE_FORMATS[image_format], needs_processing=True)

    def process(self, attachment):
        """Fit into 320x240 keeping proportions and always re-encode: drops EXIF and anything appended."""
        with attachment.file.open('rb') as source:
            data, width, height = fit_image(source.read())
        storage, name = attachment.file.storage, attachment.file.name
        storage.delete(name)
        attachment.file.name = storage.save(name, ContentFile(data))
        attachment.width, attachment.height, attachment.size = width, height, len(data)


def fit_image(data: bytes) -> tuple[bytes, int, int]:
    """Smaller images keep their size; animated GIFs keep their frames."""
    buffer = io.BytesIO()
    with Image.open(io.BytesIO(data)) as image:
        image_format = image.format
        if image_format == 'GIF' and getattr(image, 'is_animated', False):
            frames, durations = [], []
            for frame in ImageSequence.Iterator(image):
                copy = frame.convert('RGBA')
                copy.thumbnail(MAX_BOX, Image.Resampling.LANCZOS)
                frames.append(copy)
                durations.append(frame.info.get('duration', 100))
            frames[0].save(buffer, 'GIF', save_all=True, append_images=frames[1:], duration=durations,
                           loop=image.info.get('loop', 0), disposal=2)
            size = frames[0].size
        else:
            result = ImageOps.exif_transpose(image)  # photos taken sideways stay upright without EXIF
            result.thumbnail(MAX_BOX, Image.Resampling.LANCZOS)
            if image_format == 'JPEG' and result.mode not in ('RGB', 'L'):
                result = result.convert('RGB')
            result.save(buffer, image_format, optimize=True)
            size = result.size
    return buffer.getvalue(), size[0], size[1]


PROCESSORS: tuple[AttachmentProcessor, ...] = (TextProcessor(), ImageProcessor())


def inspect_upload(upload: UploadedFile) -> CheckedUpload:
    processor = next(p for p in PROCESSORS if p.accepts(upload))
    return processor.inspect(upload)


def processor_for(kind: str) -> AttachmentProcessor:
    return next(p for p in PROCESSORS if p.kind == kind)
