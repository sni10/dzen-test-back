"""Django settings. All environment-specific values come from env vars / .env, validated in config/app_settings."""
import os
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
    'drf_spectacular',
    'corsheaders',
    'common',
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

CACHES = {
    'default': {
        'BACKEND': 'django.core.cache.backends.redis.RedisCache',
        'LOCATION': ENV.redis.url,
        'KEY_PREFIX': 'dzen',
    }
}

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

REST_FRAMEWORK = {
    'DEFAULT_SCHEMA_CLASS': 'drf_spectacular.openapi.AutoSchema',
    'DEFAULT_AUTHENTICATION_CLASSES': [],  # JWT comes with the auth feature
    'DEFAULT_PERMISSION_CLASSES': ['rest_framework.permissions.AllowAny'],
    'DEFAULT_RENDERER_CLASSES': ['rest_framework.renderers.JSONRenderer'],
    'UNAUTHENTICATED_USER': None,
}

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
