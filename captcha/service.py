import base64
import hmac
import re
import secrets
from dataclasses import dataclass

from .generator import CaptchaGenerator
from .stores import CaptchaStore

ANSWER_PATTERN = re.compile(r'^[A-Za-z0-9]+$')  # the assignment: Latin letters and digits


@dataclass(frozen=True)
class Challenge:
    key: str
    image_png: bytes

    @property
    def image_data_uri(self) -> str:
        """Inline image: no second request and nothing stored on disk."""
        return 'data:image/png;base64,' + base64.b64encode(self.image_png).decode()


class CaptchaService:
    """Issue a CAPTCHA and check an answer exactly once. Depends on the CaptchaStore protocol only."""

    def __init__(self, store: CaptchaStore, generator: CaptchaGenerator, ttl: int = 300):
        self.store = store
        self.generator = generator
        self.ttl = ttl

    def issue(self) -> Challenge:
        text = self.generator.text()
        key = secrets.token_urlsafe(16)
        self.store.save(key, text, self.ttl)
        return Challenge(key=key, image_png=self.generator.image(text))

    def verify(self, key: str, answer: str) -> bool:
        """Case-insensitive. Any attempt, right or wrong, uses the CAPTCHA up: the client must fetch a new one."""
        answer = (answer or '').strip()
        if not key or not answer or not ANSWER_PATTERN.match(answer):
            if key:
                self.store.pop(key)
            return False
        expected = self.store.pop(key)
        if expected is None:
            return False
        return hmac.compare_digest(expected.lower().encode(), answer.lower().encode())
