
import re
from datetime import timedelta
from unittest import mock

from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils import timezone

from portal.models import PasswordResetCode
from portal.tests.utils import TEST_STORAGES


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STORAGES=TEST_STORAGES,
)
class LoginTests(TestCase):
    def setUp(self):
        self.client = Client()
        cache.clear()  # Evita que contadores de intentos de otros tests afecten este
        self.user = User.objects.create_user(
            username='admin_demo',
            email='admin_demo@ejemplo.cl',
            password='Demo2026!'
        )
        self.inactive_user = User.objects.create_user(
            username='inactivo_demo',
            email='inactivo_demo@ejemplo.cl',
            password='Demo2026!'
        )
        self.inactive_user.is_active = False
        self.inactive_user.save()

    # --- Login por usuario ---
    def test_login_por_usuario(self):
        resp = self.client.post(reverse('login'), {
            'username': 'admin_demo',
            'password': 'Demo2026!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('dashboard'))

    # --- Login por correo (minúsculas) ---
    def test_login_por_correo_minusculas(self):
        resp = self.client.post(reverse('login'), {
            'username': 'admin_demo@ejemplo.cl',
            'password': 'Demo2026!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('dashboard'))

    # --- Login por correo (mayúsculas) ---
    def test_login_por_correo_mayusculas(self):
        resp = self.client.post(reverse('login'), {
            'username': 'Admin_Demo@Ejemplo.cl',
            'password': 'Demo2026!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('dashboard'))

    # --- Credenciales incorrectas: mensaje genérico ---
    def test_login_credenciales_incorrectas(self):
        resp = self.client.post(reverse('login'), {
            'username': 'admin_demo',
            'password': 'clave_mala'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = [str(m) for m in resp.context['messages']]
        self.assertIn('El usuario o la contraseña no son correctos.', messages)
        # No debe revelar si el usuario existe
        self.assertNotIn('usuario no existe', ' '.join(messages).lower())

    # --- Cuenta inactiva: mensaje específico ---
    def test_login_cuenta_inactiva(self):
        resp = self.client.post(reverse('login'), {
            'username': 'inactivo_demo',
            'password': 'Demo2026!'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = [str(m) for m in resp.context['messages']]
        self.assertIn(
            'Tu cuenta está inactiva. Comunícate con el coordinador o el delegado de tu delegación.',
            messages
        )

    # --- Bloqueo por intentos ---
    def test_login_bloqueo_por_intentos(self):
        # 5 intentos fallidos
        for i in range(5):
            resp = self.client.post(reverse('login'), {
                'username': 'admin_demo',
                'password': 'clave_mala'
            }, follow=True)
        messages = [str(m) for m in resp.context['messages']]
        self.assertIn(
            'Has superado el límite de intentos. Espera 10 minutos antes de volver a intentar.',
            messages
        )

    # --- Bloqueo vigente aunque la clave sea correcta ---
    def test_login_bloqueo_con_clave_correcta_rechazado(self):
        for i in range(5):
            self.client.post(reverse('login'), {
                'username': 'admin_demo',
                'password': 'clave_mala'
            })
        # Aunque ahora la clave sea correcta, la cuenta sigue bloqueada.
        resp = self.client.post(reverse('login'), {
            'username': 'admin_demo',
            'password': 'Demo2026!'
        }, follow=True)
        messages = [str(m) for m in resp.context['messages']]
        self.assertIn(
            'Has superado el límite de intentos. Espera 10 minutos antes de volver a intentar.',
            messages
        )
        self.assertIsNone(self.client.session.get('_auth_user_id'))

    # --- next seguro ---
    def test_login_next_seguro(self):
        resp = self.client.post(
            reverse('login') + '?next=' + reverse('dashboard'),
            {'username': 'admin_demo', 'password': 'Demo2026!'}
        )
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('dashboard'))

    # --- next externo rechazado ---
    def test_login_next_externo_rechazado(self):
        resp = self.client.post(
            reverse('login') + '?next=https://evil.example.com',
            {'username': 'admin_demo', 'password': 'Demo2026!'}
        )
        self.assertEqual(resp.status_code, 302)
        # Debe ir al dashboard por defecto, no al dominio externo
        self.assertEqual(resp['Location'], reverse('dashboard'))

    # --- Logout solo por POST ---
    def test_logout_solo_post(self):
        self.client.login(username='admin_demo', password='Demo2026!')
        # GET no debe cerrar sesión
        resp = self.client.get(reverse('logout'))
        self.assertEqual(resp.status_code, 405)
        # POST sí cierra sesión
        resp = self.client.post(reverse('logout'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('login'))

    # --- Usuario autenticado en /login/ va al dashboard ---
    def test_login_usuario_autenticado_redirige(self):
        self.client.login(username='admin_demo', password='Demo2026!')
        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('dashboard'))


@override_settings(
    EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
    STORAGES=TEST_STORAGES,
)
class PasswordRecoveryTests(TestCase):
    def setUp(self):
        self.client = Client()
        self.user = User.objects.create_user(
            username='admin_demo',
            email='admin_demo@ejemplo.cl',
            password='Demo2026!'
        )

    def test_recovery_correo_inexistente_misma_respuesta(self):
        resp = self.client.post(reverse('password_reset_request'), {
            'email': 'noexiste@ejemplo.cl'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('password_reset_verify'))
        # El paso 2 se renderiza igual (no redirige al paso 1) y no se envía correo.
        resp2 = self.client.get(reverse('password_reset_verify'))
        self.assertEqual(resp2.status_code, 200)
        self.assertEqual(len(mail.outbox), 0)
        self.assertIn('n***@ejemplo.cl', resp2.content.decode())

    def test_recovery_codigo_guardado_como_hash(self):
        self.client.post(reverse('password_reset_request'), {
            'email': 'admin_demo@ejemplo.cl'
        })
        codes = PasswordResetCode.objects.filter(user=self.user)
        self.assertEqual(codes.count(), 1)
        # El código se guarda hasheado (verificable), nunca en claro.
        match = re.search(r'\b\d{6}\b', mail.outbox[0].body)
        self.assertIsNotNone(match)
        self.assertTrue(check_password(match.group(), codes.first().code_hash))

    def test_recovery_correo_enviado_con_6_digitos(self):
        self.client.post(reverse('password_reset_request'), {
            'email': 'admin_demo@ejemplo.cl'
        })
        self.assertEqual(len(mail.outbox), 1)
        match = re.search(r'\b\d{6}\b', mail.outbox[0].body)
        self.assertIsNotNone(match)
        from django.contrib.auth.hashers import check_password
        code_obj = PasswordResetCode.objects.filter(user=self.user).first()
        self.assertTrue(check_password(match.group(), code_obj.code_hash))

    def test_recovery_codigo_vencido(self):
        from django.contrib.auth.hashers import make_password
        expires = timezone.now() - timedelta(minutes=1)
        PasswordResetCode.objects.create(
            user=self.user, code_hash=make_password('123456'),
            expires_at=expires, last_sent_at=timezone.now()
        )
        session = self.client.session
        session['pr_email'] = 'admin_demo@ejemplo.cl'
        session.save()
        resp = self.client.post(reverse('password_reset_verify'), {
            'code_digit': ['1', '2', '3', '4', '5', '6']
        }, follow=True)
        messages = [str(m) for m in resp.context['messages']]
        self.assertIn('El código no es válido o ha vencido. Solicita uno nuevo.', messages)

    def test_recovery_3_intentos_fallidos(self):
        from django.contrib.auth.hashers import make_password
        expires = timezone.now() + timedelta(minutes=10)
        PasswordResetCode.objects.create(
            user=self.user, code_hash=make_password('123456'),
            expires_at=expires, last_sent_at=timezone.now()
        )
        session = self.client.session
        session['pr_email'] = 'admin_demo@ejemplo.cl'
        session.save()
        for i in range(3):
            resp = self.client.post(reverse('password_reset_verify'), {
                'code_digit': ['9', '9', '9', '9', '9', '9']
            }, follow=True)
        messages = [str(m) for m in resp.context['messages']]
        self.assertIn('El código no es válido o ha vencido. Solicita uno nuevo.', messages)

    def _iniciar_flujo(self):
        """Deja la sesión en el paso 2 con un código recién enviado (vía paso 1)."""
        resp = self.client.post(reverse('password_reset_request'), {
            'email': 'admin_demo@ejemplo.cl'
        })
        self.assertEqual(resp.status_code, 302)
        return resp

    def test_recovery_reenvio_antes_de_45s_rechazado(self):
        self._iniciar_flujo()
        codos_antes = PasswordResetCode.objects.filter(user=self.user).count()
        # Reenvío inmediato: el servidor lo rechaza y NO crea un código nuevo.
        resp = self.client.post(reverse('password_reset_resend'), follow=True)
        self.assertEqual(resp.status_code, 200)
        messages = [str(m) for m in resp.context['messages']]
        self.assertIn('Debes esperar unos segundos antes de volver a enviar el código.', messages)
        self.assertEqual(PasswordResetCode.objects.filter(user=self.user).count(), codos_antes)
        self.assertEqual(len(mail.outbox), 1)  # solo el correo del paso 1

    def test_recovery_reenvio_despues_de_45s_ok(self):
        self._iniciar_flujo()
        # Simulamos que ya pasaron más de 45 s del último envío real.
        PasswordResetCode.objects.filter(user=self.user).update(
            last_sent_at=timezone.now() - timedelta(seconds=46)
        )
        resp = self.client.post(reverse('password_reset_resend'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('password_reset_verify'))
        self.assertEqual(len(mail.outbox), 2)  # paso 1 + reenvío
        self.assertEqual(PasswordResetCode.objects.filter(user=self.user).count(), 2)

    def test_recovery_nuevo_codigo_invalida_anterior(self):
        # Códigos deterministas: 123456 en el paso 1 y 654321 en el reenvío.
        with mock.patch(
            'portal.views.secrets.randbelow', side_effect=[123456, 654321]
        ):
            self._iniciar_flujo()
            primer_codigo = PasswordResetCode.objects.get(user=self.user)
            # Simulamos que ya pasaron más de 45 s del último envío real.
            PasswordResetCode.objects.filter(user=self.user).update(
                last_sent_at=timezone.now() - timedelta(seconds=46)
            )
            resp = self.client.post(reverse('password_reset_resend'))

        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('password_reset_verify'))
        self.assertEqual(len(mail.outbox), 2)  # paso 1 + reenvío
        self.assertEqual(PasswordResetCode.objects.filter(user=self.user).count(), 2)

        # El reenvío invalida el código anterior: queda marcado como usado.
        primer_codigo.refresh_from_db()
        self.assertIsNotNone(primer_codigo.used_at)
        self.assertTrue(primer_codigo.is_used())
        self.assertFalse(primer_codigo.is_valid())

        # Solo el código nuevo sigue vigente para el usuario.
        vigente = PasswordResetCode.objects.filter(
            user=self.user, used_at__isnull=True
        ).first()
        self.assertIsNotNone(vigente)
        self.assertNotEqual(vigente.pk, primer_codigo.pk)
        self.assertTrue(vigente.is_valid())

        # Y el código anterior ya no sirve para verificar: el paso 2 lo rechaza
        # y la sesión no queda verificada.
        resp = self.client.post(reverse('password_reset_verify'), {
            'code_digit': ['1', '2', '3', '4', '5', '6']
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        mensajes = [str(m) for m in resp.context['messages']]
        self.assertIn('Código incorrecto. Verifica e inténtalo de nuevo.', mensajes)
        self.assertFalse(self.client.session.get('pr_verified'))

    @override_settings(PASSWORD_RESET_CODE_TTL=120)
    def test_recovery_expira_segun_password_reset_code_ttl(self):
        # El código se crea a través del paso 1, con el TTL definido en settings.
        resp = self.client.post(reverse('password_reset_request'), {
            'email': 'admin_demo@ejemplo.cl'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(len(mail.outbox), 1)
        codigo = PasswordResetCode.objects.get(user=self.user)
        digitos = list(re.search(r'\b\d{6}\b', mail.outbox[0].body).group())

        # La vigencia proviene de PASSWORD_RESET_CODE_TTL: 120 segundos.
        vigencia = (codigo.expires_at - codigo.created_at).total_seconds()
        self.assertGreater(vigencia, 110)
        self.assertLessEqual(vigencia, 120)

        # Simulamos que ya transcurrieron 121 segundos desde su emisión: con
        # TTL=120 el código quedó vencido hace 1 segundo.
        PasswordResetCode.objects.filter(user=self.user).update(
            expires_at=codigo.expires_at - timedelta(seconds=121)
        )
        codigo.refresh_from_db()
        self.assertTrue(codigo.is_expired())

        # /recuperar/verificar/ lo rechaza como vencido.
        resp = self.client.post(reverse('password_reset_verify'), {
            'code_digit': digitos
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        mensajes = [str(m) for m in resp.context['messages']]
        self.assertIn('El código no es válido o ha vencido. Solicita uno nuevo.', mensajes)
        self.assertFalse(self.client.session.get('pr_verified'))

    def test_recovery_contrasena_debil_rechazada(self):
        session = self.client.session
        session['pr_email'] = 'admin_demo@ejemplo.cl'
        session['pr_verified'] = True
        session['pr_verified_at'] = int(timezone.now().timestamp())
        session.save()
        resp = self.client.post(reverse('password_reset_confirm'), {
            'new_password': 'abc',
            'confirm_password': 'abc'
        }, follow=True)
        self.assertEqual(resp.status_code, 200)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Demo2026!'))

    def test_recovery_contrasena_cambiada_y_codigos_invalidados(self):
        from django.contrib.auth.hashers import make_password
        expires = timezone.now() + timedelta(minutes=10)
        PasswordResetCode.objects.create(
            user=self.user, code_hash=make_password('123456'),
            expires_at=expires, last_sent_at=timezone.now()
        )
        session = self.client.session
        session['pr_email'] = 'admin_demo@ejemplo.cl'
        session['pr_verified'] = True
        session['pr_verified_at'] = int(timezone.now().timestamp())
        session.save()
        resp = self.client.post(reverse('password_reset_confirm'), {
            'new_password': 'NuevaClave2026!',
            'confirm_password': 'NuevaClave2026!'
        })
        self.assertEqual(resp.status_code, 302)
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NuevaClave2026!'))
        for c in PasswordResetCode.objects.filter(user=self.user):
            self.assertIsNotNone(c.used_at)

    def test_recovery_flujo_completo(self):
        resp = self.client.post(reverse('password_reset_request'), {
            'email': 'admin_demo@ejemplo.cl'
        })
        self.assertEqual(resp.status_code, 302)
        match = re.search(r'\b\d{6}\b', mail.outbox[0].body)
        digits = list(match.group())
        resp = self.client.post(reverse('password_reset_verify'), {
            'code_digit': digits
        })
        self.assertEqual(resp.status_code, 302)
        resp = self.client.post(reverse('password_reset_confirm'), {
            'new_password': 'NuevaClave2026!',
            'confirm_password': 'NuevaClave2026!'
        })
        self.assertEqual(resp.status_code, 302)
        resp = self.client.post(reverse('login'), {
            'username': 'admin_demo',
            'password': 'NuevaClave2026!'
        })
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('dashboard'))

    def test_recovery_codigo_usado_no_reutilizable(self):
        from django.contrib.auth.hashers import make_password
        expires = timezone.now() + timedelta(minutes=10)
        PasswordResetCode.objects.create(
            user=self.user, code_hash=make_password('123456'),
            expires_at=expires, last_sent_at=timezone.now(), used_at=timezone.now()
        )
        session = self.client.session
        session['pr_email'] = 'admin_demo@ejemplo.cl'
        session.save()
        resp = self.client.post(reverse('password_reset_verify'), {
            'code_digit': ['1', '2', '3', '4', '5', '6']
        }, follow=True)
        messages = [str(m) for m in resp.context['messages']]
        self.assertIn('El código no es válido o ha vencido. Solicita uno nuevo.', messages)

    def test_recovery_paso3_sin_verificacion_redirige(self):
        resp = self.client.get(reverse('password_reset_confirm'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('password_reset_request'))

        self.client.login(username='admin_demo', password='Demo2026!')
        resp = self.client.get(reverse('login'))
        self.assertEqual(resp.status_code, 302)
        self.assertEqual(resp['Location'], reverse('dashboard'))
