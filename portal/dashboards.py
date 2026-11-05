"""Dashboards diferenciados por perfil (Evaluación 3).

El Inicio muestra un panel distinto según el perfil autenticado. Los perfiles
de la pauta se cumplen con los roles del proyecto:

==================  =========================================  ====================
Panel (pauta)       Rol del SGR                                Alcance del rol
==================  =========================================  ====================
Administrador       Superadministrador (o superusuario)        all
Supervisor          Coordinador / Delegado municipal           authorized / own_delegation
Administrativo      Funcionario                                own_records
==================  =========================================  ====================

Todos los datos respetan el alcance del usuario (delegación activa y
registros propios) y los accesos salen de los permisos de Django
(``portal.access``): un panel nunca ofrece algo que el servidor rechazaría.
"""

from datetime import datetime, time

from django.db.models import Count, Q
from django.utils import timezone

from operaciones.models import Attention, Employee
from sgr_core.models import AttentionSubtype, AttentionType, Delegation, ProjectItem, Role

from . import access
from .models import AuditLog
from .modules import MODULE_DESCRIPTIONS, MODULE_ICONS, MODULE_LABELS, MODULE_ORDER, MODULE_URL_NAMES

PROFILE_ADMIN = "admin"
PROFILE_SUPERVISOR = "supervisor"
PROFILE_ADMINISTRATIVE = "administrativo"

#: Título del panel según el perfil (nombres de la pauta).
PROFILE_TITLES = {
    PROFILE_ADMIN: "Dashboard Administrador",
    PROFILE_SUPERVISOR: "Dashboard Supervisor",
    PROFILE_ADMINISTRATIVE: "Dashboard Administrativo",
}

PROFILE_LEVELS = {
    PROFILE_ADMIN: "Acceso total al sistema",
    PROFILE_SUPERVISOR: "Permisos intermedios",
    PROFILE_ADMINISTRATIVE: "Permisos mínimos",
}

#: Módulos que son mantenedores (CRUD de catálogos y cuentas).
MAINTAINERS = (
    "delegations", "roles", "users", "items", "attention_types", "attention_subtypes",
)
#: Módulos que son transacciones operacionales.
TRANSACTIONS = ("attentions",)

#: Acciones críticas que el perfil Administrativo no tiene.
CRITICAL_ACTIONS = ("edit", "delete")

ACTION_LABELS = {
    "view": "Ver", "create": "Crear", "edit": "Editar",
    "delete": "Eliminar", "export": "Exportar",
}

STATUS = Attention.AttentionStatus


def profile_for(role):
    """Perfil del panel según el alcance del rol."""
    if role is None:
        return None
    if role.scope == "all":
        return PROFILE_ADMIN
    if role.scope in ("authorized", "own_delegation"):
        return PROFILE_SUPERVISOR
    return PROFILE_ADMINISTRATIVE


def _module_card(info, module):
    actions = [
        label for action, label in ACTION_LABELS.items() if info.can(module, action)
    ]
    return {
        "key": module,
        "label": MODULE_LABELS[module],
        "description": MODULE_DESCRIPTIONS[module],
        "icon": MODULE_ICONS[module],
        "url_name": MODULE_URL_NAMES[module],
        "actions": actions,
        "can_create": info.can(module, "create"),
        "count": None,
    }


def _cards(info, modules):
    return [_module_card(info, module) for module in modules if info.can(module, "view")]


def _percent(part, total):
    return round(100 * part / total) if total else 0


def _status_summary(queryset):
    """Totales por estado en una sola consulta."""
    data = queryset.aggregate(
        total=Count("pk"),
        received=Count("pk", filter=Q(status=STATUS.RECEIVED)),
        in_progress=Count("pk", filter=Q(status=STATUS.IN_PROGRESS)),
        resolved=Count("pk", filter=Q(status=STATUS.RESOLVED)),
    )
    data["resolved_pct"] = _percent(data["resolved"], data["total"])
    data["bars"] = [
        {"label": "Ingresadas", "value": data["received"], "pct": _percent(data["received"], data["total"]), "tone": "info"},
        {"label": "En gestión", "value": data["in_progress"], "pct": _percent(data["in_progress"], data["total"]), "tone": "warning"},
        {"label": "Resueltas", "value": data["resolved"], "pct": _percent(data["resolved"], data["total"]), "tone": "success"},
    ]
    return data


def _recent(queryset, limit=6):
    return list(
        queryset.select_related(
            "neighbor", "attention_type", "attention_subtype", "delegation", "responsible",
        ).order_by("-created_at", "-pk")[:limit]
    )


def _by_delegation(queryset):
    rows = (
        queryset.values("delegation__code", "delegation__name", "delegation__color")
        .annotate(
            total=Count("pk"),
            in_progress=Count("pk", filter=Q(status=STATUS.IN_PROGRESS)),
            resolved=Count("pk", filter=Q(status=STATUS.RESOLVED)),
        )
        .order_by("delegation__code")
    )
    return [dict(row, resolved_pct=_percent(row["resolved"], row["total"])) for row in rows]


def _by_type(queryset, limit=5):
    rows = (
        queryset.values("attention_type__name")
        .annotate(total=Count("pk"))
        .order_by("-total", "attention_type__name")[:limit]
    )
    biggest = max((row["total"] for row in rows), default=0)
    return [dict(row, pct=_percent(row["total"], biggest)) for row in rows]


def _by_responsible(queryset, limit=6):
    rows = (
        queryset.values("responsible__first_name", "responsible__last_name", "responsible__username")
        .annotate(
            total=Count("pk"),
            in_progress=Count("pk", filter=Q(status=STATUS.IN_PROGRESS)),
            resolved=Count("pk", filter=Q(status=STATUS.RESOLVED)),
        )
        .order_by("-total")[:limit]
    )
    result = []
    for row in rows:
        name = f"{row['responsible__first_name']} {row['responsible__last_name']}".strip()
        result.append(dict(row, name=name or row["responsible__username"]))
    return result


def _today_count(queryset):
    start = timezone.make_aware(datetime.combine(timezone.localdate(), time.min))
    return queryset.filter(created_at__gte=start).count()


def build_dashboard(request, attentions):
    """Contexto del panel del usuario autenticado.

    ``attentions`` es el queryset de atenciones ya acotado por alcance y
    delegación activa (``home_views.attention_queryset_for``).
    """
    user = request.user
    info = access.get_access(request)
    profile = profile_for(info.role)
    summary = _status_summary(attentions)
    groups = list(user.groups.order_by("name").values_list("name", flat=True))

    context = {
        "profile": profile,
        "profile_title": PROFILE_TITLES.get(profile, "Inicio"),
        "profile_level": PROFILE_LEVELS.get(profile, ""),
        "user_groups": groups,
        "django_perm_count": (
            len(info.permissions) if info.permissions is not None else "todos"
        ),
        "summary": summary,
        "recent_attentions": _recent(attentions),
        "maintainer_cards": _cards(info, MAINTAINERS),
        "transaction_cards": _cards(info, TRANSACTIONS),
        "other_cards": _cards(info, [m for m in MODULE_ORDER if m not in MAINTAINERS + TRANSACTIONS]),
        "can_create_attention": info.can("attentions", "create"),
        "can_manage_users": info.can("users", "create"),
        "can_view_roles": info.can("roles", "view"),
    }

    if profile == PROFILE_ADMIN:
        counts = {
            "delegations": Delegation.alive.count(),
            "roles": Role.alive.count(),
            "users": Employee.alive.count(),
            "items": ProjectItem.alive.count(),
            "attention_types": AttentionType.alive.count(),
            "attention_subtypes": AttentionSubtype.alive.count(),
        }
        for card in context["maintainer_cards"]:
            card["count"] = counts.get(card["key"])
        context.update({
            "global_kpis": [
                {"label": "Usuarios activos", "value": access.visible_users(user).filter(is_active=True).count(), "icon": "users"},
                {"label": "Delegaciones activas", "value": Delegation.alive.filter(status="Activa").count(), "icon": "building"},
                {"label": "Roles / grupos", "value": Role.alive.count(), "icon": "shield"},
                {"label": "Atenciones registradas", "value": summary["total"], "icon": "clip"},
            ],

            "by_delegation": _by_delegation(attentions),
            "recent_audit": list(AuditLog.objects.select_related("user")[:8]),
        })
    elif profile == PROFILE_SUPERVISOR:
        context.update({
            "team_count": access.visible_users(user).filter(is_active=True).count(),
            "by_type": _by_type(attentions),
            "by_responsible": _by_responsible(attentions),
            "delegation_count": len(access.allowed_delegations(user)),
        })
    elif profile == PROFILE_ADMINISTRATIVE:
        context.update({
            "today_count": _today_count(attentions),
            "allowed_actions": [
                ACTION_LABELS[action] for action in ACTION_LABELS
                if info.can("attentions", action)
            ],
            "restricted_actions": [
                ACTION_LABELS[action] for action in CRITICAL_ACTIONS
                if not info.can("attentions", action)
            ],
            "restricted_modules": [
                MODULE_LABELS[m] for m in MAINTAINERS if not info.can(m, "view")
            ],
        })
    return context
