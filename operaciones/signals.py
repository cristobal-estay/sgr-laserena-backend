"""Señal que deja a cada funcionario en el grupo de Django de su rol."""

from django.db.models.signals import post_save
from django.dispatch import receiver

from sgr_core.groups import sync_user_groups

from .models import Employee


@receiver(post_save, sender=Employee, dispatch_uid="sgr_employee_group_sync")
def employee_saved(sender, instance, raw=False, **kwargs):
    if raw or instance.user_id is None:
        return
    role = None if instance.deleted_at is not None else instance.role
    sync_user_groups(instance.user, role)
