from django.test import SimpleTestCase
from pydantic import ValidationError

from config.app_settings.schema import DjangoSettings

PRODUCTION = {'secret_key': 'x' * 60, 'allowed_hosts': 'example.com', 'debug': False}


class ThrottlingSwitchTests(SimpleTestCase):
    def test_rate_limits_cannot_be_switched_off_in_production(self):
        with self.assertRaisesRegex(ValidationError, 'load test only'):
            DjangoSettings(**PRODUCTION, throttling=False)

    def test_off_for_a_local_load_test(self):
        self.assertFalse(DjangoSettings(**{**PRODUCTION, 'debug': True}, throttling=False).throttling)


class GraphQLBodyTests(SimpleTestCase):
    def test_a_body_that_is_not_utf8_is_a_client_error(self):
        body = '{"query": "{ search(query: \\"комментарий\\") { totalCount } }"}'.encode('cp1251')

        response = self.client.post('/graphql', body, content_type='application/json')

        self.assertEqual(response.status_code, 400)
        self.assertIn('UTF-8', response.content.decode())
