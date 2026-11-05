from django.conf import settings
from django.conf.urls.static import static
from django.urls import include, path

handler403 = "portal.error_views.error_403"
handler404 = "portal.error_views.error_404"
handler500 = "portal.error_views.error_500"

# Evaluación 3: el sistema ya NO usa Django Admin. Toda la administración
# (usuarios, grupos/roles, permisos, mantenedores y atenciones) se hace desde
# el portal con Django Templates; /admin/ responde 404.
urlpatterns = [
    path('', include('portal.urls')),
]

# Solo en desarrollo: Django sirve los archivos subidos (MEDIA).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
