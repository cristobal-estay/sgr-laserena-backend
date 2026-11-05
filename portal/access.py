"""Módulo único de autorización del SGR.

Todas las decisiones de "quién puede ver o hacer qué" se resuelven aquí:

- ``get_role(user)``: rol de acceso del usuario (o ``None`` sin acceso).
- ``has_permission(user, module, action)``: permiso puntual.
- ``allowed_delegations(user)``: delegaciones que el usuario puede gestionar.
- ``get_active_delegation`` / ``set_active_delegation``: delegación activa
  en sesión, validada contra las delegaciones permitidas.
- ``visible_users(user)``: regla de rango + delegaciones del contexto activo.
- ``can_assign_role(user, role)``: regla de rango para asignar roles.
- ``ModulePermissionMixin`` / ``permission_required``: bloquean con 403.

Los permisos se resuelven UNA vez por request (cache en la request misma,
nunca a nivel de proceso) para no consultar de más.

Evaluación 3: los permisos se leen desde el **sistema de permisos y grupos de
Django**. Cada rol tiene un ``auth.Group`` con un ``auth.Permission`` por cada
casilla de su matriz (``sgr_core.<accion>_<modulo>``) y el usuario pertenece
al grupo de su rol (ver ``sgr_core.groups``). Aquí se consulta con
``user.has_perm`` / ``user.get_all_permissions``; el rol solo aporta el
alcance de datos (delegaciones) y si está Activo.
"""
from dataclasses import dataclass
from functools import wraps

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied

from sgr_core.groups import CODENAME_TO_PAIR, PERMISSION_APP_LABEL, permission_string
from sgr_core.models import Delegation, Role
from sgr_core.roles import SCOPE_RANKS

from .audit import audit

User = get_user_model()

ACTIVE_DELEGATION_KEY = 'active_delegation'

ALL_DELEGATIONS = 'ALL'


@dataclass(frozen=True)
class AccessRole:
    """Rol de acceso resuelto (modelo real o virtual de superusuario)."""
    code: str
    name: str
    scope: str
    status: str
    is_system: bool = False
    is_virtual: bool = False   # superusuario sin Employee
    pk: int | None = None

    @property
    def rank(self):
        return SCOPE_RANKS.get(self.scope, 0)


def get_role(user):
    """Rol de acceso activo del usuario o None si no tiene acceso.

    - Superusuario -> rol virtual de superadministrador (rank 3, todos los
      permisos), aunque no tenga Employee.
    - Sin Employee y sin ser superusuario -> sin acceso.
    - Rol Inactivo -> sin acceso.
    """
    if user is None or not user.is_authenticated:
        return None
    if user.is_superuser:
        return AccessRole(
            code='VIRTUAL', name='Superadministrador', scope='all',
            status='Activo', is_system=True, is_virtual=True,
        )
    employee = getattr(user, 'employee', None)
    if employee is None or employee.role_id is None:
        return None
    role = employee.role
    if role.status != 'Activo':
        return None
    return AccessRole(
        pk=role.pk, code=role.code, name=role.name, scope=role.scope,
        status=role.status, is_system=role.is_system,
    )


def has_permission(user, module, action):
    """True si el usuario tiene el permiso (módulo, acción).

    Exige un rol Activo y luego pregunta a Django: ``user.has_perm``
    (permisos del grupo del rol y permisos directos del usuario).
    """
    role = get_role(user)
    if role is None:
        return False
    if role.is_virtual:
        return True
    return user.has_perm(permission_string(module, action))


def module_permissions(user):
    """Pares ``(módulo, acción)`` que Django le concede al usuario."""
    pairs = set()
    for perm in user.get_all_permissions():
        app_label, _, codename = perm.partition('.')
        if app_label == PERMISSION_APP_LABEL and codename in CODENAME_TO_PAIR:
            pairs.add(CODENAME_TO_PAIR[codename])
    return frozenset(pairs)


def allowed_delegations(user):
    """Delegaciones que el usuario puede gestionar (lista de Delegation)."""
    role = get_role(user)
    if role is None:
        return []
    if role.is_virtual:
        return list(Delegation.objects.filter(status='Activa', deleted_at__isnull=True).order_by('name'))
    employee = getattr(user, 'employee', None)
    if employee is None:
        return []
    return employee.allowed_delegations()


# ============================================================
# Delegación activa en sesión
# ============================================================

def _default_active_delegation(role, allowed):
    if role.scope == 'all':
        return ALL_DELEGATIONS
    return allowed[0] if allowed else None


def get_active_delegation(request):
    """Delegación activa validada: 'ALL', un Delegation o None.

    Si el valor guardado en sesión ya no es válido, se ignora y se
    devuelve la delegación por defecto (superadmin: 'ALL'; coordinador:
    su primera autorizada; el resto: su delegación).
    """
    user = getattr(request, 'user', None)
    role = get_role(user)
    if role is None:
        return None
    allowed = allowed_delegations(user)
    stored = request.session.get(ACTIVE_DELEGATION_KEY)
    if stored == ALL_DELEGATIONS:
        if role.scope == 'all':
            return ALL_DELEGATIONS
    elif stored is not None:
        try:
            stored_pk = int(stored)
        except (TypeError, ValueError):
            stored_pk = None
        if stored_pk is not None:
            for delegation in allowed:
                if delegation.pk == stored_pk:
                    return delegation
    return _default_active_delegation(role, allowed)


def set_active_delegation(request, value):
    """Guarda la delegación activa solo si es válida. Devuelve True/False.

    'ALL' solo es válido con alcance 'all'; los pk deben pertenecer a
    ``allowed_delegations``.
    """
    user = getattr(request, 'user', None)
    role = get_role(user)
    if role is None:
        return False
    if value == ALL_DELEGATIONS:
        if role.scope != 'all':
            return False
        request.session[ACTIVE_DELEGATION_KEY] = ALL_DELEGATIONS
        return True
    try:
        pk = int(value)
    except (TypeError, ValueError):
        return False
    allowed_pks = {delegation.pk for delegation in allowed_delegations(user)}
    if pk not in allowed_pks:
        return False
    request.session[ACTIVE_DELEGATION_KEY] = str(pk)
    return True


# ============================================================
# Reglas de rango
# ============================================================

def visible_users(user):
    """Usuarios visibles para ``user`` según rango + delegaciones activas.

    - Superusuario ve a todos (incluidos otros superusuarios).
    - Un superusuario NUNCA es visible para quien no es superusuario.
    - Solo se ven usuarios con rol de menor rango, con rol Activo y cuya
      delegación base esté dentro del contexto de delegaciones permitidas.
    - Los usuarios sin Employee no son visibles (salvo para superusuario).
    """
    role = get_role(user)
    if role is None:
        return User.objects.none()
    if getattr(user, 'is_superuser', False):
        return User.objects.all()
    delegations = allowed_delegations(user)
    if not delegations:
        return User.objects.none()
    lower_scopes = [
        scope for scope, rank in SCOPE_RANKS.items() if rank < role.rank
    ]
    if not lower_scopes:
        return User.objects.none()
    return User.objects.filter(
        is_superuser=False,
        employee__delegation_id__in=[delegation.pk for delegation in delegations],
        employee__role__scope__in=lower_scopes,
        employee__role__status='Activo',
    ).distinct()


def can_assign_role(user, role):
    """Regla de rango para asignar un rol: rango estrictamente menor.

    - Sin acceso -> False.
    - Rol destino Inactivo -> False.
    - Superusuario -> True (único que puede asignar roles de sistema).
    - Rol de sistema (is_system) -> solo superusuario.
    """
    if role is None:
        return False
    viewer = get_role(user)
    if viewer is None:
        return False
    if role.status != 'Activo':
        return False
    if getattr(user, 'is_superuser', False):
        return True
    if role.is_system:
        return False
    return viewer.rank > SCOPE_RANKS.get(role.scope, 0)


# ============================================================
# Resolución una vez por request
# ============================================================

class AccessInfo:
    """Permisos del usuario resueltos una sola vez por request."""

    def __init__(self, user):
        self.user = user
        self.role = get_role(user)
        if self.role is None:
            self.permissions = frozenset()
        elif self.role.is_virtual:
            self.permissions = None  # todos los permisos
        else:
            # Permisos de Django (grupo del rol + directos), una vez por request.
            self.permissions = module_permissions(user)

    def can(self, module, action):
        if self.role is None:
            return False
        if self.permissions is None:
            return True
        return (module, action) in self.permissions


def get_access(request):
    """AccessInfo de la request, resuelto y cacheado una sola vez por request."""
    info = getattr(request, '_sgr_access_info', None)
    if info is None:
        info = AccessInfo(getattr(request, 'user', None))
        try:
            request._sgr_access_info = info
        except AttributeError:
            pass  # objetos sin __dict__ no se cachéan; se resuelve igual
    return info


def _denied(request, module, action):
    audit(
        request, 'access_denied', module=module or '',
        object_repr=request.path,
        detail=f'{request.method} {request.path} ({module}.{action})',
    )
    raise PermissionDenied


class ModulePermissionMixin:
    """403 (PermissionDenied) si falta el permiso del módulo/acción."""
    module = None
    action = 'view'

    def dispatch(self, request, *args, **kwargs):
        info = get_access(request)
        if not info.can(self.module, self.action):
            _denied(request, self.module, self.action)
        return super().dispatch(request, *args, **kwargs)


def permission_required(module, action):
    """Decorador equivalente a ModulePermissionMixin para vistas de función."""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            info = get_access(request)
            if not info.can(module, action):
                _denied(request, module, action)
            return view_func(request, *args, **kwargs)
        return wrapper
    return decorator
