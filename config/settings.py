import os
import sys
from pathlib import Path
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent

load_dotenv(os.path.join(BASE_DIR, '.env'))

SECRET_KEY = os.getenv('DJANGO_SECRET_KEY', 'django-insecure-municipalidad-laserena-sgr-2026-key')

# Los tests usan un hasher de contraseñas rápido: el PBKDF2 por defecto hace que
# la suite (que crea decenas de usuarios demo) tarde minutos. En producción y
# desarrollo se conserva el hasher seguro por defecto.
if 'test' in sys.argv:
    PASSWORD_HASHERS = ['django.contrib.auth.hashers.MD5PasswordHasher']

DEBUG = os.getenv('DEBUG', 'True') == 'True'

ALLOWED_HOSTS = [host.strip() for host in os.getenv('ALLOWED_HOSTS', 'localhost,127.0.0.1').split(',')]

INSTALLED_APPS = [
    'django.contrib.admin',
    'django.contrib.auth',
    'django.contrib.contenttypes',
    'django.contrib.sessions',
    'django.contrib.messages',
    'django.contrib.staticfiles',
    # Aplicaciones del dominio SGR
    'sgr_core.apps.SgrCoreConfig',
    'operaciones.apps.OperacionesConfig',
    'portal.apps.PortalConfig',
    'anymail',
]

MIDDLEWARE = [
    'django.middleware.security.SecurityMiddleware',
    'whitenoise.middleware.WhiteNoiseMiddleware',
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
                'django.template.context_processors.debug',
                'django.template.context_processors.request',
                'django.contrib.auth.context_processors.auth',
                'django.contrib.messages.context_processors.messages',
                'portal.context_processors.sgr_context',
            ],
        },
    },
]

WSGI_APPLICATION = 'config.wsgi.application'

# Base de datos configurable vía variables de entorno (.env).
# Por defecto SQLite; para otro motor basta con definir DB_ENGINE y sus parámetros.
DB_ENGINE = os.getenv('DB_ENGINE', 'django.db.backends.sqlite3')

if DB_ENGINE == 'django.db.backends.sqlite3':
    _db_name = Path(os.getenv('DB_NAME') or 'db.sqlite3')
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': _db_name if _db_name.is_absolute() else BASE_DIR / _db_name,
        }
    }
else:
    DATABASES = {
        'default': {
            'ENGINE': DB_ENGINE,
            'NAME': os.getenv('DB_NAME', ''),
            'USER': os.getenv('DB_USER', ''),
            'PASSWORD': os.getenv('DB_PASSWORD', ''),
            'HOST': os.getenv('DB_HOST', ''),
            'PORT': os.getenv('DB_PORT', ''),
            # Conjunto de caracteres completo (tildes, eñes, emojis) en MariaDB/MySQL.
            'OPTIONS': {'charset': 'utf8mb4'},
        }
    }

AUTH_PASSWORD_VALIDATORS = [
    {'NAME': 'django.contrib.auth.password_validation.UserAttributeSimilarityValidator'},
    {'NAME': 'django.contrib.auth.password_validation.MinimumLengthValidator'},
    {'NAME': 'django.contrib.auth.password_validation.CommonPasswordValidator'},
    {'NAME': 'django.contrib.auth.password_validation.NumericPasswordValidator'},
]

LANGUAGE_CODE = 'es-cl'
TIME_ZONE = 'America/Santiago'
USE_I18N = True
USE_TZ = True

STATIC_URL = 'static/'
STATIC_ROOT = BASE_DIR / 'staticfiles'
STATICFILES_DIRS = []

# Archivos subidos por los usuarios (imagenes y documentos de las atenciones).
MEDIA_URL = '/media/'
MEDIA_ROOT = BASE_DIR / 'media'

STORAGES = {
    'default': {
        'BACKEND': 'django.core.files.storage.FileSystemStorage',
    },
    'staticfiles': {
        'BACKEND': 'whitenoise.storage.CompressedManifestStaticFilesStorage',
    },
}

DEFAULT_AUTO_FIELD = 'django.db.models.BigAutoField'

# --- Email ---------------------------------------------------------------
EMAIL_BACKEND = os.getenv('EMAIL_BACKEND', 'django.core.mail.backends.console.EmailBackend')
EMAIL_HOST = os.getenv('EMAIL_HOST', '')
EMAIL_PORT = int(os.getenv('EMAIL_PORT', '587'))
EMAIL_HOST_USER = os.getenv('EMAIL_HOST_USER', '')
EMAIL_HOST_PASSWORD = os.getenv('EMAIL_HOST_PASSWORD', '')
EMAIL_USE_TLS = os.getenv('EMAIL_USE_TLS', 'True') == 'True'
DEFAULT_FROM_EMAIL = os.getenv('DEFAULT_FROM_EMAIL', 'no-reply@sgr.municipalidadla-serena.cl')

# Mailtrap Sending API (requiere django-anymail). El token se lee desde el .env
# local; nunca se hardcodea ni se sube a GitHub. Si EMAIL_BACKEND es
# anymail.backends.mailtrap.EmailBackend y no hay token, Anymail fallará al
# intentar enviar (el error queda en el log del servidor).
ANYMAIL = {
    'MAILTRAP_API_TOKEN': os.getenv('MAILTRAP_API_TOKEN', ''),
}

# --- Autenticación --------------------------------------------------------
AUTHENTICATION_BACKENDS = [
    'portal.backends.EmailOrUsernameBackend',
    'django.contrib.auth.backends.ModelBackend',
]

# Recuperación de contraseña: vigencia del código en SEGUNDOS y cantidad máxima
# de intentos fallidos antes de invalidarlo. Configurables vía .env.
PASSWORD_RESET_CODE_TTL = int(os.getenv('PASSWORD_RESET_CODE_TTL', '120'))
PASSWORD_RESET_MAX_ATTEMPTS = int(os.getenv('PASSWORD_RESET_MAX_ATTEMPTS', '5'))

# --- Seguridad (cabeceras y cookies) -------------------------------------
# X-Frame-Options lo envía XFrameOptionsMiddleware (DENY por defecto).
# X-Content-Type-Options: nosniff.
SECURE_CONTENT_TYPE_NOSNIFF = True
# La cookie de sesión no debe ser legible por JavaScript.
SESSION_COOKIE_HTTPONLY = True
# El servidor de pruebas/despliegue actual sirve por HTTP: no se activan
# SESSION_COOKIE_SECURE ni SECURE_SSL_REDIRECT. Actívalos solo al pasar a HTTPS.

# --- Rutas de autenticación -----------------------------------------------
LOGIN_URL = 'login'
LOGIN_REDIRECT_URL = 'dashboard'
LOGOUT_REDIRECT_URL = 'login'
