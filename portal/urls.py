from django.urls import include, path
from django.views.generic import RedirectView

from .crud import registered_modules
from .home_views import HomeView, ModulePlaceholderView, SwitchDelegationView
from .modules import MODULE_ORDER
from .views import (
    PortalLoginView,
    PortalLogoutView,
    PasswordResetRequestView,
    PasswordResetSentView,
    PasswordResetResendView,
    PasswordResetLinkView,
    PasswordResetConfirmView,
    PasswordResetCompleteView,
)


def _placeholder_kwargs(module):
    return {"module": module}


_placeholder_paths = {
    "goals": "metas-institucionales/",
    "tasks": "agenda-tareas/",
    "achievements": "cumplimiento/",
    "reports": "reportes/",
}

#: Módulos que ya tienen CRUD real (Parte 4+): los gestiona portal.crud.urls.
_crud_modules = {module.module_key for module in registered_modules()}

urlpatterns = [
    path('', PortalLoginView.as_view(), name='login'),
    path('login/', PortalLoginView.as_view(), name='login'),
    path('logout/', PortalLogoutView.as_view(), name='logout'),
    path('inicio/', HomeView.as_view(), name='home'),
    path('delegacion-activa/', SwitchDelegationView.as_view(), name='switch_delegation'),
    path('dashboard/', RedirectView.as_view(pattern_name='home', permanent=False), name='dashboard'),
    # Recuperación de contraseña con enlace + token seguro (Evaluación 3).
    path('recuperar/', PasswordResetRequestView.as_view(), name='password_reset_request'),
    path('recuperar/enviado/', PasswordResetSentView.as_view(), name='password_reset_sent'),
    path('recuperar/reenviar/', PasswordResetResendView.as_view(), name='password_reset_resend'),
    path('recuperar/enlace/<uidb64>/<token>/', PasswordResetLinkView.as_view(), name='password_reset_link'),
    path('recuperar/nueva-clave/', PasswordResetConfirmView.as_view(), name='password_reset_confirm'),
    path('recuperar/listo/', PasswordResetCompleteView.as_view(), name='password_reset_complete'),
    # Motor de mantenedores (delegaciones por ahora; Partes 5 a 7 lo usan).
    path('', include('portal.crud.urls')),
]

for _module in MODULE_ORDER:
    if _module in _crud_modules or _module not in _placeholder_paths:
        continue
    urlpatterns.append(
        path(
            _placeholder_paths[_module],
            ModulePlaceholderView.as_view(**_placeholder_kwargs(_module)),
            name=_module,
        )
    )
