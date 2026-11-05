"""Grupos y permisos de Django ligados a los roles del SGR (Evaluación 3).

Cada rol del sistema (Superadministrador, Coordinador, Delegado municipal,
Funcionario...) tiene su propio ``auth.Group`` de Django y cada casilla de la
matriz de permisos del rol (módulo × acción) es un ``auth.Permission`` real:

- Permiso ``sgr_core.<accion>_<modulo>``, por ejemplo ``sgr_core.create_attentions``
  ("Atenciones: Crear") o ``sgr_core.export_users`` ("Usuarios: Exportar").
- El grupo del rol se llama ``"<código> · <nombre>"`` (``"ROL02 · Coordinador"``)
  y recibe exactamente los permisos marcados en la matriz.
- Cada usuario queda dentro del grupo de su rol; al cambiarle el rol, cambia
  de grupo.

El portal valida los accesos con ``user.has_perm(...)`` (ver
``portal.access``), así que la autorización usa el sistema de permisos y
grupos de Django. La matriz de la pantalla Roles sigue siendo el lugar donde
se editan los permisos: cada cambio se sincroniza con el grupo (señales en
``sgr_core.signals``).

Las funciones reciben las clases de modelo como argumentos opcionales para
poder usarse también desde migraciones de datos (modelos históricos).
"""

from .roles import ACTIONS, MODULES

#: App y modelo dueños de los permisos por módulo (``sgr_core.rolepermission``).
PERMISSION_APP_LABEL = "sgr_core"
PERMISSION_MODEL = "rolepermission"

MODULE_LABELS = dict(MODULES)
ACTION_LABELS = dict(ACTIONS)


def permission_codename(module, action):
    """Codename del permiso de Django: ``create_attentions``."""
    return f"{action}_{module}"


def permission_label(module, action):
    """Nombre legible: ``Atenciones: Crear``."""
    return f"{MODULE_LABELS.get(module, module)}: {ACTION_LABELS.get(action, action)}"


def permission_string(module, action):
    """Permiso completo para ``user.has_perm``: ``sgr_core.create_attentions``."""
    return f"{PERMISSION_APP_LABEL}.{permission_codename(module, action)}"


#: codename -> (módulo, acción), para traducir los permisos de Django de vuelta.
CODENAME_TO_PAIR = {
    permission_codename(module, action): (module, action)
    for module, _ in MODULES
    for action, _ in ACTIONS
}


def group_name(role):
    """Nombre del grupo de Django de un rol: ``ROL02 · Coordinador``."""
    return f"{role.code} · {role.name}"[:150]


def _auth_models(group_cls=None, permission_cls=None, contenttype_cls=None):
    """Clases reales de Django para lo que no venga como argumento."""
    if group_cls is None or permission_cls is None or contenttype_cls is None:
        from django.contrib.auth.models import Group, Permission
        from django.contrib.contenttypes.models import ContentType

        group_cls = group_cls or Group
        permission_cls = permission_cls or Permission
        contenttype_cls = contenttype_cls or ContentType
    return group_cls, permission_cls, contenttype_cls


def ensure_module_permissions(permission_cls=None, contenttype_cls=None):
    """Crea (idempotente) los 55 permisos módulo × acción y los devuelve.

    Devuelve un diccionario ``(módulo, acción) -> Permission``.
    """
    _, permission_cls, contenttype_cls = _auth_models(
        permission_cls=permission_cls, contenttype_cls=contenttype_cls,
    )
    content_type, _ = contenttype_cls.objects.get_or_create(
        app_label=PERMISSION_APP_LABEL, model=PERMISSION_MODEL,
    )
    existing = {
        perm.codename: perm
        for perm in permission_cls.objects.filter(content_type=content_type)
    }
    result = {}
    for module, _ in MODULES:
        for action, _ in ACTIONS:
            codename = permission_codename(module, action)
            perm = existing.get(codename)
            label = permission_label(module, action)
            if perm is None:
                perm = permission_cls.objects.create(
                    content_type=content_type, codename=codename, name=label,
                )
            elif perm.name != label:
                perm.name = label
                perm.save(update_fields=["name"])
            result[(module, action)] = perm
    return result


def sync_role_group(role, rolepermission_cls=None, group_cls=None,
                    permission_cls=None, contenttype_cls=None):
    """Crea o actualiza el grupo del rol y le asigna los permisos de su matriz.

    Devuelve el ``Group``. Guarda ``role.group`` con ``update()`` para no
    volver a disparar las señales de ``Role``.
    """
    group_cls, permission_cls, contenttype_cls = _auth_models(
        group_cls, permission_cls, contenttype_cls,
    )
    if rolepermission_cls is None:
        from .models import RolePermission as rolepermission_cls

    perms = ensure_module_permissions(permission_cls, contenttype_cls)
    name = group_name(role)

    group = None
    if role.group_id:
        group = group_cls.objects.filter(pk=role.group_id).first()
    if group is None:
        group, _ = group_cls.objects.get_or_create(name=name)
    elif group.name != name:
        clash = group_cls.objects.filter(name=name).exclude(pk=group.pk).exists()
        if not clash:
            group.name = name
            group.save(update_fields=["name"])

    pairs = rolepermission_cls.objects.filter(role_id=role.pk).values_list("module", "action")
    group.permissions.set([perms[pair] for pair in pairs if pair in perms])

    if role.group_id != group.pk:
        type(role).objects.filter(pk=role.pk).update(group=group)
        role.group_id = group.pk
    return group


def sync_user_groups(user, role, group_cls=None):
    """Deja al usuario en el grupo de su rol (y fuera de los grupos de otros roles).

    Los grupos que no son de un rol (creados a mano) no se tocan. Con
    ``role=None`` el usuario sale de todos los grupos de rol.
    """
    group_cls, _, _ = _auth_models(group_cls=group_cls)
    role_groups = group_cls.objects.filter(sgr_role__isnull=False)
    target_id = getattr(role, "group_id", None) if role is not None else None
    stale = role_groups.exclude(pk=target_id) if target_id else role_groups
    stale_ids = list(stale.filter(user=user).values_list("pk", flat=True))
    if stale_ids:
        user.groups.remove(*stale_ids)
    if target_id and not user.groups.filter(pk=target_id).exists():
        user.groups.add(target_id)
