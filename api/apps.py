import sys
from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'api'
    def ready(self):
        # Evita rodar durante migrações ou quando não for o servidor/celery
        if any(cmd in sys.argv for cmd in ("runserver", "celery", "celerybeat")):
            try:
                from .startup import setup_email_polling
                setup_email_polling()
            except Exception:
                # no-op: se o banco ainda não existir ou tabela não estiver criada
                pass
