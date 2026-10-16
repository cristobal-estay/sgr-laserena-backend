from django import forms
from django.contrib import admin
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.utils import timezone
from .models import Task, Activity, Evidence, Employee, TaskReassignment, Benefit, Neighbor, Attention


def _get_employee(request):
    return getattr(request.user, "employee", None)


def _is_jefatura(request):
    emp = _get_employee(request)
    if emp is None or emp.role_id is None:
        return False
    return emp.role.scope in ("authorized", "own_delegation")


def _is_usuario(request):
    emp = _get_employee(request)
    if emp is None or emp.role_id is None:
        return False
    return emp.role.scope == "own_records"


#Admin Pro: Inlines ----------
class EvidenceInline(admin.TabularInline):
    model = Evidence
    extra = 0
    fields = ('image_url', 'is_validated', 'created_at')
    readonly_fields = ('created_at',)


class ActivityInline(admin.TabularInline):
    model = Activity
    extra = 0
    fields = ('name', 'execution_date')


#Admin Pro: validación con clean() ----------
class TaskForm(forms.ModelForm):
    class Meta:
        model = Task
        fields = "__all__"

    def clean(self):
        cleaned_data = super().clean()
        goal = cleaned_data.get("goal")
        due_date = cleaned_data.get("due_date")
        if goal and due_date:
            period = goal.period
            if not (period.start_date <= due_date <= period.end_date):
                raise forms.ValidationError(
                    f"El plazo debe estar dentro del período de la meta "
                    f"({period.start_date:%d/%m/%Y} - {period.end_date:%d/%m/%Y})."
                )
        return cleaned_data


#Admin Pro: acción personalizada ----------
@admin.action(description="Validar evidencias seleccionadas")
def validate_evidences(modeladmin, request, queryset):
    if not request.user.is_superuser and not _is_jefatura(request):
        modeladmin.message_user(
            request,
            "No tienes permiso para validar evidencias (solo Jefatura o superusuario).",
            level=messages.ERROR,
        )
        return
    # update() no dispara auto_now, por eso se actualiza updated_at a mano
    updated = queryset.filter(is_validated=False).update(
        is_validated=True, updated_at=timezone.now()
    )
    modeladmin.message_user(request, f"{updated} evidencia(s) validada(s).")


@admin.register(Employee)
class EmployeeAdmin(admin.ModelAdmin):
    list_display = ('user', 'rut', 'delegation', 'role')
    list_filter = ('delegation', 'role')
    search_fields = ('rut', 'user__username', 'user__first_name', 'user__last_name', 'address')
    list_select_related = ('user', 'delegation')
    ordering = ('user__username',)
    readonly_fields = ('created_at', 'updated_at')

    def get_queryset(self, request):
        qs = super().get_queryset(request)
        if request.user.is_superuser:
            return qs
        if _is_jefatura(request):
            return qs.filter(delegation=request.user.employee.delegation).exclude(user__is_superuser=True)
        return qs.none()

    def save_model(self, request, obj, form, change):
        if not request.user.is_superuser and obj.user_id:
            from django.contrib.auth.models import User
            target = obj.user if hasattr(obj, "user") else None
            if target is None:
                target = User.objects.filter(pk=obj.user_id).first()
            if target is not None and target.is_superuser:
                raise PermissionDenied("No puedes modificar un funcionario de superusuario.")
        super().save_model(request, obj, form, change)

    def has_delete_permission(self, request, obj=None):
        if request.user.is_superuser:
            return super().has_delete_permission(request, obj)
        if obj is not None and getattr(getattr(obj, "user", None), "is_superuser", False):
            return False
        return super().has_delete_permission(request, obj)


@admin.register(Task)
class TaskAdmin(admin.ModelAdmin):
    form = TaskForm
    list_display = ('title', 'goal', 'due_date', 'status', 'assigned_to')
    list_filter = ('status', 'assigned_to')
    search_fields = ('title',)
    list_select_related = ('goal', 'goal__delegation', 'assigned_to')
    ordering = ('due_date',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [ActivityInline]

    # Candado de Seguridad (Scoping): Filtra los datos según el usuario logueado
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Si es superadministrador, ve todo
        if request.user.is_superuser:
            return qs
        # Si es un funcionario normal, solo ve las tareas de su delegación
        if hasattr(request.user, 'employee'):
            qs = qs.filter(goal__delegation=request.user.employee.delegation)
            # Usuario ve solo sus tareas asignadas; Jefatura ve todas las de su delegación
            if _is_usuario(request):
                qs = qs.filter(assigned_to=request.user.employee)
            return qs
        # Si no tiene empleado asociado, no ve nada
        return qs.none()


@admin.register(Activity)
class ActivityAdmin(admin.ModelAdmin):
    list_display = ('name', 'task', 'execution_date')
    list_filter = ('execution_date',)
    search_fields = ('name', 'task__title')
    list_select_related = ('task',)
    ordering = ('-execution_date',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [EvidenceInline]

    # Candado de Seguridad (Scoping): Filtra los datos según el usuario logueado
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Si es superadministrador, ve todo
        if request.user.is_superuser:
            return qs
        # Si es un funcionario normal, solo ve las actividades de su delegación
        if hasattr(request.user, 'employee'):
            qs = qs.filter(task__goal__delegation=request.user.employee.delegation)
            if _is_usuario(request):
                qs = qs.filter(task__assigned_to=request.user.employee)
            return qs
        # Si no tiene empleado asociado, no ve nada
        return qs.none()


@admin.register(Evidence)
class EvidenceAdmin(admin.ModelAdmin):
    list_display = ('activity', 'is_validated', 'created_at')
    list_filter = ('is_validated', 'created_at')
    search_fields = ('activity__name',)
    list_select_related = ('activity',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
    actions = [validate_evidences]

    # Candado de Seguridad (Scoping): Filtra los datos según el usuario logueado
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Si es superadministrador, ve todo
        if request.user.is_superuser:
            return qs
        # Si es un funcionario normal, solo ve las evidencias de su delegación
        if hasattr(request.user, 'employee'):
            qs = qs.filter(activity__task__goal__delegation=request.user.employee.delegation)
            if _is_usuario(request):
                qs = qs.filter(activity__task__assigned_to=request.user.employee)
            return qs
        # Si no tiene empleado asociado, no ve nada
        return qs.none()


@admin.register(TaskReassignment)
class TaskReassignmentAdmin(admin.ModelAdmin):
    list_display = ('task', 'original_employee', 'reassigned_employee', 'reason', 'reassigned_at')
    list_filter = ('reason',)
    search_fields = ('task__title', 'original_employee__rut', 'reassigned_employee__rut')
    list_select_related = ('task', 'original_employee', 'reassigned_employee')
    ordering = ('-reassigned_at',)
    readonly_fields = ('created_at', 'updated_at')

    # Candado de Seguridad (Scoping): Filtra los datos según el usuario logueado
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Si es superadministrador, ve todo
        if request.user.is_superuser:
            return qs
        # Si es un funcionario normal, solo ve las derivaciones de su delegación
        if hasattr(request.user, 'employee'):
            return qs.filter(task__goal__delegation=request.user.employee.delegation)
        # Si no tiene empleado asociado, no ve nada
        return qs.none()

    def has_module_permission(self, request):
        if request.user.is_superuser or _is_jefatura(request):
            return super().has_module_permission(request)
        if _is_usuario(request):
            return False
        return super().has_module_permission(request)


@admin.register(Benefit)
class BenefitAdmin(admin.ModelAdmin):
    list_display = ('employee', 'benefit_type', 'delivery_area', 'delivered_at', 'delivered')
    list_filter = ('benefit_type', 'delivered', 'delivery_area')
    search_fields = ('employee__rut', 'employee__user__username')
    list_select_related = ('employee', 'employee__user', 'delivery_area')
    ordering = ('-delivered_at',)
    readonly_fields = ('created_at', 'updated_at')

    # Candado de Seguridad (Scoping): Filtra los datos según el usuario logueado
    def get_queryset(self, request):
        qs = super().get_queryset(request)
        # Si es superadministrador, ve todo
        if request.user.is_superuser:
            return qs
        # Si es un funcionario normal, solo ve los beneficios de su delegación
        if hasattr(request.user, 'employee'):
            return qs.filter(employee__delegation=request.user.employee.delegation)
        # Si no tiene empleado asociado, no ve nada
        return qs.none()

    def has_module_permission(self, request):
        if request.user.is_superuser or _is_jefatura(request):
            return super().has_module_permission(request)
        if _is_usuario(request):
            return False
        return super().has_module_permission(request)


# ---------- Atención ciudadana: vecinos y atenciones ----------
class AttentionInline(admin.TabularInline):
    """Atenciones del vecino, con enlace a cada una (navegación entre entidades)."""
    model = Attention
    fields = ('number', 'attention_type', 'status', 'created_at')
    readonly_fields = ('number', 'attention_type', 'status', 'created_at')
    extra = 0
    can_delete = False
    show_change_link = True

    def has_add_permission(self, request, obj=None):
        return False


@admin.register(Neighbor)
class NeighborAdmin(admin.ModelAdmin):
    list_display = ('full_name', 'identifier', 'phone', 'email', 'status')
    list_filter = ('status',)
    search_fields = ('full_name', 'identifier', 'email', 'phone')
    ordering = ('full_name',)
    readonly_fields = ('created_at', 'updated_at')
    inlines = [AttentionInline]


@admin.register(Attention)
class AttentionAdmin(admin.ModelAdmin):
    list_display = ('number', 'neighbor', 'delegation', 'attention_type', 'attention_subtype', 'responsible', 'status', 'created_at')
    list_filter = ('status', 'delegation', 'attention_type')
    search_fields = ('number', 'neighbor__full_name', 'neighbor__identifier', 'description', 'responsible__username')
    list_select_related = ('neighbor', 'delegation', 'attention_type', 'attention_subtype', 'responsible')
    autocomplete_fields = ('neighbor',)
    ordering = ('-created_at',)
    readonly_fields = ('created_at', 'updated_at')
