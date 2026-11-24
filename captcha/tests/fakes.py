class InMemoryCaptchaStore:
    """Test double for CaptchaStore: a dict, no Redis. TTL is recorded, not enforced."""

    def __init__(self):
        self.answers: dict[str, str] = {}
        self.ttls: dict[str, int] = {}

    def save(self, key: str, answer: str, ttl: int) -> None:
        self.answers[key] = answer
        self.ttls[key] = ttl

    def pop(self, key: str) -> str | None:
        self.ttls.pop(key, None)
        return self.answers.pop(key, None)
