
import re
from unittest import mock

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.core import mail
from django.core.cache import cache
from django.test import TestCase, Client, override_settings
from django.urls import reverse
from django.utils.encoding import force_bytes
from django.utils.http import urlsafe_base64_encode

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
    """Recuperación por enlace con token seguro (Evaluación 3).

    Flujo: solicitar con el correo -> correo con enlace -> abrir enlace
    (valida token) -> nueva contraseña -> confirmación -> login con la nueva.
    """

    LINK_RE = re.compile(r'https?://[^\s"<]+/recuperar/enlace/[^\s"<]+/')

    def setUp(self):
        cache.clear()
        self.client = Client()
        self.user = User.objects.create_user(
            username='admin_demo',
            email='admin_demo@ejemplo.cl',
            password='Demo2026!',
            first_name='Admin',
        )

    def _request(self, email='admin_demo@ejemplo.cl'):
        return self.client.post(reverse('password_reset_request'), {'email': email})

    def _link_from_mail(self, index=-1):
        body = mail.outbox[index].body
        match = self.LINK_RE.search(body)
        self.assertIsNotNone(match, body)
        return match.group(0)

    def _path(self, link):
        return link.split('://', 1)[1].split('/', 1)[1].join(['/', ''])

    def _open_link(self, link):
        return self.client.get(self._path(link))

    def _set_password(self, password='NuevaClave2026', confirm=None):
        return self.client.post(reverse('password_reset_confirm'), {
            'new_password': password,
            'confirm_password': confirm if confirm is not None else password,
        })

    # --- Paso 1 y 2: solicitud y correo -------------------------------------

    def test_correo_inexistente_misma_respuesta_y_sin_correo(self):
        resp = self._request('noexiste@ejemplo.cl')
        self.assertRedirects(resp, reverse('password_reset_sent'))
        resp = self.client.get(reverse('password_reset_sent'))
        self.assertContains(resp, 'n***@ejemplo.cl')
        self.assertEqual(len(mail.outbox), 0)

    def test_correo_invalido_muestra_error(self):
        resp = self._request('sin-arroba')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Ingresa un correo válido')

    def test_envia_correo_con_enlace_y_token(self):
        resp = self._request('ADMIN_DEMO@ejemplo.cl')
        self.assertRedirects(resp, reverse('password_reset_sent'))
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.to, ['admin_demo@ejemplo.cl'])
        link = self._link_from_mail()
        uid = urlsafe_base64_encode(force_bytes(self.user.pk))
        self.assertIn(f'/recuperar/enlace/{uid}/', link)
        # Versión HTML con el mismo enlace (botón).
        html, mimetype = message.alternatives[0]
        self.assertEqual(mimetype, 'text/html')
        self.assertIn(link, html)

    def test_cuenta_inactiva_no_recibe_correo(self):
        self.user.is_active = False
        self.user.save()
        self._request()
        self.assertEqual(len(mail.outbox), 0)

    @override_settings(SITE_URL='http://sgr.ejemplo.cl')
    def test_site_url_define_el_dominio_del_enlace(self):
        self._request()
        self.assertTrue(self._link_from_mail().startswith('http://sgr.ejemplo.cl/recuperar/enlace/'))

    def test_reenvio_antes_de_45s_rechazado_y_despues_ok(self):
        self._request()
        resp = self.client.post(reverse('password_reset_resend'), follow=True)
        self.assertIn(
            'Debes esperar unos segundos antes de volver a enviar el enlace.',
            [str(m) for m in resp.context['messages']],
        )
        self.assertEqual(len(mail.outbox), 1)
        # Simula que pasaron 60 s desde el último envío.
        session = self.client.session
        session['pr_sent_at'] -= 60
        session.save()
        cache.clear()
        self.client.post(reverse('password_reset_resend'))
        self.assertEqual(len(mail.outbox), 2)

    # --- Paso 3: validar token ----------------------------------------------

    def test_enlace_valido_pasa_al_formulario_sin_token_en_la_url(self):
        self._request()
        resp = self._open_link(self._link_from_mail())
        self.assertRedirects(resp, reverse('password_reset_confirm'))
        resp = self.client.get(reverse('password_reset_confirm'))
        self.assertContains(resp, 'Crear nueva contraseña')
        self.assertContains(resp, 'admin_demo@ejemplo.cl')

    def test_token_alterado_es_rechazado(self):
        self._request()
        link = self._link_from_mail()
        resp = self._open_link(link[:-6] + 'xxxxx/')
        self.assertEqual(resp.status_code, 200)
        self.assertContains(resp, 'Enlace no válido o vencido')
        resp = self.client.get(reverse('password_reset_confirm'))
        self.assertContains(resp, 'Enlace no válido o vencido')

    def test_uid_inexistente_es_rechazado(self):
        token = default_token_generator.make_token(self.user)
        resp = self.client.get(reverse('password_reset_link', args=['OTk5OTk', token]))
        self.assertContains(resp, 'Enlace no válido o vencido')

    @override_settings(PASSWORD_RESET_TIMEOUT=60)
    def test_token_vencido_es_rechazado(self):
        self._request()
        link = self._link_from_mail()
        future = default_token_generator._now().timestamp() + 120
        with mock.patch.object(default_token_generator, '_now') as fake_now:
            from datetime import datetime

            fake_now.return_value = datetime.fromtimestamp(future)
            resp = self._open_link(link)
        self.assertContains(resp, 'Enlace no válido o vencido')

    def test_formulario_sin_enlace_muestra_invalido(self):
        resp = self.client.get(reverse('password_reset_confirm'))
        self.assertContains(resp, 'Enlace no válido o vencido')
        resp = self._set_password()
        self.assertContains(resp, 'Enlace no válido o vencido')

    # --- Paso 3 y 4: nueva contraseña y confirmación ------------------------

    def test_contrasena_debil_o_distinta_rechazada(self):
        self._request()
        self._open_link(self._link_from_mail())
        resp = self._set_password('corta')
        self.assertContains(resp, 'al menos 8 caracteres')
        resp = self._set_password('NuevaClave2026', confirm='OtraClave2026')
        self.assertContains(resp, 'Las contraseñas no coinciden.')
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('Demo2026!'))

    def test_flujo_completo_y_login_con_la_nueva_clave(self):
        # 1. Solicita la recuperación.
        self._request()
        # 2. Recibe el correo con el enlace y lo abre (valida el token).
        link = self._link_from_mail()
        self._open_link(link)
        # 3. Define la nueva contraseña.
        resp = self._set_password()
        self.assertRedirects(
            resp, reverse('password_reset_complete'), fetch_redirect_response=False,
        )
        # 4. Confirmación del cambio (pantalla + correo de aviso).
        resp = self.client.get(reverse('password_reset_complete'))
        self.assertContains(resp, 'Contraseña actualizada')
        self.assertEqual(mail.outbox[-1].subject, 'Tu contraseña fue actualizada - Sistema Municipal')
        # 5. Ingresa con la nueva contraseña (y la antigua ya no sirve).
        self.user.refresh_from_db()
        self.assertTrue(self.user.check_password('NuevaClave2026'))
        self.assertFalse(self.client.login(username='admin_demo', password='Demo2026!'))
        resp = self.client.post(reverse('login'), {
            'username': 'admin_demo', 'password': 'NuevaClave2026',
        })
        self.assertEqual(resp.status_code, 302)

    def test_enlace_de_un_solo_uso(self):
        self._request()
        link = self._link_from_mail()
        self._open_link(link)
        self._set_password()
        # Volver a abrir el mismo enlace ya no sirve: el token cambió con la clave.
        resp = self._open_link(link)
        self.assertContains(resp, 'Enlace no válido o vencido')

    def test_confirmacion_sin_cambio_redirige_al_login(self):
        resp = self.client.get(reverse('password_reset_complete'))
        self.assertRedirects(resp, reverse('login'))

    def test_usuario_autenticado_no_ve_recuperacion(self):
        self.client.login(username='admin_demo', password='Demo2026!')
        resp = self.client.get(reverse('password_reset_request'))
        self.assertEqual(resp.status_code, 302)
