from pathlib import Path
from decouple import config, Csv 
import os

# Para suportar DATABASE_URL (Neon Database)
try:
    import dj_database_url
except ImportError:
    dj_database_url = None

BASE_DIR = Path(__file__).resolve().parent.parent

# Django settings
ROOT_URLCONF = 'backend.urls'
SECRET_KEY = config('DJANGO_SECRET_KEY') 
DEBUG = config('DJANGO_DEBUG', default=False, cast=bool) 
ALLOWED_HOSTS = config('DJANGO_ALLOWED_HOSTS', cast=Csv()) 

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

WSGI_APPLICATION = 'backend.wsgi.application'

# Apps instalados
INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    'channels',
    'django_celery_beat',
    'django_celery_results',
    "api.apps.ApiConfig",
    'corsheaders',
    'rest_framework',
    'social_django',
]

# Middleware
MIDDLEWARE = [
    'corsheaders.middleware.CorsMiddleware',
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',  # Para servir arquivos estáticos em produção
    'django.contrib.sessions.middleware.SessionMiddleware',
    'django.middleware.common.CommonMiddleware',
    'django.middleware.csrf.CsrfViewMiddleware',
    'django.contrib.auth.middleware.AuthenticationMiddleware',
    'django.contrib.messages.middleware.MessageMiddleware',
    'django.middleware.clickjacking.XFrameOptionsMiddleware',
    'social_django.middleware.SocialAuthExceptionMiddleware',
]

# Configurações de CORS
CORS_ALLOWED_ORIGINS = config('CORS_ALLOWED_ORIGINS', cast=Csv())
CORS_ALLOW_CREDENTIALS = True
AUTHENTICATION_BACKENDS = (
    'social_core.backends.google.GoogleOAuth2',
    'django.contrib.auth.backends.ModelBackend',
)

# Configuração para o Google OAuth2
SOCIAL_AUTH_GOOGLE_OAUTH2_KEY = config('SOCIAL_AUTH_GOOGLE_OAUTH2_KEY')
SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET = config('SOCIAL_AUTH_GOOGLE_OAUTH2_SECRET')
SOCIAL_AUTH_ALLOW_MULTIPLE_USERS = True
SOCIAL_AUTH_GOOGLE_OAUTH2_SCOPE = [
    'https://www.googleapis.com/auth/userinfo.email',
    'https://www.googleapis.com/auth/userinfo.profile',
    'openid',
    'https://www.googleapis.com/auth/gmail.readonly',
    'https://www.googleapis.com/auth/gmail.modify',
    'https://www.googleapis.com/auth/gmail.send',
]
SOCIAL_AUTH_GOOGLE_OAUTH2_EXTRA_DATA = ['refresh_token', 'access_token', 'expires']

SOCIAL_AUTH_LOGIN_REDIRECT_URL = config('SOCIAL_AUTH_LOGIN_REDIRECT_URL', default="http://localhost:3000/")
SOCIAL_AUTH_LOGIN_ERROR_URL = config('SOCIAL_AUTH_LOGIN_ERROR_URL', default="http://localhost:3000/")
LOGOUT_REDIRECT_URL = '/'
SOCIAL_AUTH_GOOGLE_OAUTH2_AUTH_EXTRA_ARGUMENTS = {
    'access_type': 'offline',
    'prompt': 'consent',
}
SOCIAL_AUTH_PIPELINE = (
    'social_core.pipeline.social_auth.social_details',
    'social_core.pipeline.social_auth.social_uid',   
    'api.pipeline.prevent_duplicate_social_auth',   
    'social_core.pipeline.user.get_username',
    'social_core.pipeline.user.create_user',
    'social_core.pipeline.social_auth.associate_user',
    'social_core.pipeline.social_auth.load_extra_data',
    'api.pipeline.save_email_to_extra_data',
    'social_core.pipeline.user.user_details',
)

SOCIAL_AUTH_GOOGLE_OAUTH2_IGNORE_DEFAULT_SCOPE = True

CSRF_TRUSTED_ORIGINS = config('CSRF_TRUSTED_ORIGINS', cast=Csv())

# Configurações do banco de dados
# Suporta DATABASE_URL (Neon Database), variáveis individuais (PostgreSQL tradicional) ou SQLite (desenvolvimento)
DATABASE_URL = config('DATABASE_URL', default=None)

if DATABASE_URL and dj_database_url:
    # Usa DATABASE_URL (Neon Database ou outros serviços que fornecem connection string)
    DATABASES = {
        'default': dj_database_url.parse(DATABASE_URL, conn_max_age=600)
    }
elif config('DB_NAME', default=None):
    # Usa variáveis individuais (PostgreSQL tradicional no Render)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.postgresql',
            'NAME': config('DB_NAME'),
            'USER': config('DB_USER'),
            'PASSWORD': config('DB_PASSWORD'),
            'HOST': config('DB_HOST'),
            'PORT': config('DB_PORT', default='5432'),
        }
    }
else:
    # Fallback para SQLite (desenvolvimento local)
    DATABASES = {
        'default': {
            'ENGINE': 'django.db.backends.sqlite3',  
            'NAME': BASE_DIR / 'db.sqlite3',  
        }
    }


# Celery Settings
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default="redis://localhost:6379/0")
CELERY_BEAT_SCHEDULE = {
    "pull-gmail-notifications-every-5s": {
        "task": "api.tasks.pull_pubsub_messages",
        "schedule": 5.0,
    }
}

# Google Cloud Settings
GCLOUD_PROJECT = config('GCLOUD_PROJECT')
PUBSUB_SUBSCRIPTION_ID = config('PUBSUB_SUBSCRIPTION_ID')
GMAIL_PUBSUB_TOPIC = config('GMAIL_PUBSUB_TOPIC')

# Canal para WebSockets
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels_redis.core.RedisChannelLayer",
        "CONFIG": {
            "hosts": [(config('REDIS_HOST', default='127.0.0.1'), config('REDIS_PORT', default=6379, cast=int))],
        },
    },
}

ASGI_APPLICATION = "backend.asgi.application"

# Outras configurações como timezone, etc.
LANGUAGE_CODE = 'en-us'
TIME_ZONE = 'UTC'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'

# WhiteNoise para servir arquivos estáticos em produção
STATICFILES_STORAGE = 'whitenoise.storage.CompressedManifestStaticFilesStorage'

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# Definição do Celery e Broker
CELERY_BROKER_URL = config('CELERY_BROKER_URL', default="redis://localhost:6379/0")
CELERY_BEAT_SCHEDULER = "django_celery_beat.schedulers:DatabaseScheduler"

REST_FRAMEWORK = {
    'DEFAULT_AUTHENTICATION_CLASSES': [
        'rest_framework.authentication.SessionAuthentication',
        'rest_framework.authentication.TokenAuthentication',  
    ],
    'DEFAULT_PERMISSION_CLASSES': [
        'rest_framework.permissions.IsAuthenticated', 
    ],
}
