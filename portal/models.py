from django.contrib.auth.hashers import make_password
from django.contrib.auth.models import User
from django.db import models
from django.utils import timezone


class PasswordResetCode(models.Model):
    """Código temporal de recuperación de contraseña.
    El código en claro NUNCA se guarda: solo su hash.
    """
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='password_reset_codes', verbose_name='Usuario')
    code_hash = models.CharField(max_length=128, verbose_name='Hash del código')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')
    expires_at = models.DateTimeField(verbose_name='Fecha de expiración')
    attempts = models.PositiveIntegerField(default=0, verbose_name='Intentos fallidos')
    max_attempts = models.PositiveIntegerField(default=3, verbose_name='Máximo de intentos')
    used_at = models.DateTimeField(null=True, blank=True, verbose_name='Fecha de uso')
    last_sent_at = models.DateTimeField(default=timezone.now, verbose_name='Último envío')

    class Meta:
        verbose_name = 'Código de recuperación'
        verbose_name_plural = 'Códigos de recuperación'
        db_table = 'portal_password_reset_code'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['user', 'expires_at'], name='idx_codigo_recup_user_exp'),
        ]

    def __str__(self):
        return f'Código para {self.user.username} ({"usado" if self.used_at else "pendiente"})'

    def is_expired(self):
        from django.utils import timezone
        return timezone.now() > self.expires_at

    def is_used(self):
        return self.used_at is not None

    def is_valid(self):
        """Válido = no usado, no expirado y con intentos disponibles."""
        if self.is_used() or self.is_expired():
            return False
        return self.attempts < self.max_attempts

    @classmethod
    def create_for_user(cls, user, code, expires_at, last_sent_at=None):
        """Crea un nuevo código: invalida los anteriores del usuario."""
        from django.conf import settings
        from django.utils import timezone
        cls.objects.filter(user=user).update(used_at=timezone.now())
        return cls.objects.create(
            user=user,
            code_hash=make_password(code),
            expires_at=expires_at,
            last_sent_at=last_sent_at or timezone.now(),
            max_attempts=getattr(settings, 'PASSWORD_RESET_MAX_ATTEMPTS', 5),
        )


class AuditLog(models.Model):
    """Registro de auditoría de accesos y acciones relevantes del portal."""
    user = models.ForeignKey(
        'auth.User', on_delete=models.SET_NULL, null=True, blank=True,
        related_name='audit_logs', verbose_name='Usuario',
    )
    action = models.CharField(max_length=50, verbose_name='Acción')
    module = models.CharField(max_length=50, blank=True, default='', verbose_name='Módulo')
    object_repr = models.CharField(max_length=200, blank=True, default='', verbose_name='Objeto')
    detail = models.TextField(blank=True, default='', verbose_name='Detalle')
    ip = models.CharField(max_length=45, blank=True, default='', verbose_name='IP')
    created_at = models.DateTimeField(auto_now_add=True, verbose_name='Fecha de creación')

    class Meta:
        verbose_name = 'Registro de auditoría'
        verbose_name_plural = 'Registros de auditoría'
        db_table = 'portal_audit_log'
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['created_at'], name='idx_auditoria_fecha'),
            models.Index(fields=['user', 'created_at'], name='idx_auditoria_user_fecha'),
        ]

    def __str__(self):
        user = self.user.username if self.user_id else 'anónimo'
        return f'{user}: {self.action} ({self.module or "-"})'

