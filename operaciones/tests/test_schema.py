"""Pruebas del esquema de la Parte 2B (operaciones)."""
import re

from django.contrib.auth.models import User
from django.core.management import call_command
from django.db import connection
from django.db.models.deletion import ProtectedError, RestrictedError
from django.test import TestCase, override_settings
from django.utils import timezone

from operaciones.models import Attention, Employee, Neighbor
from portal.models import AuditLog
from portal.tests.utils import TEST_STORAGES
from sgr_core.models import AttentionSubtype, AttentionType, Delegation, Role


def _base(tipo_code="TAT01", subtipo_code="SAT01"):
    deleg = Delegation.objects.create(name="Base", code="DEL99")
    tipo = AttentionType.objects.create(code=tipo_code, name="Tipo")
    subtipo = AttentionSubtype.objects.create(
        code=subtipo_code, name="Sub", attention_type=tipo
    )
    vecino = Neighbor.objects.create(identifier="1-9", full_name="Vecino Uno")
    user = User.objects.create_user("resp_demo", password="Demo2026!")
    return deleg, tipo, subtipo, vecino, user


@override_settings(STORAGES=TEST_STORAGES)
class AttentionSchemaTests(TestCase):
    def test_tablas_con_nombre_de_convencion(self):
        tables = connection.introspection.table_names()
        self.assertIn("vecino", tables)
        self.assertIn("atencion", tables)

    def test_number_formato_unico_y_asignado(self):
        deleg, tipo, subtipo, vecino, user = _base()
        a1 = Attention.objects.create(
            neighbor=vecino, delegation=deleg, attention_type=tipo,
            attention_subtype=subtipo, description="Caso uno.", responsible=user,
        )
        vecino2 = Neighbor.objects.create(identifier="2-7", full_name="Vecino Dos")
        a2 = Attention.objects.create(
            neighbor=vecino2, delegation=deleg, attention_type=tipo,
            attention_subtype=subtipo, description="Caso dos.", responsible=user,
        )
        self.assertRegex(a1.number, r"^ATN-\d{4}$")
        self.assertNotEqual(a1.number, a2.number)
        self.assertEqual(Attention.objects.filter(number=a1.number).count(), 1)

    def test_number_no_se_recalcula_al_editar(self):
        deleg, tipo, subtipo, vecino, user = _base()
        att = Attention.objects.create(
            neighbor=vecino, delegation=deleg, attention_type=tipo,
            attention_subtype=subtipo, description="Caso editable.", responsible=user,
        )
        numero = att.number
        att.description = "Caso editado."
        att.save()
        att.refresh_from_db()
        self.assertEqual(att.number, numero)

    def test_protected_usuario_con_atenciones(self):
        deleg, tipo, subtipo, vecino, user = _base()
        Attention.objects.create(
            neighbor=vecino, delegation=deleg, attention_type=tipo,
            attention_subtype=subtipo, description="Caso.", responsible=user,
        )
        # RESTRICT se manifiesta como RestrictedError (hermana de ProtectedError).
        with self.assertRaises((ProtectedError, RestrictedError)):
            user.delete()

    def test_protected_rol_con_usuarios(self):
        role = Role.objects.create(code="ROL98", name="Rol demo")
        user = User.objects.create_user("con_rol", password="Demo2026!")
        deleg = Delegation.objects.create(name="D98", code="DEL98")
        Employee.objects.create(user=user, rut="9-9", delegation=deleg, role=role)
        with self.assertRaises(ProtectedError):
            role.delete()

    def test_protected_delegacion_con_registros(self):
        deleg, tipo, subtipo, vecino, user = _base()
        Attention.objects.create(
            neighbor=vecino, delegation=deleg, attention_type=tipo,
            attention_subtype=subtipo, description="Caso.", responsible=user,
        )
        # RESTRICT se manifiesta como RestrictedError (hermana de ProtectedError).
        with self.assertRaises((ProtectedError, RestrictedError)):
            deleg.delete()

    def test_alive_excluye_borrado_logico(self):
        deleg, tipo, subtipo, vecino, user = _base()
        att = Attention.objects.create(
            neighbor=vecino, delegation=deleg, attention_type=tipo,
            attention_subtype=subtipo, description="Caso.", responsible=user,
        )
        self.assertEqual(Attention.alive.count(), 1)
        att.deleted_at = timezone.now()
        att.save(update_fields=["deleted_at"])
        self.assertEqual(Attention.objects.count(), 1)
        self.assertEqual(Attention.alive.count(), 0)

    def test_seed_idempotente_atenciones(self):
        call_command("seed_demo", verbosity=0)
        n_vecinos = Neighbor.objects.count()
        n_atenciones = Attention.objects.count()
        self.assertEqual(n_vecinos, 14)
        self.assertEqual(n_atenciones, 14)
        numeros = list(Attention.objects.values_list("number", flat=True))
        self.assertEqual(len(set(numeros)), 14)
        for numero in numeros:
            self.assertTrue(re.match(r"^ATN-\d{4}$", numero or ""))
        call_command("seed_demo", verbosity=0)
        self.assertEqual(Neighbor.objects.count(), n_vecinos)
        self.assertEqual(Attention.objects.count(), n_atenciones)

    def test_seed_created_at_ultimos_10_dias(self):
        call_command("seed_demo", verbosity=0)
        limite = timezone.now() - timezone.timedelta(days=10, hours=2)
        self.assertEqual(Attention.objects.filter(created_at__lt=limite).count(), 0)

    def test_indices_portal(self):
        idx = {i.name for i in AuditLog._meta.indexes}
        self.assertIn("idx_auditoria_fecha", idx)
        self.assertIn("idx_auditoria_user_fecha", idx)

    def test_sin_cambios_pendientes(self):
        call_command("makemigrations", check=True, dry_run=True, verbosity=0)

