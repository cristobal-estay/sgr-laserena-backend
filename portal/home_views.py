"""Vistas del shell (Parte 3: Inicio, cambio de delegación y placeholders)."""
from django.contrib import messages
from django.contrib.auth.mixins import LoginRequiredMixin
from django.shortcuts import redirect
from django.views import View
from django.views.generic import TemplateView

from operaciones.models import Attention
from sgr_core.roles import ACTIONS

from . import access
from .access import ModulePermissionMixin
from .dashboards import build_dashboard
from .modules import MODULE_DESCRIPTIONS, MODULE_ICONS, MODULE_LABELS, MODULE_ORDER, MODULE_URL_NAMES

#: Etiquetas ES de las acciones (para "Puedes: ..." del Inicio).
ACTION_LABELS = dict(ACTIONS)

#: Alcance en minúsculas para el texto del Inicio.
SCOPE_TEXT = {
    "all": "todas las delegaciones",
    "authorized": "delegaciones autorizadas",
    "own_delegation": "su delegación",
    "own_records": "solo registros propios",
}


def attention_queryset_for(user, active):
    """Atenciones visibles según rol + delegación activa (conteos del Inicio)."""
    role = access.get_role(user)
    if role is None:
        return Attention.objects.none()
    queryset = Attention.objects.all()
    if active is not None and active != access.ALL_DELEGATIONS:
        queryset = queryset.filter(delegation_id=active.pk)
    if role.scope == "own_records":
        queryset = queryset.filter(responsible_id=user.pk)
    return queryset


class HomeView(LoginRequiredMixin, TemplateView):
    """Inicio = dashboard del perfil (Administrador, Supervisor o Administrativo).

    Ver ``portal.dashboards``: cada perfil ve cifras, accesos y listados
    distintos, siempre dentro de su alcance y de sus permisos de Django.
    """

    template_name = "portal/home.html"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        user = self.request.user
        info = access.get_access(self.request)
        active = access.get_active_delegation(self.request)

        attentions = attention_queryset_for(user, active)
        registered = attentions.count()
        in_progress = attentions.filter(status=Attention.AttentionStatus.IN_PROGRESS).count()

        if info.can("users", "view"):
            third_label = "Usuarios activos"
            third_value = access.visible_users(user).filter(is_active=True).count()
        else:
            third_label = "Atenciones resueltas"
            third_value = attentions.filter(status=Attention.AttentionStatus.RESOLVED).count()

        cards = []
        for module in MODULE_ORDER:
            if not info.can(module, "view"):
                continue
            actions = [
                ACTION_LABELS.get(action, action)
                for module_key, action in sorted(info.permissions or [])
                if module_key == module
            ] if info.permissions is not None else [label for _, label in ACTIONS]
            cards.append({
                "key": module,
                "label": MODULE_LABELS[module],
                "description": MODULE_DESCRIPTIONS[module],
                "icon": MODULE_ICONS[module],
                "url_name": MODULE_URL_NAMES[module],
                "actions": ", ".join(actions).lower(),
            })
        hidden = [MODULE_LABELS[m] for m in MODULE_ORDER if not info.can(m, "view")]

        if active == access.ALL_DELEGATIONS:
            context_text = "Ves todas las delegaciones."
        elif active is not None:
            context_text = f"Delegación activa: {active.code} | Delegación {active.name}."
        else:
            context_text = ""

        full_name = user.get_full_name() or user.username
        context.update({
            "active_module": "home",
            "first_name": full_name.split()[0],
            "context_text": context_text,
            "scope_text": SCOPE_TEXT.get(info.role.scope, "") if info.role else "",
            "stat_registered": registered,
            "stat_in_progress": in_progress,
            "stat_third_label": third_label,
            "stat_third_value": third_value,
            "cards": cards,
            "hidden_labels": ", ".join(hidden),
        })
        context.update(build_dashboard(self.request, attentions))
        return context


class SwitchDelegationView(LoginRequiredMixin, View):
    """Cambia la delegación activa solo por POST (validada en el servidor)."""

    def post(self, request):
        value = request.POST.get("delegation", "")
        if access.set_active_delegation(request, value):
            active = access.get_active_delegation(request)
            if active == access.ALL_DELEGATIONS:
                messages.success(request, "Delegación activa: todas las delegaciones.")
            elif active is not None:
                messages.success(
                    request,
                    f"Delegación activa: {active.code} | Delegación {active.name}.",
                )
        else:
            messages.error(request, "La delegación seleccionada no es válida para tu perfil.")
        return redirect("home")


class ModulePlaceholderView(LoginRequiredMixin, ModulePermissionMixin, TemplateView):
    """Página provisional 'Módulo en construcción' (ancla Partes 4 a 7)."""

    template_name = "portal/under_construction.html"
    module = None
    action = "view"

    def get_context_data(self, **kwargs):
        context = super().get_context_data(**kwargs)
        context.update({
            "active_module": self.module,
            "module_label": MODULE_LABELS.get(self.module, ""),
            "module_icon": MODULE_ICONS.get(self.module, "info"),
        })
        return context
