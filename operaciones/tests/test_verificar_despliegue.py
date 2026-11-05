"""Pruebas del comando ``verificar_despliegue`` (chequeo previo a la revisión)."""

from io import StringIO

from django.core import mail
from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase, override_settings

from portal.tests.helpers import ensure_roles, make_delegation, make_employee
from portal.tests.utils import TEST_STORAGES

SECURE_KEY = "clave-de-pruebas-" + "x" * 40


@override_settings(STORAGES=TEST_STORAGES, SECRET_KEY=SECURE_KEY)
class VerificarDespliegueTests(TestCase):
    @classmethod
    def setUpTestData(cls):
        roles = ensure_roles()
        delegation = make_delegation("Centro", "DEL01")
        make_employee("funcionario", "11.111.113-3", delegation, roles["ROL04"])

    def _run(self, *args):
        out = StringIO()
        call_command("verificar_despliegue", *args, stdout=out)
        return out.getvalue()

    def test_reporta_grupos_admin_y_bootstrap(self):
        salida = self._run()
        self.assertIn("ROL04 · Funcionario: 4 permisos, 1 usuario(s)", salida)
        self.assertIn("Cada usuario está en el grupo de su rol", salida)
        self.assertIn("Django Admin desactivado", salida)
        self.assertIn("Bootstrap 5 incluido en el proyecto", salida)
        self.assertIn("SweetAlert2 incluido en el proyecto (sin CDN)", salida)
        self.assertIn("Todo listo para la revisión.", salida)

    def test_correo_de_prueba(self):
        salida = self._run("--correo", "destino@ejemplo.cl")
        self.assertIn("Correo enviado a destino@ejemplo.cl", salida)
        self.assertEqual(mail.outbox[0].to, ["destino@ejemplo.cl"])

    @override_settings(SECRET_KEY="django-insecure-clave-de-ejemplo", DEBUG=False)
    def test_clave_de_ejemplo_en_produccion_es_error(self):
        with self.assertRaises(CommandError):
            self._run()
