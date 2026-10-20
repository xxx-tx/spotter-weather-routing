"""Django settings for the route planner."""

from pathlib import Path
import os

from django.core.exceptions import ImproperlyConfigured
from dotenv import load_dotenv

# Build paths inside the project like this: BASE_DIR / 'subdir'.
BASE_DIR = Path(__file__).resolve().parent.parent
load_dotenv(BASE_DIR / '.env')

TOMTOM_API_KEY = os.getenv('TOMTOM_API_KEY', '')


# Fail closed when settings are not provided: local development must explicitly
# enable DJANGO_DEBUG=true in backend/.env (as shown in .env.example).
def env_boolean(name, default=False):
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def env_list(name, default=""):
    return [value.strip() for value in os.getenv(name, default).split(",") if value.strip()]


DEBUG = env_boolean("DJANGO_DEBUG", False)
SECRET_KEY = os.getenv("DJANGO_SECRET_KEY")
if not SECRET_KEY:
    if DEBUG:
        # This fallback is intentionally for local development ONLY.
        SECRET_KEY = "development-only-insecure-secret-change-for-deployment"
    else:
        raise ImproperlyConfigured("DJANGO_SECRET_KEY must be configured when DEBUG=false.")

ALLOWED_HOSTS = env_list(
    "DJANGO_ALLOWED_HOSTS", "127.0.0.1,localhost" if DEBUG else ""
)
if not DEBUG and not ALLOWED_HOSTS:
    raise ImproperlyConfigured("DJANGO_ALLOWED_HOSTS must be configured when DEBUG=false.")

CORS_ALLOWED_ORIGINS = env_list(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:5173,http://127.0.0.1:5173" if DEBUG else "",
)
CSRF_TRUSTED_ORIGINS = env_list("CSRF_TRUSTED_ORIGINS")

def env_nonnegative_int(name, default=0):
    raw = os.getenv(name, str(default)).strip()
    try:
        value = int(raw)
    except ValueError as exc:
        raise ImproperlyConfigured(f"{name} must be a nonnegative integer.") from exc
    if value < 0:
        raise ImproperlyConfigured(f"{name} must be a nonnegative integer.")
    return value


# Django is behind a trusted HTTPS proxy on many hosts. Only trust a forwarded
# protocol header when the proxy is configured to strip client-supplied values.
if env_boolean("DJANGO_TRUST_PROXY_SSL_HEADER", False):
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")

# Enable redirect/HSTS only after HTTPS and proxy forwarding are verified.
SECURE_SSL_REDIRECT = env_boolean("DJANGO_SECURE_SSL_REDIRECT", False)
SECURE_HSTS_SECONDS = env_nonnegative_int("DJANGO_SECURE_HSTS_SECONDS", 0)
SECURE_HSTS_INCLUDE_SUBDOMAINS = env_boolean("DJANGO_SECURE_HSTS_INCLUDE_SUBDOMAINS", False)
SECURE_HSTS_PRELOAD = env_boolean("DJANGO_SECURE_HSTS_PRELOAD", False)
SESSION_COOKIE_SECURE = not DEBUG
CSRF_COOKIE_SECURE = not DEBUG


# Application definition

REST_FRAMEWORK = {
    # Do not trust client-supplied X-Forwarded-For headers by default.
    "NUM_PROXIES": env_nonnegative_int("DRF_NUM_PROXIES", 0),
    "DEFAULT_THROTTLE_RATES": {
        "routes_minute": os.getenv("ROUTES_RATE_PER_MINUTE", "6/min"),
        "routes_daily": os.getenv("ROUTES_RATE_PER_DAY", "80/day"),
    },
}

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',

    'rest_framework',
    'corsheaders',
    'routing',
]

MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'django.contrib.sessions.middleware.SessionMiddleware',
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

WSGI_APPLICATION = 'config.wsgi.application'


# Database
# https://docs.djangoproject.com/en/6.1/ref/settings/#databases

DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': BASE_DIR / 'db.sqlite3',
    }
}


# Password validation
# https://docs.djangoproject.com/en/6.1/ref/settings/#auth-password-validators

AUTH_PASSWORD_VALIDATORS = [
    {
        'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator',
    },
    {
        'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator',
    },
]


# Internationalization
# https://docs.djangoproject.com/en/6.1/topics/i18n/

LANGUAGE_CODE = 'en-us'

TIME_ZONE = 'UTC'

USE_I18N = True

USE_TZ = True


# Static files (CSS, JavaScript, Images)
# https://docs.djangoproject.com/en/6.1/howto/static-files/

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / "staticfiles"


# Email
# https://docs.djangoproject.com/en/6.1/topics/email/#topic-email-configuration

EMAIL_BACKEND = 'django.core.mail.backends.console.EmailBackend'

