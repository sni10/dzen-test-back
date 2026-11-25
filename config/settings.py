"""Django settings. All environment-specific values come from env vars / .env, validated in config/app_settings."""
import os
from datetime import timedelta
from pathlib import Path

from .app_settings import load_settings

BASE_DIR = Path(__file__).resolve().parent.parent

ENV = load_settings(BASE_DIR / '.env')

SECRET_KEY = ENV.django.secret_key.get_secret_value()
DEBUG = ENV.django.debug
ALLOWED_HOSTS = ENV.django.allowed_hosts

# Behind Caddy, which sets X-Forwarded-Proto itself
SECURE_PROXY_SSL_HEADER = ('HTTP_X_FORWARDED_PROTO', 'https')
SESSION_COOKIE_SECURE = CSRF_COOKIE_SECURE = not DEBUG

# CI sets TEST_REPORTS_DIR: tests also write a JUnit report there (unittest-xml-reporting, a dev dependency)
if os.environ.get('TEST_REPORTS_DIR'):
    TEST_RUNNER = 'xmlrunner.extra.djangotestrunner.XMLTestRunner'
    TEST_OUTPUT_DIR = os.environ['TEST_REPORTS_DIR']
    TEST_OUTPUT_FILE_NAME = 'junit.xml'

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'rest_framework',
    'rest_framework_simplejwt.token_blacklist',
    'drf_spectacular',
    'corsheaders',
    'common',
    'accounts',
    'comments',
    'captcha',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # admin static from the app container
    'django.contrib.sessions.middleware.SessionMiddleware',
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'common.guest.GuestKeyMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
]

ROOT_URLCONF = 'config.urls'

TEMPLATES = [
    {
        'BACKEND': 'django.template.backends.django.DjangoTemplates',
        'DIRS': [],
        'APP_DIRS': True,
        'OPTIONS': {
            'context_processors': [
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
            ],
        },
    },
]

ASGI_APPLICATION = 'config.asgi.application'
WSGI_APPLICATION = 'config.wsgi.application'

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.mysql',
        'NAME': ENV.db.name,
        'USER': ENV.db.user,
        'PASSWORD': ENV.db.password.get_secret_value(),
        'HOST': ENV.db.host,
        'PORT': ENV.db.port,
        'OPTIONS': {
            'charset': 'utf8mb4',
            'init_command': "SET sql_mode='STRICT_TRANS_TABLES'",
        },
        'TEST': {'CHARSET': 'utf8mb4', 'COLLATION': 'utf8mb4_unicode_ci'},
    }
}

REDIS_URL = ENV.redis.url

# WebSocket groups (Channels) live in Redis, so the web process and Celery workers reach every connection
CHANNEL_LAYERS = {
    'default': {
        'BACKEND': 'channels_redis.core.RedisChannelLayer',
        # A consumer waits for messages with a blocking Redis read of 5 s (channels_redis brpop_timeout);
        # redis-py 8 times socket reads out after 5 s by default, which drops idle sockets. Read longer.
        'CONFIG': {'hosts': [{'address': ENV.redis.url, 'socket_timeout': 15}]},
    },
}

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': ENV.redis.url,
        'KEY_PREFIX': 'dzen',
    }
}

AUTH_USER_MODEL = 'accounts.User'

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / ENV.static.root

MEDIA_URL = ENV.media.url
MEDIA_ROOT = BASE_DIR / ENV.media.root

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

CORS_ALLOWED_ORIGINS = ENV.cors.allowed_origins
CORS_ALLOW_CREDENTIALS = True  # the guest_key cookie travels with fetch(..., {credentials: 'include'})

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    # The API trusts only the Bearer token, never the session cookie (no CSRF surface); sessions are for /admin
    'DEFAULT_AUTHENTICATION_CLASSES': ['rest_framework_simplejwt.authentication.JWTAuthentication'],
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'UNAUTHENTICATED_USER': None,
    # Counters live in the Redis cache, shared by all workers
    'DEFAULT_THROTTLE_RATES': {
        'captcha': '30/min',
        'comment_create': '10/min',
        'comment_preview': '60/min',
        'auth_register': '5/min',
        'auth_login': '10/min',
        'auth_refresh': '30/min',
        'auth_password_reset': '5/min',
        'auth_password_reset_confirm': '10/min',
    },
}

# Mail: Brevo SMTP in production (EMAIL_* in the server's .env), printed to the log locally
MAILERS = {
    'default': {
        'BACKEND': f'django.core.mail.backends.{ENV.email.backend}.EmailBackend',
        'OPTIONS': {
            'host': ENV.email.host,
            'port': ENV.email.port,
            'username': ENV.email.user,
            'password': ENV.email.password.get_secret_value(),
            'use_tls': ENV.email.use_tls,
            'timeout': ENV.email.timeout,
        } if ENV.email.backend == 'smtp' else {},
    },
}
DEFAULT_FROM_EMAIL = ENV.email.sender
PASSWORD_RESET_TIMEOUT = 3600  # the reset link works for one hour (and only once: the token dies with the old password)

SIMPLE_JWT = {
    'ACCESS_TOKEN_LIFETIME': timedelta(minutes=15),
    'REFRESH_TOKEN_LIFETIME': timedelta(days=7),
    'UPDATE_LAST_LOGIN': True,
}

CAPTCHA_LENGTH = 5
CAPTCHA_TTL = 300  # seconds; each CAPTCHA is also single-use

# Celery over RabbitMQ: background work (image resizing). Results are not needed, only side effects.
CELERY_BROKER_URL = ENV.rabbitmq.url
CELERY_TASK_IGNORE_RESULT = True
CELERY_TASK_ACKS_LATE = True  # a task survives a worker crash
CELERY_WORKER_PREFETCH_MULTIPLIER = 1

SPECTACULAR_SETTINGS = {
    'TITLE': 'Comments API',
    'DESCRIPTION': 'Tree comments with CAPTCHA, attachments, live updates and moderation.',
    'VERSION': os.environ.get('APP_VERSION', 'dev'),
    'SERVE_INCLUDE_SCHEMA': False,
}

LOGGING = {
    'version': 1,
    'disable_existing_loggers': False,
    'handlers': {'console': {'class': 'logging.StreamHandler'}},
    'root': {'handlers': ['console'], 'level': 'INFO'},
}
