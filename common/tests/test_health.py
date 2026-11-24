from unittest import mock

from django.test import TestCase
from django.urls import reverse


class HealthViewTests(TestCase):
    url = reverse('health')

    def test_ok_when_db_and_cache_respond(self):
        response = self.client.get(self.url)

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), {'status': 'ok', 'db': True, 'cache': True})

    def test_degraded_when_cache_is_down(self):
        with mock.patch('common.views.cache.set', side_effect=ConnectionError):
            response = self.client.get(self.url)

        self.assertEqual(response.status_code, 503)
        self.assertEqual(response.json(), {'status': 'degraded', 'db': True, 'cache': False})

    def test_openapi_schema_is_served(self):
        response = self.client.get(reverse('schema'))

        self.assertEqual(response.status_code, 200)
