from django import forms
from django.contrib import admin
from .models import (
    AttentionSubtype,
    AttentionType,
    Delegation,
    Period,
    InstitutionalGoal,
    Achievement,
    MeasurementItem,
    ProjectItem,
    Role,
    RolePermission,
)


# ---------- Admin Pro: validación con clean() ----------
class PeriodForm(forms.ModelForm):
    class Meta:
        model = Period
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        start = cleaned_data.get("start_date")
        end = cleaned_data.get("end_date")
        if start and end and end < start:
            raise forms.ValidationError(
                "La fecha de término no puede ser anterior a la fecha de inicio."
            )
        return cleaned_data


@admin.register(Delegation)
class DelegationAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'commune', 'status', 'color', 'created_at', 'updated_at')
    list_editable = ('color', 'status')
    list_filter = ('status', 'commune')
    search_fields = ('name', 'code', 'commune')
    ordering = ('code', 'name')
    readonly_fields = ('created_at', 'updated_at')


class RolePermissionInline(admin.TabularInline):
    model = RolePermission
    extra = 0
    fields = ('module', 'action')


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'scope', 'status', 'is_system')
    list_filter = ('scope', 'status', 'is_system')
    search_fields = ('name', 'code')
    ordering = ('code',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [RolePermissionInline]


@admin.register(RolePermission)
class RolePermissionAdmin(admin.ModelAdmin):
    list_display = ('role', 'module', 'action')
    list_filter = ('module', 'action', 'role')
    search_fields = ('role__name', 'role__code', 'module', 'action')
    list_select_related = ('role',)
    ordering = ('role__code', 'module', 'action')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Period)
class PeriodAdmin(admin.ModelAdmin):
    form = PeriodForm
    list_display = ('name', 'quarter', 'start_date', 'end_date', 'status')
    list_filter = ('status', 'quarter')
    search_fields = ('name',)
    ordering = ('-start_date',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(InstitutionalGoal)
class InstitutionalGoalAdmin(admin.ModelAdmin):
    list_display = ('name', 'delegation', 'weight', 'period')
    list_filter = ('period', 'delegation')
    search_fields = ('name',)
    # list_select_related optimiza la BD al traer las FK de una sola vez 
    list_select_related = ('delegation', 'period')
    ordering = ('-period__start_date', 'name')
    readonly_fields = ('created_at', 'updated_at')


@admin.register(Achievement)
class AchievementAdmin(admin.ModelAdmin):
    list_display = ('goal', 'percentage', 'updated_at')
    list_filter = ('goal__delegation',)
    search_fields = ('goal__name',)
    list_select_related = ('goal',)
    ordering = ('-updated_at',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(MeasurementItem)
class MeasurementItemAdmin(admin.ModelAdmin):
    list_display = ('name', 'goal', 'unit_of_measure', 'baseline', 'target_value')
    list_filter = ('goal__delegation',)
    search_fields = ('name',)
    list_select_related = ('goal',)
    ordering = ('name',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(ProjectItem)
class ProjectItemAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'status')
    list_filter = ('status',)
    search_fields = ('code', 'name')
    ordering = ('code',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AttentionType)
class AttentionTypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'status')
    list_filter = ('status',)
    search_fields = ('code', 'name')
    ordering = ('code',)
    readonly_fields = ('created_at', 'updated_at')


@admin.register(AttentionSubtype)
class AttentionSubtypeAdmin(admin.ModelAdmin):
    list_display = ('code', 'name', 'attention_type', 'status')
    list_filter = ('status', 'attention_type')
    search_fields = ('code', 'name')
    list_select_related = ('attention_type',)
    ordering = ('code',)
    readonly_fields = ('created_at', 'updated_at')