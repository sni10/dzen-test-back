"""Typed configuration sections. Each section reads env vars with its own prefix and validates them."""
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import urlsplit

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

Port = Annotated[int, Field(ge=1, le=65535)]
CommaList = Annotated[list[str], NoDecode]  # "a, b" in env -> ['a', 'b']


def split_commas(value):
    if isinstance(value, str):
        return [item.strip() for item in value.split(',') if item.strip()]
    return value


def check_origin(origin: str) -> str:
    parts = urlsplit(origin)
    if parts.scheme not in ('http', 'https') or not parts.netloc or parts.path or parts.query:
        raise ValueError(f'"{origin}" must look like scheme://host[:port] without a path')
    return origin


class Section(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore', env_file_encoding='utf-8')


class DjangoSettings(Section):
    model_config = SettingsConfigDict(env_prefix='DJANGO_')

    secret_key: SecretStr
    debug: bool = False
    allowed_hosts: CommaList = []

    _split_hosts = field_validator('allowed_hosts', mode='before')(split_commas)

    @model_validator(mode='after')
    def check_production(self):
        if self.debug:
            return self
        key = self.secret_key.get_secret_value()
        if len(key) < 50 or key.startswith('django-insecure-'):
            raise ValueError('DJANGO_SECRET_KEY must be a random value of 50+ chars when DJANGO_DEBUG=false')
        if not self.allowed_hosts:
            raise ValueError('DJANGO_ALLOWED_HOSTS is required when DJANGO_DEBUG=false')
        return self


class DatabaseSettings(Section):
    """MySQL 8.4. The test database (`test_<name>`) is created by the same user, so it needs CREATE rights."""

    model_config = SettingsConfigDict(env_prefix='DB_')

    name: str
    user: str
    password: SecretStr
    host: str = 'db'  # the compose service
    port: Port = 3306


class RedisSettings(Section):
    """Cache now; later also CAPTCHA answers and the Channels layer."""

    model_config = SettingsConfigDict(env_prefix='REDIS_')

    url: str = 'redis://redis:6379/0'

    @field_validator('url')
    @classmethod
    def check_url(cls, url):
        if urlsplit(url).scheme not in ('redis', 'rediss'):
            raise ValueError('must be redis://host:port/db')
        return url


class RabbitMQSettings(Section):
    """Message broker for Celery (image processing now; search indexing and events later)."""

    model_config = SettingsConfigDict(env_prefix='RABBITMQ_')

    url: str = 'amqp://dzen:dzen@rabbitmq:5672//'

    @field_validator('url')
    @classmethod
    def check_url(cls, url):
        if urlsplit(url).scheme not in ('amqp', 'amqps'):
            raise ValueError('must be amqp://user:password@host:port/vhost')
        return url


class EmailSettings(Section):
    """Account emails (password reset). Production: Brevo SMTP; locally they are printed to the log."""

    model_config = SettingsConfigDict(env_prefix='EMAIL_')

    backend: Literal['console', 'smtp'] = 'console'
    host: str = 'smtp-relay.brevo.com'
    port: Port = 587
    user: str = ''
    password: SecretStr = SecretStr('')
    use_tls: bool = True
    timeout: int = Field(10, ge=1, description='SMTP connect/send timeout, seconds')
    sender: str = 'Comments <noreply@localhost>'


class CorsSettings(Section):
    model_config = SettingsConfigDict(env_prefix='CORS_')

    allowed_origins: CommaList = []

    _split_origins = field_validator('allowed_origins', mode='before')(split_commas)

    @field_validator('allowed_origins')
    @classmethod
    def check_origins(cls, origins):
        for origin in origins:
            check_origin(origin)
        return origins


class StaticSettings(Section):
    model_config = SettingsConfigDict(env_prefix='STATIC_')

    root: Path = Path('staticfiles')  # `collectstatic` target; relative to the project root


class MediaSettings(Section):
    """Comment attachments (resized images, TXT files)."""

    model_config = SettingsConfigDict(env_prefix='MEDIA_')

    root: Path = Path('media')  # relative to the project root
    url: str = '/media/'

    @field_validator('url')
    @classmethod
    def check_url(cls, url):
        if not url.endswith('/'):
            raise ValueError('must end with /')
        return url


class AppSettings(BaseModel):
    django: DjangoSettings
    db: DatabaseSettings
    redis: RedisSettings
    rabbitmq: RabbitMQSettings
    email: EmailSettings
    cors: CorsSettings
    static: StaticSettings
    media: MediaSettings
