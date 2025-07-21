import sys
from django.apps import AppConfig

class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'

    def ready(self):
        if any(cmd in sys.argv for cmd in ("runserver", "celery", "celerybeat")):
            try:
                from .startup import setup_email_polling
                setup_email_polling()
            except Exception:
                pass
