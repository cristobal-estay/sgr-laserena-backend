from django.apps import AppConfig

class SgrCoreConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'sgr_core'
    verbose_name = 'Metas y Cumplimiento Institucional'

    def ready(self):
        from . import signals  # noqa: F401  (grupos de Django por rol)
