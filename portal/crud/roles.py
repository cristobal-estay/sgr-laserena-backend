"""Configuración del mantenedor de Roles (Parte 5).

Solo la declara: el motor (``portal.crud.views``) hace todo el trabajo.
"""

from operaciones.models import Employee
from sgr_core.models import Role

from .config import CELL_STATUS, ColumnSpec, ModuleConfig, register_module
from .forms import RoleForm


def role_delete_guard(role, request=None):
    """Bloquea el borrado si el rol es del sistema o tiene usuarios asignados.

    Devuelve el mensaje a mostrar o cadena vacía si se puede eliminar. El
    mensaje nunca sugiere desactivar: sugiere reasignar los usuarios.
    """
    if role.is_system:
        return (
            f"No se puede eliminar el rol {role.name}: es el perfil base del "
            f"sistema y solo se puede consultar."
        )
    users = Employee.objects.filter(role=role).count()
    if users:
        return (
            f"No se puede eliminar el rol {role.name} porque tiene {users} "
            f"usuario(s) asignado(s). Reasínalos a otro perfil antes de eliminarlo."
        )
    return ""


ROLES_MODULE = ModuleConfig(
    module_key="roles",
    slug="roles",
    model=Role,
    form_class=RoleForm,
    list_title="Roles",
    singular_label="Rol",
    columns=(
        ColumnSpec("code", "Código"),
        ColumnSpec("name", "Rol"),
        ColumnSpec("scope_label", "Alcance"),
        ColumnSpec("enabled_modules_count", "Módulos habilitados"),
        ColumnSpec("status", "Estado", cell=CELL_STATUS),
        ColumnSpec("group_label", "Grupo de Django"),
    ),
    search_fields=("code", "name", "scope"),
    status_field="status",
    status_options=(("Activo", "Activo"), ("Inactivo", "Inactivo")),
    ordering=("code",),
    delete_guard=role_delete_guard,
)

register_module(ROLES_MODULE)
