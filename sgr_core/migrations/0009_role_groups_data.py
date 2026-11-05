"""Crea los permisos módulo × acción y un grupo de Django por cada rol.

Usa las mismas funciones que la aplicación (``sgr_core.groups``) con los
modelos históricos de la migración.
"""

from django.db import migrations

from sgr_core.groups import sync_role_group


def forwards(apps, schema_editor):
    Role = apps.get_model("sgr_core", "Role")
    RolePermission = apps.get_model("sgr_core", "RolePermission")
    Group = apps.get_model("auth", "Group")
    Permission = apps.get_model("auth", "Permission")
    ContentType = apps.get_model("contenttypes", "ContentType")
    for role in Role.objects.all():
        sync_role_group(
            role, rolepermission_cls=RolePermission, group_cls=Group,
            permission_cls=Permission, contenttype_cls=ContentType,
        )


class Migration(migrations.Migration):

    dependencies = [
        ("auth", "0012_alter_user_first_name_max_length"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("sgr_core", "0008_role_group"),
    ]

    operations = [
        migrations.RunPython(forwards, migrations.RunPython.noop),
    ]
