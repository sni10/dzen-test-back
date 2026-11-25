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
