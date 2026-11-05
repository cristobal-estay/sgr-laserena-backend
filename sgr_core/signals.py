"""Señales que mantienen los grupos de Django sincronizados con los roles.

- Guardar un rol crea/renombra su grupo.
- Agregar o quitar una casilla de la matriz (``RolePermission``) actualiza los
  permisos del grupo.
Ver ``sgr_core.groups``.
"""

from django.db.models.signals import post_delete, post_save
from django.dispatch import receiver

from .groups import sync_role_group
from .models import Role, RolePermission


@receiver(post_save, sender=Role, dispatch_uid="sgr_role_group_sync")
def role_saved(sender, instance, raw=False, **kwargs):
    if raw:
        return
    sync_role_group(instance)


@receiver(post_save, sender=RolePermission, dispatch_uid="sgr_rolepermission_saved")
@receiver(post_delete, sender=RolePermission, dispatch_uid="sgr_rolepermission_deleted")
def role_permission_changed(sender, instance, raw=False, **kwargs):
    if raw:
        return
    role = Role.objects.filter(pk=instance.role_id).first()
    if role is not None:
        sync_role_group(role)
