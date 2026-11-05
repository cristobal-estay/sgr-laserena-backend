import logging

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.models import User
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.contrib.auth.views import LoginView, LogoutView
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.core.mail import EmailMultiAlternatives
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import url_has_allowed_host_and_scheme, urlsafe_base64_decode, urlsafe_base64_encode
from django.views.generic import TemplateView

logger = logging.getLogger(__name__)

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW = 10 * 60
#: Espera mínima entre dos envíos del enlace de recuperación (segundos).
LINK_RESEND_SECONDS = 45

#: Claves de sesión del flujo de recuperación.
SESSION_EMAIL = 'pr_email'
SESSION_SENT_AT = 'pr_sent_at'
SESSION_RESET_UID = 'pr_reset_uid'
SESSION_RESET_TOKEN = 'pr_reset_token'
RESET_SESSION_KEYS = (SESSION_EMAIL, SESSION_SENT_AT, SESSION_RESET_UID, SESSION_RESET_TOKEN)


# ============================================================
# HELPERS DE RECUPERACIÓN DE CONTRASEÑA (enlace + token)
# ============================================================
#
# Flujo (Evaluación 3):
#   1. El usuario ingresa su correo (/recuperar/).
#   2. Si la cuenta existe y está activa, se genera un TOKEN SEGURO con
#      ``default_token_generator`` de Django (HMAC-SHA256 con SECRET_KEY, que
#      incluye el id, el hash de la contraseña y el último login: deja de
#      servir apenas se cambia la clave) y se envía por correo un ENLACE
#      /recuperar/enlace/<uid>/<token>/.
#   3. Al abrir el enlace se VALIDA el token (y su vigencia,
#      PASSWORD_RESET_TIMEOUT). Si es válido se guarda en la sesión y se
#      redirige a /recuperar/nueva-clave/ (así el token no queda en la URL).
#   4. El usuario define la nueva contraseña (validadores de Django).
#   5. Se confirma el cambio (/recuperar/listo/) y se avisa por correo.
# La respuesta es la misma exista o no la cuenta (no se filtra información).


def _find_active_user(email):
    try:
        return User.objects.get(email__iexact=email, is_active=True)
    except (User.DoesNotExist, User.MultipleObjectsReturned):
        return None


def _reset_timeout_minutes():
    return max(1, round(int(settings.PASSWORD_RESET_TIMEOUT) / 60))


def _absolute_url(request, path):
    """URL absoluta del enlace: SITE_URL (si está definido) o el host actual."""
    base = getattr(settings, 'SITE_URL', '').rstrip('/')
    if base:
        return f'{base}{path}'
    return request.build_absolute_uri(path)


def build_reset_link(request, user):
    """Genera uid + token seguro y devuelve el enlace absoluto de recuperación."""
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    path = reverse('password_reset_link', kwargs={'uidb64': uid, 'token': token})
    return _absolute_url(request, path)


def _send_email(subject, template_base, context, to):
    """Envía un correo en texto + HTML. Los errores quedan en el log."""
    text = render_to_string(f'portal/email/{template_base}.txt', context)
    html = render_to_string(f'portal/email/{template_base}.html', context)
    message = EmailMultiAlternatives(subject, text, settings.DEFAULT_FROM_EMAIL, [to])
    message.attach_alternative(html, 'text/html')
    try:
        message.send(fail_silently=False)
    except Exception as exc:  # noqa: BLE001 (SMTP caído, credenciales, etc.)
        logger.error('Error enviando correo "%s" a %s: %s', subject, to, exc)
        return False
    return True


def send_reset_link(request, user):
    """Envía el correo con el enlace de recuperación al usuario."""
    context = {
        'user': user,
        'name': user.get_full_name() or user.username,
        'reset_link': build_reset_link(request, user),
        'minutes': _reset_timeout_minutes(),
    }
    return _send_email(
        'Recupera tu contraseña - Sistema Municipal', 'password_reset_link', context, user.email,
    )


def _user_from_uid(uidb64):
    try:
        pk = force_str(urlsafe_base64_decode(uidb64))
        return User.objects.get(pk=pk, is_active=True)
    except (TypeError, ValueError, OverflowError, User.DoesNotExist):
        return None


def _masked(email):
    local, _, domain = (email or '').partition('@')
    masked = (local[0] + '***') if local else '***'
    return f'{masked}@{domain}' if domain else masked


def _clear_reset_session(request):
    for key in RESET_SESSION_KEYS:
        request.session.pop(key, None)


# ============================================================
# LOGIN
# ============================================================

class PortalLoginView(LoginView):
    template_name = 'portal/login.html'
    redirect_authenticated_user = True

    def get_success_url(self):
        url = self.get_redirect_url()
        if url and url_has_allowed_host_and_scheme(
            url, allowed_hosts={self.request.get_host()}, require_https=self.request.is_secure()
        ):
            return url
        return reverse('dashboard')

    def post(self, request, *args, **kwargs):
        # Bloqueo por intentos ANTES de autenticar: aunque la clave sea
        # correcta, una cuenta bloqueada no puede iniciar sesión.
        username = request.POST.get('username', '').strip()
        if self._is_locked_out(username):
            messages.error(
                request,
                'Has superado el límite de intentos. Espera 10 minutos antes de volver a intentar.'
            )
            return redirect('login')
        return super().post(request, *args, **kwargs)

    def form_valid(self, form):
        user = form.get_user()
        if not user.is_active:
            messages.warning(
                self.request,
                'Tu cuenta está inactiva. Comunícate con el coordinador o el delegado de tu delegación.'
            )
            return redirect('login')
        cache_key = self._cache_key(self.request.POST.get('username', ''))
        cache.delete(cache_key)
        auth_login(self.request, user)
        return redirect(self.get_success_url())

    def form_invalid(self, form):
        username = self.request.POST.get('username', '').strip()
        password = self.request.POST.get('password', '')

        user = self._find_user(username)
        if user is not None and not user.is_active and user.check_password(password):
            messages.warning(
                self.request,
                'Tu cuenta está inactiva. Comunícate con el coordinador o el delegado de tu delegación.'
            )
            return redirect('login')

        cache_key = self._cache_key(username)
        attempts = cache.get(cache_key, 0) + 1
        cache.set(cache_key, attempts, LOGIN_LOCKOUT_WINDOW)

        if attempts >= LOGIN_MAX_ATTEMPTS:
            messages.error(
                self.request,
                'Has superado el límite de intentos. Espera 10 minutos antes de volver a intentar.'
            )
            return redirect('login')

        messages.error(self.request, 'El usuario o la contraseña no son correctos.')
        return redirect('login')

    def _is_locked_out(self, username):
        return cache.get(self._cache_key(username), 0) >= LOGIN_MAX_ATTEMPTS

    def _cache_key(self, username):
        ip = self.request.META.get('REMOTE_ADDR', 'unknown')
        return f'login_attempts:{ip}:{username.lower()}'

    def _find_user(self, username):
        if not username:
            return None
        if '@' in username:
            try:
                return User.objects.get(email__iexact=username)
            except User.DoesNotExist:
                return None
        try:
            return User.objects.get(username__iexact=username)
        except User.DoesNotExist:
            return None


class PortalLogoutView(LogoutView):
    next_page = reverse_lazy('login')

    def post(self, request, *args, **kwargs):
        auth_logout(request)
        return redirect(self.next_page)


# ============================================================
# RECUPERACIÓN DE CONTRASEÑA (enlace con token)
# ============================================================

class PasswordResetRequestView(TemplateView):
    """Paso 1: solicitar la recuperación con el correo de la cuenta."""

    template_name = 'portal/password_recovery/step1.html'

    def get(self, request, *args, **kwargs):
        if request.user.is_authenticated:
            return redirect('dashboard')
        return super().get(request, *args, **kwargs)

    def post(self, request, *args, **kwargs):
        email = request.POST.get('email', '').strip().lower()
        errors = {}
        if not email:
            errors['email'] = 'Ingresa tu correo electrónico.'
        elif '@' not in email or '.' not in email.split('@')[-1]:
            errors['email'] = 'Ingresa un correo válido, por ejemplo nombre@dominio.cl.'
        if errors:
            return render(request, self.template_name, {'errors': errors, 'email': email})

        # La sesión se marca SIEMPRE, exista o no la cuenta: el paso 2 se ve
        # igual en ambos casos y no se filtra la existencia de la cuenta.
        request.session[SESSION_EMAIL] = email
        request.session[SESSION_SENT_AT] = timezone.now().timestamp()

        user = _find_active_user(email)
        if user is not None:
            send_reset_link(request, user)
        return redirect('password_reset_sent')


class PasswordResetSentView(TemplateView):
    """Paso 2: "Revisa tu correo" (con reenvío limitado en el servidor)."""

    template_name = 'portal/password_recovery/step2.html'

    def get(self, request, *args, **kwargs):
        email = request.session.get(SESSION_EMAIL)
        if not email:
            return redirect('password_reset_request')
        now = timezone.now().timestamp()
        sent = request.session.get(SESSION_SENT_AT, now)
        return render(request, self.template_name, {
            'masked_email': _masked(email),
            'minutes': _reset_timeout_minutes(),
            'resend_in': max(0, int(LINK_RESEND_SECONDS - (now - sent))),
        })


class PasswordResetResendView(TemplateView):
    """Reenvía el enlace (solo POST). Espera mínima de 45 s impuesta en el servidor."""

    def get(self, request, *args, **kwargs):
        return redirect('password_reset_sent')

    def post(self, request, *args, **kwargs):
        email = request.session.get(SESSION_EMAIL)
        if not email:
            return redirect('password_reset_request')
        now = timezone.now().timestamp()
        sent = request.session.get(SESSION_SENT_AT, 0)
        throttle_key = f'sgr_reset_link_{email}'
        if now - sent < LINK_RESEND_SECONDS or cache.get(throttle_key):
            messages.error(request, 'Debes esperar unos segundos antes de volver a enviar el enlace.')
            return redirect('password_reset_sent')
        cache.set(throttle_key, True, LINK_RESEND_SECONDS)
        request.session[SESSION_SENT_AT] = now
        user = _find_active_user(email)
        if user is not None:
            send_reset_link(request, user)
        messages.success(request, 'Si el correo está registrado, enviamos un nuevo enlace.')
        return redirect('password_reset_sent')


class PasswordResetLinkView(TemplateView):
    """Abre el enlace del correo: valida uid + token y pasa al formulario.

    Igual que la vista de Django, el token se guarda en la sesión y se
    redirige a una URL sin token, para que no quede en el historial ni se
    filtre por la cabecera Referer.
    """

    template_name = 'portal/password_recovery/invalid_link.html'

    def get(self, request, uidb64, token, *args, **kwargs):
        user = _user_from_uid(uidb64)
        if user is None or not default_token_generator.check_token(user, token):
            return render(request, self.template_name, status=200)
        request.session[SESSION_RESET_UID] = uidb64
        request.session[SESSION_RESET_TOKEN] = token
        return redirect('password_reset_confirm')


class PasswordResetConfirmView(TemplateView):
    """Paso 3: definir la nueva contraseña (token revalidado en cada request)."""

    template_name = 'portal/password_recovery/step3.html'

    def _user_with_valid_token(self, request):
        uidb64 = request.session.get(SESSION_RESET_UID)
        token = request.session.get(SESSION_RESET_TOKEN)
        if not uidb64 or not token:
            return None
        user = _user_from_uid(uidb64)
        if user is None or not default_token_generator.check_token(user, token):
            return None
        return user

    def get(self, request, *args, **kwargs):
        user = self._user_with_valid_token(request)
        if user is None:
            _clear_reset_session(request)
            return render(request, 'portal/password_recovery/invalid_link.html')
        return render(request, self.template_name, {'email': user.email})

    def post(self, request, *args, **kwargs):
        user = self._user_with_valid_token(request)
        if user is None:
            _clear_reset_session(request)
            return render(request, 'portal/password_recovery/invalid_link.html')

        new_password = request.POST.get('new_password', '')
        confirm_password = request.POST.get('confirm_password', '')

        errors = {}
        if not new_password:
            errors['new_password'] = 'Ingresa una nueva contraseña.'
        elif len(new_password) < 8:
            errors['new_password'] = 'La contraseña debe tener al menos 8 caracteres.'
        elif not any(c.isupper() for c in new_password):
            errors['new_password'] = 'La contraseña debe tener al menos una mayúscula.'
        elif not any(c.islower() for c in new_password):
            errors['new_password'] = 'La contraseña debe tener al menos una minúscula.'
        elif not any(c.isdigit() for c in new_password):
            errors['new_password'] = 'La contraseña debe tener al menos un número.'
        if new_password != confirm_password:
            errors['confirm_password'] = 'Las contraseñas no coinciden.'
        if not errors:
            try:
                validate_password(new_password, user)
            except DjangoValidationError as e:
                errors['new_password'] = ' '.join(e.messages)
        if errors:
            return render(request, self.template_name, {'errors': errors, 'email': user.email})

        # Al cambiar el hash de la contraseña, el token deja de ser válido (un
        # solo uso) y Django cierra las demás sesiones abiertas del usuario.
        user.set_password(new_password)
        user.save()
        _clear_reset_session(request)
        _send_email(
            'Tu contraseña fue actualizada - Sistema Municipal', 'password_changed',
            {'name': user.get_full_name() or user.username,
             'login_url': _absolute_url(request, reverse('login'))},
            user.email,
        )
        request.session['pr_done'] = True
        return redirect('password_reset_complete')


class PasswordResetCompleteView(TemplateView):
    """Paso 4: confirmación del cambio exitoso."""

    template_name = 'portal/password_recovery/step4.html'

    def get(self, request, *args, **kwargs):
        if not request.session.pop('pr_done', False):
            return redirect('login')
        return super().get(request, *args, **kwargs)
