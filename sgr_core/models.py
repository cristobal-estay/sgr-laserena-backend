from django.db import models

from .roles import ACTIONS, MODULES, SCOPES, SCOPE_RANKS

DELEGATION_STATUS_CHOICES = [("Activa", "Activa"), ("Inactiva", "Inactiva")]
ROLE_STATUS_CHOICES = [("Activo", "Activo"), ("Inactivo", "Inactivo")]
CATALOG_STATUS_CHOICES = [("Activo", "Activo"), ("Inactivo", "Inactivo")]

class AliveQuerySet(models.QuerySet):
    """QuerySet que excluye registros con borrado lógico."""

    def alive(self):
        return self.filter(deleted_at__isnull=True)


class AliveManager(models.Manager):
    """Manager adicional que excluye registros con deleted_at no nulo."""

    def get_queryset(self):
        return AliveQuerySet(self.model, using=self._db).filter(deleted_at__isnull=True)


class BaseModel(models.Model):
    created_at = models.DateTimeField(auto_now_add=True, verbose_name="Fecha de creación")
    updated_at = models.DateTimeField(auto_now=True, verbose_name="Última modificación")
    deleted_at = models.DateTimeField(null=True, blank=True, verbose_name="Fecha de eliminación")

    # El manager por defecto no cambia (no altera el Admin ni el código
    # existente); "alive" es un manager adicional con borrado lógico.
    objects = models.Manager()
    alive = AliveManager()

    class Meta:
        abstract = True

class Delegation(BaseModel):
    name = models.CharField(max_length=50, verbose_name="Nombre de Delegación")
    code = models.CharField(max_length=8, unique=True, verbose_name="Código")
    commune = models.CharField(max_length=80, default="La Serena", verbose_name="Comuna")
    address = models.CharField(max_length=200, blank=True, default="", verbose_name="Dirección")
    status = models.CharField(max_length=10, choices=DELEGATION_STATUS_CHOICES, default="Activa", verbose_name="Estado")
    description = models.TextField(blank=True, null=True, verbose_name="Descripción")
    color = models.CharField(max_length=7, blank=True, default="", help_text="Código hex, ej: #E63946", verbose_name="Color distintivo")

    class Meta:
        verbose_name = "Delegación"
        verbose_name_plural = "Delegaciones"
        db_table = "delegacion"

    def __str__(self):
        return self.name

    @property
    def is_active(self):
        return self.status == "Activa"

class Role(BaseModel):
    code = models.CharField(max_length=8, unique=True, verbose_name="Código")
    name = models.CharField(max_length=50, verbose_name="Nombre del Rol")
    description = models.TextField(blank=True, default="", verbose_name="Descripción")
    scope = models.CharField(max_length=20, choices=SCOPES, default="own_records", verbose_name="Alcance")
    status = models.CharField(max_length=10, choices=ROLE_STATUS_CHOICES, default="Activo", verbose_name="Estado")
    is_system = models.BooleanField(default=False, verbose_name="Rol de sistema")
    #: Grupo de Django del rol (Evaluación 3): recibe los permisos de la
    #: matriz y agrupa a los usuarios con este rol. Ver ``sgr_core.groups``.
    group = models.OneToOneField(
        "auth.Group", on_delete=models.SET_NULL, null=True, blank=True,
        related_name="sgr_role", verbose_name="Grupo de Django",
    )

    class Meta:
        verbose_name = "Rol"
        verbose_name_plural = "Roles"
        db_table = "rol"

    def __str__(self):
        return f"{self.code} - {self.name}"

    @property
    def rank(self):
        """Rango derivado del alcance: all=3, authorized=2, own_delegation=1, own_records=0."""
        return SCOPE_RANKS.get(self.scope, 0)

    @property
    def scope_label(self):
        """Alcance en texto para el usuario (es-cl), por ejemplo 'Todas las delegaciones'."""
        return dict(SCOPES).get(self.scope, self.scope)

    @property
    def enabled_modules_count(self):
        """Cantidad de módulos con al menos un permiso asignado.

        Property de solo lectura: no es un campo, así que no genera migración.
        """
        return self.permissions.values_list("module", flat=True).distinct().count()

    @property
    def is_active(self):
        return self.status == "Activo"

    @property
    def group_label(self):
        """Nombre del grupo de Django del rol (columna del listado)."""
        return self.group.name if self.group_id else "—"

class RolePermission(BaseModel):
    role = models.ForeignKey(Role, on_delete=models.CASCADE, related_name="permissions", verbose_name="Rol")
    module = models.CharField(max_length=30, choices=MODULES, verbose_name="Módulo")
    action = models.CharField(max_length=20, choices=ACTIONS, verbose_name="Acción")

    class Meta:
        verbose_name = "Permiso de rol"
        verbose_name_plural = "Permisos de roles"
        db_table = "rol_permiso"
        constraints = [
            models.UniqueConstraint(fields=["role", "module", "action"], name="uniq_role_module_action"),
        ]

    def __str__(self):
        return f"{self.role.code}: {self.module}.{self.action}"

class Period(BaseModel):
    name = models.CharField(max_length=30, verbose_name="Nombre del Período")
    start_date = models.DateField(verbose_name="Fecha Inicio")
    end_date = models.DateField(verbose_name="Fecha Fin")
    quarter = models.IntegerField(choices=[(1, 'Q1'), (2, 'Q2'), (3, 'Q3'), (4, 'Q4')], verbose_name="Trimestre")
    status = models.CharField(max_length=15, default="En curso", choices=[("En curso", "En curso"), ("Cerrado", "Cerrado")], verbose_name="Estado")

    class Meta:
        verbose_name = "Período de Medición"
        verbose_name_plural = "Períodos de Medición"
        db_table = "periodo"

    def __str__(self):
        return f"{self.name} (T{self.quarter})"

class InstitutionalGoal(BaseModel):
    name = models.CharField(max_length=100, verbose_name="Meta Institucional")
    description = models.TextField(blank=True, null=True, verbose_name="Descripción")
    weight = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="Ponderación (%)")
    period = models.ForeignKey(Period, on_delete=models.RESTRICT, related_name="goals", verbose_name="Período")
    delegation = models.ForeignKey(Delegation, on_delete=models.RESTRICT, related_name="goals", verbose_name="Delegación")

    class Meta:
        verbose_name = "Meta Institucional"
        verbose_name_plural = "Metas Institucionales"
        db_table = "meta"

    def __str__(self):
        return f"{self.name} ({self.weight}%)"

class Achievement(BaseModel):
    goal = models.ForeignKey(InstitutionalGoal, on_delete=models.CASCADE, related_name="achievements", verbose_name="Meta")
    percentage = models.DecimalField(max_digits=5, decimal_places=2, default=0.00, verbose_name="Porcentaje Cumplido (%)")

    class Meta:
        verbose_name = "Registro de Cumplimiento"
        verbose_name_plural = "Registros de Cumplimiento"
        db_table = "cumplimiento"

    def __str__(self):
        return f"{self.goal.name}: {self.percentage}%"

class MeasurementItem(BaseModel):
    goal = models.ForeignKey(InstitutionalGoal, on_delete=models.CASCADE, related_name="measurement_items", verbose_name="Meta")
    name = models.CharField(max_length=100, verbose_name="Indicador / Item de Medición")
    unit_of_measure = models.CharField(max_length=50, verbose_name="Unidad de Medida")
    baseline = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Línea Base")
    target_value = models.DecimalField(max_digits=10, decimal_places=2, default=0.00, verbose_name="Valor Objetivo")

    class Meta:
        verbose_name = "Ítem de Medición"
        verbose_name_plural = "Ítems de Medición"
        db_table = "item_medicion"

    def __str__(self):
        return f"{self.name} ({self.unit_of_measure})"


class ProjectItem(BaseModel):
    """Ítem de proyecto del catálogo (mantenedor Ítems y metas)."""

    code = models.CharField(max_length=8, unique=True, verbose_name="Código")
    name = models.CharField(max_length=100, verbose_name="Nombre del ítem")
    description = models.TextField(blank=True, default="", verbose_name="Descripción")
    status = models.CharField(max_length=10, choices=CATALOG_STATUS_CHOICES, default="Activo", verbose_name="Estado")

    class Meta:
        verbose_name = "Ítem de proyecto"
        verbose_name_plural = "Ítems de proyecto"
        db_table = "item_proyecto"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class AttentionType(BaseModel):
    """Tipo de atención del catálogo (mantenedor Tipo de Atención)."""

    code = models.CharField(max_length=8, unique=True, verbose_name="Código")
    name = models.CharField(max_length=100, verbose_name="Nombre del tipo")
    description = models.TextField(blank=True, default="", verbose_name="Descripción")
    status = models.CharField(max_length=10, choices=CATALOG_STATUS_CHOICES, default="Activo", verbose_name="Estado")

    class Meta:
        verbose_name = "Tipo de atención"
        verbose_name_plural = "Tipos de atención"
        db_table = "tipo_atencion"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"


class AttentionSubtype(BaseModel):
    """Sub atención del catálogo (mantenedor Sub Atención)."""

    code = models.CharField(max_length=8, unique=True, verbose_name="Código")
    name = models.CharField(max_length=100, verbose_name="Nombre de la sub atención")
    attention_type = models.ForeignKey(
        AttentionType, on_delete=models.RESTRICT,
        related_name="subtypes", verbose_name="Tipo de atención",
    )
    status = models.CharField(max_length=10, choices=CATALOG_STATUS_CHOICES, default="Activo", verbose_name="Estado")

    class Meta:
        verbose_name = "Sub atención"
        verbose_name_plural = "Sub atenciones"
        db_table = "sub_atencion"
        ordering = ["code"]

    def __str__(self):
        return f"{self.code} - {self.name}"