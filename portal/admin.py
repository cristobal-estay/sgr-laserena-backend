from django.contrib import admin

from .models import AuditLog


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ('created_at', 'user', 'action', 'module', 'object_repr', 'ip')
    list_filter = ('action', 'module')
    search_fields = ('user__username', 'action', 'module', 'object_repr', 'detail', 'ip')
    list_select_related = ('user',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at',)
