"""Deja a cada funcionario existente en el grupo de Django de su rol."""

from django.db import migrations

from sgr_core.groups import sync_user_groups


def forwards(apps, schema_editor):
    Employee = apps.get_model("operaciones", "Employee")
    Group = apps.get_model("auth", "Group")
    for employee in Employee.objects.select_related("user", "role"):
        role = None if employee.deleted_at is not None else employee.role
        sync_user_groups(employee.user, role, group_cls=Group)

    # Superusuarios sin funcionario: grupo del Superadministrador (ROL01).
    Role = apps.get_model("sgr_core", "Role")
    User = apps.get_model("auth", "User")
    super_role = Role.objects.filter(code="ROL01").first()
    if super_role is not None:
        for user in User.objects.filter(is_superuser=True, employee__isnull=True):
            sync_user_groups(user, super_role, group_cls=Group)


class Migration(migrations.Migration):

    dependencies = [
        ("operaciones", "0008_attention_media_evidence_file"),
        ("sgr_core", "0009_role_groups_data"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
