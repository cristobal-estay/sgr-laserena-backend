from django.apps import AppConfig

class OperacionesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'operaciones'
    verbose_name = 'Operaciones Territoriales y Evidencias'

    def ready(self):
        from . import signals  # noqa: F401  (usuario -> grupo de su rol)
