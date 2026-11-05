"""Pruebas de la Parte 3: Inicio, cambio de delegación y placeholders."""
from django.contrib.auth.models import User
from django.test import TestCase, override_settings
from django.urls import reverse

from operaciones.models import Employee
from portal.tests.utils import TEST_STORAGES
from sgr_core.models import Delegation, Role, RolePermission
from sgr_core.roles import ensure_base_roles


@override_settings(STORAGES=TEST_STORAGES)
class HomeTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        ensure_base_roles(Role, RolePermission)
        cls.roles = {r.code: r for r in Role.objects.all()}
        cls.d1 = Delegation.objects.create(name="Centro", code="DEL01", color="#C62828")
        cls.d2 = Delegation.objects.create(name="Avenida del Mar", code="DEL02", color="#1D6FA5")
        cls.superuser = User.objects.create_user(
            username="superadmin", password="Demo2026!", is_superuser=True, is_staff=True,
        )
        cls.funcionario_user = User.objects.create_user(username="funcionario", password="Demo2026!")
        Employee.objects.create(
            user=cls.funcionario_user, rut="33.333.333-3",
            delegation=cls.d1, role=cls.roles["ROL04"],
        )
        cls.coord_user = User.objects.create_user(username="coordinador", password="Demo2026!")
        emp = Employee.objects.create(
            user=cls.coord_user, rut="11.111.111-1",
            delegation=cls.d1, role=cls.roles["ROL02"],
        )
        emp.authorized_delegations.set([cls.d1, cls.d2])

    def test_inicio_exige_login(self):
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 302)
        self.assertIn(reverse("login"), resp["Location"])

    def test_inicio_superadmin_200_y_menu_completo(self):
        self.client.login(username="superadmin", password="Demo2026!")
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, "Atenciones registradas")
        for label in ("Delegaciones", "Roles", "Usuarios", "Atenciones"):
            self.assertContains(resp, label)

    def test_inicio_funcionario_sin_usuarios_en_menu(self):
        self.client.login(username="funcionario", password="Demo2026!")
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        self.assertNotContains(resp, "Usuarios del sistema")
        self.assertContains(resp, "Atenciones resueltas")

    def test_placeholder_200_con_permiso_y_403_sin_permiso(self):
        self.client.login(username="funcionario", password="Demo2026!")
        self.assertEqual(self.client.get(reverse("attentions")).status_code, 200)
        resp = self.client.get(reverse("users"))
        self.assertEqual(resp.status_code, 403)

    def test_switch_valido_cambia_e_invalido_no_revienta(self):
        self.client.login(username="coordinador", password="Demo2026!")
        resp = self.client.post(reverse("switch_delegation"), {"delegation": str(self.d2.pk)})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session.get("active_delegation"), str(self.d2.pk))
        resp = self.client.post(reverse("switch_delegation"), {"delegation": "999999"})
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(self.client.session.get("active_delegation"), str(self.d2.pk))

    def test_switch_solo_post(self):
        self.client.login(username="coordinador", password="Demo2026!")
        self.assertEqual(self.client.get(reverse("switch_delegation")).status_code, 405)

    def test_django_admin_desactivado(self):
        # Evaluación 3: no existe /admin/; se responde con la página 404 propia.
        self.client.login(username="superadmin", password="Demo2026!")
        resp = self.client.get("/admin/")
        self.assertEqual(resp.status_code, 404)
        self.assertEqual(self.client.get("/admin/login/").status_code, 404)

    def test_404_propio(self):
        self.client.login(username="superadmin", password="Demo2026!")
        with override_settings(DEBUG=False):
            resp = self.client.get("/no-existe-xyz/")
            self.assertEqual(resp.status_code, 404)
            self.assertContains(resp, "No encontramos esta página", status_code=404)
