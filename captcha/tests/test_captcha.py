import base64
import io
import uuid
from unittest import mock

from django.core.cache import cache
from django.test import SimpleTestCase
from django.urls import reverse
from PIL import Image

from captcha.container import redis_client
from captcha.generator import ALPHABET, CaptchaGenerator
from captcha.service import CaptchaService
from captcha.stores import RedisCaptchaStore

from .fakes import InMemoryCaptchaStore


class CaptchaGeneratorTests(SimpleTestCase):
    def test_text_uses_unambiguous_latin_letters_and_digits(self):
        generator = CaptchaGenerator(length=6)
        texts = {generator.text() for _ in range(50)}

        self.assertGreater(len(texts), 45)  # random
        for text in texts:
            self.assertEqual(len(text), 6)
            self.assertTrue(set(text) <= set(ALPHABET))
        self.assertFalse(set('0Oo1lIsS') & set(ALPHABET))

    def test_image_is_png_of_the_configured_size(self):
        png = CaptchaGenerator(width=200, height=70).image('ab3Cd')

        image = Image.open(io.BytesIO(png))
        self.assertEqual((image.format, image.size), ('PNG', (200, 70)))

    def test_same_text_draws_differently(self):
        generator = CaptchaGenerator()

        self.assertNotEqual(generator.image('ab3Cd'), generator.image('ab3Cd'))


class CaptchaServiceTests(SimpleTestCase):
    """Runs on the in-memory store: the service only knows the CaptchaStore protocol."""

    def setUp(self):
        self.store = InMemoryCaptchaStore()
        self.generator = CaptchaGenerator()
        self.service = CaptchaService(self.store, self.generator, ttl=120)

    def issue(self, text='Ab3Cd'):
        with mock.patch.object(self.generator, 'text', return_value=text):
            return self.service.issue()

    def test_issue_stores_answer_with_ttl(self):
        challenge = self.issue()

        self.assertEqual(self.store.answers[challenge.key], 'Ab3Cd')
        self.assertEqual(self.store.ttls[challenge.key], 120)
        self.assertTrue(challenge.image_data_uri.startswith('data:image/png;base64,'))

    def test_keys_are_unique_and_unguessable(self):
        keys = {self.service.issue().key for _ in range(20)}

        self.assertEqual(len(keys), 20)
        self.assertTrue(all(len(key) >= 20 for key in keys))

    def test_right_answer_any_case(self):
        for answer in ('Ab3Cd', 'ab3cd', 'AB3CD', ' ab3cd '):
            with self.subTest(answer=answer):
                self.assertTrue(self.service.verify(self.issue().key, answer))

    def test_wrong_answer(self):
        self.assertFalse(self.service.verify(self.issue().key, 'xxxxx'))

    def test_single_use_even_after_a_right_answer(self):
        key = self.issue().key

        self.assertTrue(self.service.verify(key, 'Ab3Cd'))
        self.assertFalse(self.service.verify(key, 'Ab3Cd'))

    def test_wrong_answer_uses_the_captcha_up(self):
        key = self.issue().key

        self.assertFalse(self.service.verify(key, 'wrong'))
        self.assertFalse(self.service.verify(key, 'Ab3Cd'))

    def test_answer_must_be_latin_letters_and_digits(self):
        for answer in ('Ab3-d', 'Аb3Cd', '', 'Ab3Cd; DROP'):
            with self.subTest(answer=answer):
                key = self.issue().key
                self.assertFalse(self.service.verify(key, answer))
                self.assertNotIn(key, self.store.answers)

    def test_unknown_or_empty_key(self):
        self.assertFalse(self.service.verify('nope', 'Ab3Cd'))
        self.assertFalse(self.service.verify('', 'Ab3Cd'))


class RedisCaptchaStoreTests(SimpleTestCase):
    def setUp(self):
        self.store = RedisCaptchaStore(redis_client())
        self.key = f'test-{uuid.uuid4().hex}'

    def tearDown(self):
        redis_client().delete(self.store.prefix + self.key)

    def test_save_then_pop_once(self):
        self.store.save(self.key, 'Ab3Cd', ttl=60)

        self.assertEqual(self.store.pop(self.key), 'Ab3Cd')
        self.assertIsNone(self.store.pop(self.key))

    def test_answer_expires(self):
        self.store.save(self.key, 'Ab3Cd', ttl=60)

        ttl = redis_client().ttl(self.store.prefix + self.key)
        self.assertTrue(0 < ttl <= 60)

    def test_unknown_key(self):
        self.assertIsNone(self.store.pop(self.key))


class CaptchaViewTests(SimpleTestCase):
    url = reverse('captcha')

    def setUp(self):
        cache.clear()  # throttle counters

    def test_returns_key_and_inline_png(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(set(body), {'key', 'image', 'ttl'})
        prefix = 'data:image/png;base64,'
        self.assertTrue(body['image'].startswith(prefix))
        Image.open(io.BytesIO(base64.b64decode(body['image'][len(prefix):]))).verify()
        self.assertIn('no-store', response['Cache-Control'])

    def test_issued_captcha_can_be_verified_through_the_container(self):
        from captcha.container import captcha_service

        key = self.client.get(self.url).json()['key']
        answer = redis_client().get(RedisCaptchaStore.prefix + key).decode()

        self.assertTrue(captcha_service().verify(key, answer))

    def test_rate_limited(self):
        with mock.patch.dict('rest_framework.throttling.ScopedRateThrottle.THROTTLE_RATES', {'captcha': '2/min'}):
            codes = [self.client.get(self.url).status_code for _ in range(3)]

        self.assertEqual(codes, [200, 200, 429])
