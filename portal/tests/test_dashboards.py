"""Evaluación 3: dashboards diferenciados por perfil (con Bootstrap 5).

- Administrador (Superadministrador): todos los mantenedores, transacciones,
  gestión de usuarios y visualización global.
- Supervisor (Coordinador / Delegado): mantenedores y transacciones
  autorizadas e información operacional de sus delegaciones.
- Administrativo (Funcionario): solo sus funcionalidades y sin operaciones
  críticas.
"""

import re

from django.test import TestCase, override_settings
from django.urls import reverse

from operaciones.models import Attention, Neighbor
from portal.dashboards import PROFILE_ADMIN, PROFILE_ADMINISTRATIVE, PROFILE_SUPERVISOR
from portal.tests.helpers import (
    DEMO_PASSWORD,
    TEST_STORAGES,
    ensure_roles,
    make_delegation,
    make_employee,
    make_user,
)
from sgr_core.models import AttentionSubtype, AttentionType


@override_settings(STORAGES=TEST_STORAGES)
class DashboardsTestCase(TestCase):
    @classmethod
    def setUpTestData(cls):
        cls.roles = ensure_roles()
        cls.d1 = make_delegation("Centro", "DEL01", color="#C62828")
        cls.d2 = make_delegation("Las Compañías", "DEL02", color="#1565C0")
        make_user("superadmin", is_superuser=True, is_staff=True, first_name="Super")
        cls.coordinador = make_employee("coordinador", "11.111.111-1", cls.d1, cls.roles["ROL02"])
        cls.coordinador.authorized_delegations.set([cls.d1, cls.d2])
        cls.delegado = make_employee("delegado", "11.111.112-2", cls.d1, cls.roles["ROL03"])
        cls.funcionario = make_employee("funcionario", "11.111.113-3", cls.d1, cls.roles["ROL04"])
        cls.otro = make_employee("otro", "11.111.114-4", cls.d1, cls.roles["ROL04"])
        tipo = AttentionType.objects.create(code="TAT01", name="Social")
        sub = AttentionSubtype.objects.create(code="SAT01", name="Ayuda social", attention_type=tipo)
        vecino = Neighbor.objects.create(identifier="12.345.678-5", full_name="Ana Pérez")

        def atencion(user, delegation, status="received"):
            return Attention.objects.create(
                neighbor=vecino, delegation=delegation, attention_type=tipo,
                attention_subtype=sub, description="Atención de prueba del dashboard.",
                responsible=user, status=status,
            )

        cls.propia = atencion(cls.funcionario.user, cls.d1, "resolved")
        cls.ajena = atencion(cls.otro.user, cls.d1)
        cls.de_d2 = atencion(cls.otro.user, cls.d2, "in_progress")

    def _get(self, username):
        self.client.logout()
        assert self.client.login(username=username, password=DEMO_PASSWORD)
        resp = self.client.get(reverse("home"))
        self.assertEqual(resp.status_code, 200)
        return resp

    def test_bootstrap_cargado_en_las_plantillas(self):
        resp = self._get("funcionario")
        self.assertContains(resp, "portal/vendor/bootstrap/bootstrap.min.css")
        self.assertContains(resp, "portal/vendor/bootstrap/bootstrap.bundle.min.js")
        self.client.logout()
        login = self.client.get(reverse("password_reset_request"))
        self.assertContains(login, "portal/vendor/bootstrap/bootstrap.min.css")

    def test_librerias_locales_sin_cdn(self):
        """Bootstrap y SweetAlert2 van dentro del proyecto: ninguna página depende
        de un CDN (si no cargara, Salir y Eliminar dejarían de funcionar)."""
        externo = re.compile(r'<(?:script|link)\b[^>]*\b(?:src|href)="(?:https?:)?//', re.I)
        panel = self._get("funcionario")
        self.client.logout()
        login = self.client.get(reverse("login"))
        for resp in (panel, login):
            html = resp.content.decode()
            self.assertIn("portal/vendor/sweetalert2/sweetalert2.all.min.js", html)
            self.assertIsNone(externo.search(html), externo.search(html) and externo.search(html).group(0))

    def test_dashboard_administrador(self):
        resp = self._get("superadmin")
        self.assertEqual(resp.context["profile"], PROFILE_ADMIN)
        self.assertContains(resp, "Dashboard Administrador")
        for texto in ("Mantenedores", "Transacciones", "Visualización global",
                      "Atenciones por delegación", "Actividad reciente", "Nuevo usuario"):
            self.assertContains(resp, texto)
        # Ve los 6 mantenedores y todas las atenciones.
        self.assertEqual(len(resp.context["maintainer_cards"]), 6)
        self.assertEqual(resp.context["summary"]["total"], 3)

    def test_dashboard_supervisor_coordinador_y_delegado(self):
        for username in ("coordinador", "delegado"):
            with self.subTest(username=username):
                resp = self._get(username)
                self.assertEqual(resp.context["profile"], PROFILE_SUPERVISOR)
                self.assertContains(resp, "Dashboard Supervisor")
                self.assertContains(resp, "Información operacional")
                self.assertContains(resp, "Mantenedores autorizados")
                self.assertNotContains(resp, "Visualización global")
                keys = {card["key"] for card in resp.context["maintainer_cards"]}
                self.assertNotIn("delegations", keys)
                self.assertNotIn("roles", keys)
                self.assertIn("users", keys)

    def test_supervisor_ve_solo_su_delegacion_activa(self):
        resp = self._get("delegado")
        numeros = {item.number for item in resp.context["recent_attentions"]}
        self.assertEqual(numeros, {self.propia.number, self.ajena.number})

    def test_dashboard_administrativo(self):
        resp = self._get("funcionario")
        self.assertEqual(resp.context["profile"], PROFILE_ADMINISTRATIVE)
        self.assertContains(resp, "Dashboard Administrativo")
        self.assertContains(resp, "Funcionalidades asignadas")
        self.assertContains(resp, "Operaciones restringidas")
        self.assertContains(resp, "Atenciones resueltas")
        self.assertNotContains(resp, "Mantenedores autorizados")
        self.assertEqual(resp.context["maintainer_cards"], [])
        self.assertIn("Eliminar", resp.context["restricted_actions"])
        self.assertIn("Editar", resp.context["restricted_actions"])
        # Solo sus propias atenciones.
        numeros = [item.number for item in resp.context["recent_attentions"]]
        self.assertEqual(numeros, [self.propia.number])

    def test_dashboard_muestra_grupo_de_django(self):
        resp = self._get("funcionario")
        self.assertContains(resp, "Grupo de Django")
        self.assertContains(resp, "ROL04 · Funcionario")
