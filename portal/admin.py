from django.contrib import admin

from .models import AuditLog, PasswordResetCode


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'action', 'module', 'object_repr', 'ip')
    list_filter = ('action', 'module')
    search_fields = ('user__username', 'action', 'module', 'object_repr', 'detail', 'ip')
    list_select_related = ('user',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)


@admin.register(PasswordResetCode)
class PasswordResetCodeAdmin(admin.ModelAdmin):
    list_display = ('user', 'created_at', 'expires_at', 'attempts', 'used_at')
    search_fields = ('user__username', 'user__email')
    list_select_related = ('user',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
