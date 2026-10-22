import logging
import secrets
import time
from datetime import timedelta

from django.conf import settings
from django.contrib import messages
from django.contrib.auth import login as auth_login, logout as auth_logout
from django.contrib.auth.hashers import check_password
from django.contrib.auth.models import User
from django.contrib.auth.views import LoginView, LogoutView
from django.contrib.auth.password_validation import validate_password
from django.contrib.sessions.models import Session
from django.core.cache import cache
from django.core.exceptions import ValidationError as DjangoValidationError
from django.shortcuts import redirect, render
from django.template.loader import render_to_string
from django.urls import reverse, reverse_lazy
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.generic import TemplateView

from .models import PasswordResetCode

logger = logging.getLogger(__name__)

LOGIN_MAX_ATTEMPTS = 5
LOGIN_LOCKOUT_WINDOW = 10 * 60
CODE_EXPIRY_MINUTES = 10
CODE_RESEND_SECONDS = 45


# ============================================================
# HELPERS DE RECUPERACIÓN DE CONTRASEÑA (compartidos)
# ============================================================

def _find_user(email):
    """Usuario por correo (sin distinguir mayúsculas) o None."""
    if not email:
        return None
    try:
        return User.objects.get(email__iexact=email)
    except User.DoesNotExist:
        return None


def _find_active_user(email):
    try:
        return User.objects.get(email__iexact=email, is_active=True)
    except User.DoesNotExist:
        return None


def _code_ttl_seconds():
    """Vigencia del código de recuperación en segundos (configurable vía .env)."""
    return int(getattr(settings, 'PASSWORD_RESET_CODE_TTL', 120))


def _send_reset_code(user, email):
    """Crea un código nuevo (invalidando los anteriores) y lo envía por correo.

    El código viaja solo dentro del correo; nunca se guarda en claro.
    """
    code = f'{secrets.randbelow(1000000):06d}'
    expires_at = timezone.now() + timedelta(seconds=_code_ttl_seconds())
    PasswordResetCode.create_for_user(user, code, expires_at)

    from django.core.mail import send_mail
    subject = 'Código de recuperación de contraseña - Sistema Municipal'
    message = render_to_string(
        'portal/email/password_reset_code.txt',
        {
            'code': code,
            'minutes': max(1, round(_code_ttl_seconds() / 60)),
            'seconds': _code_ttl_seconds(),
        },
    )
    try:
        send_mail(subject, message, settings.DEFAULT_FROM_EMAIL, [email], fail_silently=False)
    except Exception as e:
        logger.error(f'Error enviando código de recuperación a {email}: {e}')


def _touch_sent(request):
    """Marca en la sesión el momento de envío/reenvío (contadores del paso 2)."""
    now = timezone.now().timestamp()
    request.session['pr_sent_at'] = now
    request.session['pr_exp'] = now + _code_ttl_seconds()


def _reset_context(request, email):
    """Contexto del paso 2: correo enmascarado y contadores calculados en el servidor."""
    now = timezone.now().timestamp()
    sent = request.session.get('pr_sent_at', now)
    exp = request.session.get('pr_exp', now)
    local, _, domain = (email or '').partition('@')
    masked_email = (local[0] + '***') if local else '***'
    if domain:
        masked_email += '@' + domain
    return {
        'email': email,
        'masked_email': masked_email,
        'expires_in': max(0, int(exp - now)),
        'resend_in': max(0, int(CODE_RESEND_SECONDS - (now - sent))),
    }


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
# RECUPERACIÓN DE CONTRASEÑA
# ============================================================

class PasswordResetRequestView(TemplateView):
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

        # La sesión se marca SIEMPRE, exista o no la cuenta: así el paso 2 se
        # comporta igual en ambos casos y no se filtra la existencia de la cuenta.
        request.session['pr_email'] = email
        request.session['pr_verified'] = False
        _touch_sent(request)

        user = _find_active_user(email)
        if user is not None:
            _send_reset_code(user, email)
        return redirect('password_reset_verify')


class PasswordResetVerifyView(TemplateView):
    template_name = 'portal/password_recovery/step2.html'

    def get(self, request, *args, **kwargs):
        email = request.session.get('pr_email')
        if not email:
            return redirect('password_reset_request')
        # Se renderiza igual exista o no la cuenta: sin usuario/código el
        # contexto muestra el correo enmascarado y contadores neutros.
        return render(request, self.template_name, _reset_context(request, email))

    def post(self, request, *args, **kwargs):
        email = request.session.get('pr_email')
        if not email:
            return redirect('password_reset_request')

        user = _find_user(email)
        code_obj = None
        if user is not None:
            code_obj = PasswordResetCode.objects.filter(
                user=user
            ).order_by('-created_at').first()

        entered = ''.join(d.strip() for d in request.POST.getlist('code_digit') if d.strip())

        # Sin código utilizable (cuenta inexistente o código usado/vencido/sin
        # intentos): respuesta equivalente para no filtrar información.
        if (
            code_obj is None
            or code_obj.is_used()
            or code_obj.is_expired()
            or code_obj.attempts >= code_obj.max_attempts
        ):
            messages.error(request, 'El código no es válido o ha vencido. Solicita uno nuevo.')
            return render(request, self.template_name, _reset_context(request, email))

        if not check_password(entered, code_obj.code_hash):
            code_obj.attempts += 1
            code_obj.save(update_fields=['attempts'])
            if code_obj.attempts >= code_obj.max_attempts:
                messages.error(request, 'El código no es válido o ha vencido. Solicita uno nuevo.')
            else:
                messages.error(request, 'Código incorrecto. Verifica e inténtalo de nuevo.')
            return render(request, self.template_name, _reset_context(request, email))

        # Código correcto: marcamos la sesión como verificada
        request.session['pr_email'] = email
        request.session['pr_verified'] = True
        request.session['pr_verified_at'] = int(time.time())
        return redirect('password_reset_confirm')


class PasswordResetResendView(TemplateView):
    """Reenvío del código de verificación (paso 2).

    La espera mínima de 45 s la impone el servidor usando last_sent_at real
    del último código. Responde de forma equivalente exista o no la cuenta.
    """

    def post(self, request, *args, **kwargs):
        email = request.session.get('pr_email')
        if not email:
            return redirect('password_reset_request')

        user = _find_user(email)
        now = timezone.now()

        if user is not None:
            code = PasswordResetCode.objects.filter(
                user=user
            ).order_by('-created_at').first()
            # Puerta de 45 s impuesta por el servidor.
            if code is not None and (now - code.last_sent_at).total_seconds() < CODE_RESEND_SECONDS:
                messages.error(
                    request,
                    'Debes esperar unos segundos antes de volver a enviar el código.'
                )
                return render(
                    request,
                    'portal/password_recovery/step2.html',
                    _reset_context(request, email),
                )
            _send_reset_code(user, email)

        # Reinicia los contadores de la sesión en todos los casos (equivalente).
        _touch_sent(request)
        return redirect('password_reset_verify')


class PasswordResetConfirmView(TemplateView):
    template_name = 'portal/password_recovery/step3.html'

    def get(self, request, *args, **kwargs):
        if not self._is_verified(request):
            return redirect('password_reset_request')
        email = request.session.get('pr_email', '')
        return render(request, self.template_name, {'email': email})

    def post(self, request, *args, **kwargs):
        if not self._is_verified(request):
            return redirect('password_reset_request')

        email = request.session.get('pr_email', '')
        user = _find_user(email)
        if user is None:
            request.session.pop('pr_email', None)
            request.session.pop('pr_verified', None)
            return redirect('password_reset_request')

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
            return render(request, self.template_name, {'errors': errors, 'email': email})

        user.set_password(new_password)
        user.save()
        PasswordResetCode.objects.filter(user=user, used_at__isnull=True).update(used_at=timezone.now())

        for session in Session.objects.filter(expire_date__gt=timezone.now()):
            data = session.get_decoded()
            if str(data.get('_auth_user_id', '')) == str(user.id):
                session.delete()

        for key in ['pr_email', 'pr_verified', 'pr_verified_at', 'pr_sent_at', 'pr_exp']:
            request.session.pop(key, None)

        messages.success(request, 'Contraseña actualizada correctamente. Inicia sesión con tu nueva contraseña.')
        return redirect('login')

    def _is_verified(self, request):
        if not request.session.get('pr_verified'):
            return False
        verified_at = request.session.get('pr_verified_at', 0)
        if int(time.time()) - verified_at > CODE_EXPIRY_MINUTES * 60:
            return False
        return True


