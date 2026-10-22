"""Pruebas de la Clase 9: subida de archivos e imágenes (MEDIA) en Atenciones.

Cubre: atención sin archivos (campos opcionales), creación y edición con imagen
y PDF válidos, y rechazo por peso excesivo (> 2 MB imagen, > 5 MB documento) y
por extensión no permitida. Los archivos se guardan en una carpeta temporal que
se borra al terminar, así no se ensucia ``media/`` del proyecto.
"""

import os
import shutil
import tempfile
from io import BytesIO

from django.core.exceptions import ValidationError
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
from django.urls import reverse

from PIL import Image

from operaciones.models import Attention, Neighbor
from portal.tests.helpers import (
    DEMO_PASSWORD,
    TEST_STORAGES,
    ensure_roles,
    make_delegation,
    make_employee,
)
from portal.validators import validate_attachment_file, validate_image_file
from sgr_core.models import AttentionSubtype, AttentionType

MB = 1024 * 1024
MEDIA_TMP = tempfile.mkdtemp(prefix="sgr_media_test_")


def png_bytes(size=(20, 20)):
    """PNG real y pequeño (Pillow valida el contenido de las imágenes)."""
    buffer = BytesIO()
    Image.new("RGB", size, (146, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


def big_png_bytes():
    """PNG real de ruido aleatorio que pesa más de 2 MB."""
    side = 1000
    image = Image.frombytes("RGB", (side, side), os.urandom(side * side * 3))
    buffer = BytesIO()
    image.save(buffer, format="PNG")
    data = buffer.getvalue()
    assert len(data) > 2 * MB
    return data


def png_file(name="foto.png"):
    return SimpleUploadedFile(name, png_bytes(), content_type="image/png")


def pdf_file(name="respaldo.pdf", size=2048):
    content = b"%PDF-1.4\n" + b"0" * size
    return SimpleUploadedFile(name, content, content_type="application/pdf")


@override_settings(STORAGES=TEST_STORAGES, MEDIA_ROOT=MEDIA_TMP)
class MediaUploadTestCase(TestCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.addClassCleanup(shutil.rmtree, MEDIA_TMP, ignore_errors=True)

    @classmethod
    def setUpTestData(cls):
        cls.roles = ensure_roles()
        cls.d1 = make_delegation("Centro", "DEL01", color="#C62828")
        cls.coordinador = make_employee(
            "coordinador", "11.111.111-1", cls.d1, cls.roles["ROL02"],
        )
        cls.coordinador.authorized_delegations.set([cls.d1])
        cls.delegado = make_employee(
            "delegado", "11.111.112-2", cls.d1, cls.roles["ROL03"],
        )
        cls.tipo = AttentionType.objects.create(code="TAT01", name="Social")
        cls.sub = AttentionSubtype.objects.create(
            code="SAT01", name="Ayuda social", attention_type=cls.tipo,
        )
        cls.vecino = Neighbor.objects.create(
            identifier="11.111.111-1", full_name="María González",
        )
        cls.atencion = Attention.objects.create(
            neighbor=cls.vecino, delegation=cls.d1,
            attention_type=cls.tipo, attention_subtype=cls.sub,
            description="Atención existente sin archivos adjuntos.",
            responsible=cls.delegado.user,
        )

    def _login(self, username):
        self.client.logout()
        assert self.client.login(username=username, password=DEMO_PASSWORD)

    def _create_data(self, **extra):
        data = {
            "neighbor": str(self.vecino.pk),
            "delegation": str(self.d1.pk),
            "attention_type": str(self.tipo.pk),
            "attention_subtype": str(self.sub.pk),
            "description": "Descripción válida de la atención ingresada.",
        }
        data.update(extra)
        return data

    def _edit_data(self, **extra):
        data = {
            "attention_type": str(self.tipo.pk),
            "attention_subtype": str(self.sub.pk),
            "description": "Descripción editada de la atención existente.",
            "status": "in_progress",
        }
        data.update(extra)
        return data

    def _create(self, **extra):
        self._login("coordinador")
        return self.client.post(reverse("attentions_new"), self._create_data(**extra))

    def _edit(self, **extra):
        self._login("delegado")
        return self.client.post(
            reverse("attentions_edit", args=[self.atencion.pk]), self._edit_data(**extra),
        )

    # --- Archivos opcionales ---------------------------------------------

    def test_crear_sin_archivos(self):
        total = Attention.objects.count()
        resp = self._create()
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(Attention.objects.count(), total + 1)
        nueva = Attention.objects.latest("pk")
        self.assertFalse(nueva.evidence_image)
        self.assertFalse(nueva.attachment)

    def test_formulario_es_multipart_y_tiene_los_campos(self):
        self._login("coordinador")
        resp = self.client.get(reverse("attentions_new"))
        self.assertContains(resp, 'enctype="multipart/form-data"')
        self.assertContains(resp, 'name="evidence_image"')
        self.assertContains(resp, 'name="attachment"')

    def test_editar_sin_archivos_no_falla_con_archivo_inexistente(self):
        # Archivo registrado en la BD pero ausente del disco (otra máquina):
        # editar otros campos no debe lanzar error.
        Attention.objects.filter(pk=self.atencion.pk).update(
            evidence_image="atenciones/imagenes/2026/10/no_existe.png",
        )
        resp = self._edit()
        self.assertEqual(resp.status_code, 302)

    # --- Archivos válidos ------------------------------------------------

    def test_crear_con_imagen_valida(self):
        resp = self._create(evidence_image=png_file())
        self.assertEqual(resp.status_code, 302)
        nueva = Attention.objects.latest("pk")
        self.assertTrue(nueva.evidence_image.name.startswith("atenciones/imagenes/"))
        self.assertTrue(nueva.evidence_image.storage.exists(nueva.evidence_image.name))

    def test_crear_con_pdf_valido(self):
        resp = self._create(attachment=pdf_file())
        self.assertEqual(resp.status_code, 302)
        nueva = Attention.objects.latest("pk")
        self.assertTrue(nueva.attachment.name.startswith("atenciones/adjuntos/"))
        self.assertTrue(nueva.attachment.name.endswith(".pdf"))

    def test_editar_con_imagen_y_pdf_validos(self):
        resp = self._edit(evidence_image=png_file(), attachment=pdf_file())
        self.assertEqual(resp.status_code, 302)
        self.atencion.refresh_from_db()
        self.assertTrue(self.atencion.evidence_image)
        self.assertTrue(self.atencion.attachment)

    def test_consulta_y_edicion_muestran_miniatura_y_enlace(self):
        self._edit(evidence_image=png_file(), attachment=pdf_file())
        self.atencion.refresh_from_db()
        for name in ("attentions_edit", "attentions_detail"):
            resp = self.client.get(reverse(name, args=[self.atencion.pk]))
            self.assertEqual(resp.status_code, 200)
            self.assertContains(resp, self.atencion.evidence_image.url)
            self.assertContains(resp, self.atencion.attachment.url)

    def test_consulta_sin_archivos_no_falla(self):
        self._login("delegado")
        resp = self.client.get(reverse("attentions_detail", args=[self.atencion.pk]))
        self.assertEqual(resp.status_code, 200)

    # --- Rechazos --------------------------------------------------------

    def test_rechaza_imagen_de_mas_de_2mb(self):
        total = Attention.objects.count()
        grande = SimpleUploadedFile("grande.png", big_png_bytes(), content_type="image/png")
        resp = self._create(evidence_image=grande)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("evidence_image", resp.context["form"].errors)
        self.assertContains(resp, "pesa demasiado")
        self.assertEqual(Attention.objects.count(), total)

    def test_rechaza_documento_de_mas_de_5mb(self):
        total = Attention.objects.count()
        grande = pdf_file("grande.pdf", size=5 * MB + 1)
        resp = self._create(attachment=grande)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.context["form"].errors)
        self.assertContains(resp, "pesa demasiado")
        self.assertEqual(Attention.objects.count(), total)

    def test_rechaza_imagen_con_extension_no_permitida(self):
        total = Attention.objects.count()
        malo = SimpleUploadedFile("virus.exe", png_bytes(), content_type="image/png")
        resp = self._create(evidence_image=malo)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("evidence_image", resp.context["form"].errors)
        self.assertEqual(Attention.objects.count(), total)

    def test_rechaza_documento_con_extension_no_permitida(self):
        total = Attention.objects.count()
        for nombre in ("programa.exe", "notas.txt"):
            malo = SimpleUploadedFile(nombre, b"contenido", content_type="text/plain")
            resp = self._create(attachment=malo)
            self.assertEqual(resp.status_code, 200)
            self.assertIn("attachment", resp.context["form"].errors)
        self.assertEqual(Attention.objects.count(), total)

    def test_edicion_rechaza_archivo_invalido_y_no_modifica(self):
        malo = SimpleUploadedFile("notas.txt", b"contenido", content_type="text/plain")
        resp = self._edit(attachment=malo)
        self.assertEqual(resp.status_code, 200)
        self.assertIn("attachment", resp.context["form"].errors)
        self.atencion.refresh_from_db()
        self.assertFalse(self.atencion.attachment)
        self.assertEqual(self.atencion.status, "received")


class ValidatorsUnitTests(TestCase):
    """Los validadores sirven directamente sobre archivos subidos."""

    def test_imagen_valida_y_limites(self):
        validate_image_file(SimpleUploadedFile("a.JPG", b"x" * 100))  # mayúsculas ok
        with self.assertRaises(ValidationError):
            validate_image_file(SimpleUploadedFile("a.pdf", b"x"))
        with self.assertRaises(ValidationError):
            validate_image_file(SimpleUploadedFile("a.png", b"x" * (2 * MB + 1)))

    def test_adjunto_valido_y_limites(self):
        validate_attachment_file(SimpleUploadedFile("a.pdf", b"x" * 100))
        validate_attachment_file(SimpleUploadedFile("a.webp", b"x" * 100))
        with self.assertRaises(ValidationError):
            validate_attachment_file(SimpleUploadedFile("a.txt", b"x"))
        with self.assertRaises(ValidationError):
            validate_attachment_file(SimpleUploadedFile("a.pdf", b"x" * (5 * MB + 1)))
