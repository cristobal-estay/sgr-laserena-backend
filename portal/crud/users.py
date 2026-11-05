"""Configuración del mantenedor de Usuarios (Parte 5, Etapa 2).

Solo la declara: el motor (``portal.crud.views``) hace todo el trabajo. El
listado se acota con :func:`users_scope` (misma regla de rango + delegación que
``portal.access.visible_users``) y el borrado nunca es físico: el guard impide
eliminar al único superusuario y el modelo desactiva la cuenta.
"""

from ..access import get_role
from ..access import allowed_delegations
from sgr_core.roles import SCOPE_RANKS
from operaciones.models import Employee

from .config import CELL_STATUS, CELL_DELEGATION, ColumnSpec, ModuleConfig, register_module
from .forms import UserForm


def users_scope(request, queryset):
    """Usuarios visibles para el operador (mismo criterio que ``visible_users``).

    - Superusuario ve a todos (incluidos otros superusuarios).
    - Un superusuario NUNCA es visible para quien no es superusuario.
    - El resto ve solo usuarios de menor rango, con rol Activo, sin rol de
      sistema virtual y cuya delegación base esté entre las permitidas.
    """
    role = get_role(request.user)
    if role is None:
        return queryset.none()
    if getattr(request.user, "is_superuser", False):
        return queryset
    delegations = allowed_delegations(request.user)
    if not delegations:
        return queryset.none()
    lower_scopes = [
        scope for scope, rank in SCOPE_RANKS.items() if rank < role.rank
    ]
    if not lower_scopes:
        return queryset.none()
    return queryset.filter(
        user__is_superuser=False,
        delegation_id__in=[delegation.pk for delegation in delegations],
        role__scope__in=lower_scopes,
        role__status="Activo",
    ).distinct()


def user_delete_guard(employee, request=None):
    """Bloquea el borrado del propio operador o del último superusuario.

    El borrado es lógico (nunca físico) y desactiva la cuenta; aquí solo se
    impiden los casos que dejarían el sistema sin acceso. Devuelve el mensaje a
    mostrar o cadena vacía si se puede eliminar.
    """
    if request is not None and request.user.pk == employee.user_id:
        return "No puedes eliminar tu propio usuario."
    if employee.user.is_superuser:
        otros = Employee.objects.filter(
            user__is_superuser=True, deleted_at__isnull=True
        ).exclude(pk=employee.pk).count()
        if otros == 0:
            return (
                "No se puede eliminar el último usuario administrador del "
                "sistema. Crea otro administrador antes de eliminarlo."
            )
    return ""


USERS_MODULE = ModuleConfig(
    module_key="users",
    slug="usuarios",
    model=Employee,
    form_class=UserForm,
    list_title="Usuarios",
    singular_label="Usuario",
    columns=(
        ColumnSpec("rut", "RUT"),
        ColumnSpec("full_name", "Nombre"),
        ColumnSpec("email", "Correo"),
        ColumnSpec("role_code", "Rol"),
        ColumnSpec("delegations", "Delegaciones", cell=CELL_DELEGATION),
        ColumnSpec("status_label", "Estado", cell=CELL_STATUS),
        ColumnSpec("group_label", "Grupo de Django"),
    ),
    search_fields=(
        "rut", "user__first_name", "user__last_name", "user__email",
        "user__username", "role__name", "role__code", "delegation__name",
        "delegation__code",
    ),
    status_field=None,
    status_options=(),
    ordering=("user__first_name", "user__last_name", "rut"),
    scope=users_scope,
    delete_guard=user_delete_guard,
    form_template="portal/crud/users_form.html",
)

register_module(USERS_MODULE)
