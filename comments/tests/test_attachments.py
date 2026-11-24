import io
import shutil
import tempfile
from unittest import mock

from django.core.cache import cache
from django.core.files.base import ContentFile
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import connection
from django.test import TestCase, override_settings
from django.test.utils import CaptureQueriesContext
from django.urls import reverse
from PIL import Image

from comments.attachments import AttachmentRejected, fit_image, inspect_upload
from comments.markup import CommentMarkup
from comments.models import Attachment
from comments.services import Author, CommentService, InvalidAttachment, NewComment
from comments.tasks import process_attachment

from .factories import make_comment
from .test_create import FakeCaptcha

MEDIA_ROOT = tempfile.mkdtemp(prefix='dzen-test-media-')


def image_bytes(image_format='JPEG', size=(100, 80), frames=1, exif=False) -> bytes:
    buffer = io.BytesIO()
    images = [Image.new('RGB', size, (40 * n % 255, 120, 200)) for n in range(frames)]
    options = {}
    if frames > 1:
        options = {'save_all': True, 'append_images': images[1:], 'duration': 50, 'loop': 0}
    if exif:
        data = Image.Exif()
        data[0x010F] = 'SecretCamera'  # Make
        options['exif'] = data
    images[0].save(buffer, image_format, **options)
    return buffer.getvalue()


def upload(name, content, content_type='application/octet-stream'):
    return SimpleUploadedFile(name, content, content_type=content_type)


@override_settings(MEDIA_ROOT=MEDIA_ROOT)
class MediaTestCase(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(MEDIA_ROOT, ignore_errors=True)


class InspectTests(MediaTestCase):
    def test_images_are_recognised_by_content(self):
        for image_format, extension in (('JPEG', 'jpg'), ('PNG', 'png'), ('GIF', 'gif')):
            with self.subTest(image_format=image_format):
                # a misleading name does not matter, the content decides
                checked = inspect_upload(upload('photo.bin', image_bytes(image_format)))
                self.assertEqual((checked.kind, checked.extension, checked.needs_processing),
                                 ('image', extension, True))

    def test_text_file(self):
        checked = inspect_upload(upload('notes.TXT', 'Привет, мир'.encode()))

        self.assertEqual((checked.kind, checked.extension, checked.needs_processing), ('text', 'txt', False))

    def test_rejected_uploads(self):
        cases = {
            'fake.png': b'<?php echo 1; ?>',
            'picture.bmp': image_bytes('BMP'),
            'picture.webp': image_bytes('WEBP'),
            'empty.txt': b'   ',
            'cp1251.txt': 'Привет'.encode('cp1251'),
            'big.txt': b'x' * (100 * 1024 + 1),
        }
        for name, content in cases.items():
            with self.subTest(name=name), self.assertRaises(AttachmentRejected):
                inspect_upload(upload(name, content))

    def test_text_limit_is_inclusive(self):
        inspect_upload(upload('exact.txt', b'x' * 100 * 1024))

    def test_image_size_limits(self):
        with mock.patch('comments.attachments.MAX_IMAGE_BYTES', 100), self.assertRaises(AttachmentRejected):
            inspect_upload(upload('a.png', image_bytes('PNG', (50, 50))))
        with mock.patch('comments.attachments.MAX_IMAGE_PIXELS', 99), self.assertRaises(AttachmentRejected):
            inspect_upload(upload('a.png', image_bytes('PNG', (10, 10))))


class FitImageTests(MediaTestCase):
    def fitted(self, data):
        result, width, height = fit_image(data)
        with Image.open(io.BytesIO(result)) as image:
            self.assertEqual(image.size, (width, height))
            return image.format, image.size, getattr(image, 'n_frames', 1), image.getexif()

    def test_large_image_is_fitted_into_320x240_keeping_proportions(self):
        cases = {(1000, 800): (300, 240), (1600, 400): (320, 80), (480, 960): (120, 240)}
        for source, expected in cases.items():
            with self.subTest(source=source):
                self.assertEqual(self.fitted(image_bytes('JPEG', source))[1], expected)

    def test_small_image_keeps_its_size_and_format(self):
        for image_format in ('JPEG', 'PNG', 'GIF'):
            with self.subTest(image_format=image_format):
                self.assertEqual(self.fitted(image_bytes(image_format, (200, 100)))[:2], (image_format, (200, 100)))

    def test_animated_gif_keeps_its_frames(self):
        image_format, size, frames, _ = self.fitted(image_bytes('GIF', (640, 480), frames=4))

        self.assertEqual((image_format, size, frames), ('GIF', (320, 240), 4))

    def test_metadata_is_dropped(self):
        source = image_bytes('JPEG', (200, 100), exif=True)
        with Image.open(io.BytesIO(source)) as original:
            self.assertEqual(original.getexif().get(0x010F), 'SecretCamera')

        self.assertNotIn(0x010F, self.fitted(source)[3])


class ProcessTaskTests(MediaTestCase):
    def attachment(self, content, status=Attachment.Status.PROCESSING):
        attachment = Attachment(comment=make_comment(), kind='image', original_name='photo.jpg',
                                size=len(content), status=status)
        attachment.file.save('upload.jpg', ContentFile(content), save=False)
        attachment.save()
        return attachment

    def test_image_is_resized_and_marked_ready(self):
        attachment = self.attachment(image_bytes('JPEG', (1000, 800)))
        name = attachment.file.name

        process_attachment(attachment.pk)

        attachment.refresh_from_db()
        self.assertEqual(attachment.status, 'ready')
        self.assertEqual((attachment.width, attachment.height), (300, 240))
        self.assertEqual(attachment.file.name, name)
        self.assertEqual(attachment.size, attachment.file.size)
        with attachment.file.open('rb') as stored, Image.open(stored) as image:
            self.assertEqual(image.size, (300, 240))

    def test_broken_file_is_marked_failed(self):
        attachment = self.attachment(b'not an image')

        with self.assertLogs('comments.tasks', 'ERROR'):
            process_attachment(attachment.pk)

        attachment.refresh_from_db()
        self.assertEqual(attachment.status, 'failed')

    def test_finished_or_missing_attachment_is_left_alone(self):
        attachment = self.attachment(image_bytes(), status=Attachment.Status.READY)

        process_attachment(attachment.pk)
        process_attachment(999999)

        attachment.refresh_from_db()
        self.assertIsNone(attachment.width)


class ServiceTests(MediaTestCase):
    def setUp(self):
        self.captcha = FakeCaptcha()
        self.queued = []
        self.service = CommentService(CommentMarkup(), self.captcha.service, self.queued.append)

    def create(self, attachment, **overrides):
        data = NewComment(user_name='Anonym', email='a@example.com', text='See the file',
                          captcha_key=self.captcha.new_key(), captcha_answer='Ab3Cd', attachment=attachment,
                          **overrides)
        with self.captureOnCommitCallbacks(execute=True):
            return self.service.create(data, Author())

    def test_image_is_saved_and_queued_after_commit(self):
        comment = self.create(upload('My Photo.JPG', image_bytes('PNG', (500, 500))))

        attachment = comment.attachments.get()
        self.assertEqual((attachment.kind, attachment.status, attachment.original_name),
                         ('image', 'processing', 'My Photo.JPG'))
        self.assertTrue(attachment.file.name.endswith('.png'))  # from the detected format
        self.assertNotIn('Photo', attachment.file.name)
        self.assertEqual(self.queued, [attachment.pk])

    def test_text_is_ready_at_once(self):
        comment = self.create(upload('notes.txt', b'hello'))

        attachment = comment.attachments.get()
        self.assertEqual((attachment.kind, attachment.status, attachment.size), ('text', 'ready', 5))
        self.assertEqual(self.queued, [])
        with attachment.file.open('rb') as stored:
            self.assertEqual(stored.read(), b'hello')

    def test_rejected_file_saves_nothing_and_keeps_the_captcha(self):
        key = self.captcha.new_key()
        data = NewComment(user_name='Anonym', email='a@example.com', text='x', captcha_key=key,
                          captcha_answer='Ab3Cd', attachment=upload('fake.png', b'nope'))

        with self.assertRaises(InvalidAttachment):
            self.service.create(data, Author())

        self.assertFalse(Attachment.objects.exists())
        self.assertTrue(self.captcha.service.verify(key, 'Ab3Cd'))  # the CAPTCHA was not spent


class ApiTests(MediaTestCase):
    url = reverse('comment-create')

    def setUp(self):
        cache.clear()
        self.captcha = FakeCaptcha()
        for patcher in (
            mock.patch('comments.container.captcha_service', return_value=self.captcha.service),
            mock.patch('comments.container.process_attachment'),
            mock.patch.dict('rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES',
                            {'comment_create': '1000/min'}),
        ):
            patcher.start()
            self.addCleanup(patcher.stop)
        from comments.container import comment_service
        comment_service.cache_clear()
        self.addCleanup(comment_service.cache_clear)

    def post(self, attachment):
        return self.client.post(self.url, {
            'user_name': 'Anonym', 'email': 'a@example.com', 'text': 'With a file',
            'captcha_key': self.captcha.new_key(), 'captcha_answer': 'Ab3Cd', 'attachment': attachment,
        })

    def test_multipart_post_with_an_image(self):
        response = self.post(upload('cat.gif', image_bytes('GIF', (400, 300)), 'image/gif'))

        self.assertEqual(response.status_code, 201)
        [attachment] = response.json()['attachments']
        self.assertEqual((attachment['kind'], attachment['status'], attachment['original_name']),
                         ('image', 'processing', 'cat.gif'))
        self.assertRegex(attachment['url'], r'^/media/attachments/[0-9a-f]{2}/[0-9a-f]{32}\.gif$')

    def test_multipart_post_with_a_text_file(self):
        response = self.post(upload('notes.txt', b'plain text', 'text/plain'))

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['attachments'][0]['status'], 'ready')

    def test_rejected_file(self):
        response = self.post(upload('virus.exe', b'MZ\x90\x00', 'application/x-msdownload'))

        self.assertEqual(response.status_code, 400)
        self.assertIn('attachment', response.json())

    def test_comment_without_a_file_has_no_attachments(self):
        response = self.client.post(self.url, {
            'user_name': 'Anonym', 'email': 'a@example.com', 'text': 'No file',
            'captcha_key': self.captcha.new_key(), 'captcha_answer': 'Ab3Cd',
        })

        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.json()['attachments'], [])


class GraphQLAttachmentTests(MediaTestCase):
    query = '{ comments { items { attachments { kind url status width height originalName } '\
            'replies { items { attachments { kind } } } } } }'

    def attach(self, comment, kind='image'):
        attachment = Attachment(comment=comment, kind=kind, original_name='f', size=1, status='ready',
                                width=10, height=10)
        attachment.file.save('f.png', ContentFile(b'x'), save=False)
        attachment.save()

    def run_query(self):
        response = self.client.post(reverse('graphql'), {'query': self.query}, content_type='application/json')
        self.assertNotIn('errors', response.json())
        return response.json()['data']['comments']['items']

    def test_attachments_are_listed(self):
        self.attach(make_comment())

        [item] = self.run_query()

        self.assertEqual(item['attachments'][0]['kind'], 'image')
        self.assertTrue(item['attachments'][0]['url'].startswith('/media/attachments/'))

    def test_hidden_by_moderator_means_no_attachments(self):
        self.attach(make_comment(is_ufo=True))

        self.assertEqual(self.run_query()[0]['attachments'], [])

    def test_attachments_do_not_add_a_query_per_comment(self):
        def count():
            with CaptureQueriesContext(connection) as queries:
                self.run_query()
            return len(queries)

        self.attach(make_comment(parent=make_comment()))
        few = count()
        for _ in range(8):
            root = make_comment()
            self.attach(root)
            self.attach(make_comment(parent=root), kind='text')

        self.assertEqual(count(), few)
