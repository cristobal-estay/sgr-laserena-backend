from django.db import models


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

