from django.conf import settings
from django.conf.urls.static import static
from django.contrib import admin
from django.urls import include, path

admin.site.site_header = "SGR Municipalidad de La Serena"
admin.site.site_title = "Portal de Administración SGR"
admin.site.index_title = "Gestión de Resultados y Control Territorial"

handler403 = "portal.error_views.error_403"
handler404 = "portal.error_views.error_404"
handler500 = "portal.error_views.error_500"

urlpatterns = [
    path('admin/', admin.site.urls),
    path('', include('portal.urls')),
]

# Solo en desarrollo: Django sirve los archivos subidos (MEDIA).
if settings.DEBUG:
    urlpatterns += static(settings.MEDIA_URL, document_root=settings.MEDIA_ROOT)
