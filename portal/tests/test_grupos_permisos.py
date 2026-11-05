"""Evaluación 3: roles ligados al sistema de permisos y grupos de Django.

- Cada rol tiene un ``auth.Group`` con un ``auth.Permission`` por casilla de
  su matriz (``sgr_core.<accion>_<modulo>``).
- Cada usuario queda en el grupo de su rol y cambia de grupo con el rol.
- El portal valida los accesos con ``user.has_perm``.
"""

from django.contrib.auth.models import Group, Permission
from django.test import TestCase, override_settings
from django.urls import reverse

from portal.access import has_permission
from portal.tests.helpers import (
    DEMO_PASSWORD,
    TEST_STORAGES,
    ensure_roles,
    make_delegation,
    make_employee,
)
from sgr_core.groups import CODENAME_TO_PAIR, group_name, permission_string
from sgr_core.models import RolePermission


@override_settings(STORAGES=TEST_STORAGES)
class GruposPermisosTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.roles = ensure_roles()
        cls.d1 = make_delegation("Centro", "DEL01")
        cls.funcionario = make_employee("funcionario", "11.111.113-3", cls.d1, cls.roles["ROL04"])
        cls.delegado = make_employee("delegado", "11.111.112-2", cls.d1, cls.roles["ROL03"])

    def _login(self, username):
        self.client.logout()
        assert self.client.login(username=username, password=DEMO_PASSWORD)

    def test_cada_rol_tiene_su_grupo_con_los_permisos_de_la_matriz(self):
        for role in self.roles.values():
            role.refresh_from_db()
            with self.subTest(role=role.code):
                self.assertIsNotNone(role.group)
                self.assertEqual(role.group.name, group_name(role))
                matriz = set(
                    RolePermission.objects.filter(role=role).values_list("module", "action")
                )
                grupo = {
                    CODENAME_TO_PAIR[codename]
                    for codename in role.group.permissions.values_list("codename", flat=True)
                }
                self.assertTrue(matriz)
                self.assertEqual(matriz, grupo)

    def test_usuario_queda_en_el_grupo_de_su_rol(self):
        user = self.funcionario.user
        self.assertEqual(
            list(user.groups.values_list("name", flat=True)),
            [group_name(self.roles["ROL04"])],
        )
        # Cambiar el rol cambia el grupo (sale del anterior).
        self.funcionario.role = self.roles["ROL03"]
        self.funcionario.save()
        self.assertEqual(
            list(user.groups.values_list("name", flat=True)),
            [group_name(self.roles["ROL03"])],
        )

    def test_grupos_manuales_no_se_tocan(self):
        extra = Group.objects.create(name="Comité de prueba")
        self.funcionario.user.groups.add(extra)
        self.funcionario.save()
        self.assertIn(extra, self.funcionario.user.groups.all())

    def test_acceso_se_valida_con_has_perm(self):
        user = self.funcionario.user
        self.assertTrue(user.has_perm(permission_string("attentions", "create")))
        self.assertTrue(has_permission(user, "attentions", "create"))
        self.assertFalse(user.has_perm(permission_string("delegations", "view")))
        self.assertFalse(has_permission(user, "delegations", "view"))

    def test_cambiar_la_matriz_actualiza_el_grupo_y_el_acceso(self):
        rol = self.roles["ROL04"]
        self._login("funcionario")
        self.assertEqual(self.client.get(reverse("items")).status_code, 403)
        RolePermission.objects.create(role=rol, module="items", action="view")
        rol.refresh_from_db()
        self.assertTrue(
            rol.group.permissions.filter(codename="view_items").exists()
        )
        self.assertEqual(self.client.get(reverse("items")).status_code, 200)
        RolePermission.objects.filter(role=rol, module="items").delete()
        self.assertEqual(self.client.get(reverse("items")).status_code, 403)

    def test_permiso_directo_de_django_tambien_cuenta(self):
        permiso = Permission.objects.get(codename="view_items")
        self.funcionario.user.user_permissions.add(permiso)
        self._login("funcionario")
        self.assertEqual(self.client.get(reverse("items")).status_code, 200)

    def test_rol_inactivo_no_entra_aunque_el_grupo_tenga_permisos(self):
        rol = self.roles["ROL04"]
        rol.status = "Inactivo"
        rol.save()
        self.funcionario.user.refresh_from_db()
        self.assertFalse(has_permission(self.funcionario.user, "attentions", "view"))

    def test_listados_muestran_el_grupo(self):
        self._login("delegado")
        resp = self.client.get(reverse("users"))
        self.assertContains(resp, "Grupo de Django")
        self.assertContains(resp, group_name(self.roles["ROL04"]))
