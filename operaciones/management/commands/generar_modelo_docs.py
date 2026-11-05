"""Genera docs/db/modelo_entidad_relacion.md desde los modelos reales."""
from pathlib import Path

from django.apps import apps
from django.core.management.base import BaseCommand


def _targets():
    models = []
    for app_label in ("sgr_core", "operaciones", "portal"):
        models.extend(apps.get_app_config(app_label).get_models(include_auto_created=False))
    models.append(apps.get_model("auth", "User"))
    models.sort(key=lambda m: f"{m._meta.app_label}.{m._meta.model_name}")
    return models


def _diagram(models):
    out = ["```mermaid", "erDiagram"]
    for model in models:
        out.append(f"    {model._meta.db_table} ||")
        out[-1] = f"    {model._meta.db_table} {{"
        for field in model._meta.get_fields():
            if getattr(field, "auto_created", False) and not getattr(field, "concrete", False):
                continue
            if getattr(field, "many_to_many", False):
                continue
            if hasattr(field, "get_internal_type"):
                ftype = field.get_internal_type()
            else:
                ftype = "Relation"
            key = ""
            if getattr(field, "primary_key", False):
                key = "PK"
            elif getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False):
                key = "FK"
            out.append(f"        {ftype} {field.name} {key}".rstrip())
        out.append("    }")
    seen = set()
    for model in models:
        table = model._meta.db_table
        for field in model._meta.get_fields():
            is_fk = getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)
            if not is_fk or getattr(field, "auto_created", False):
                continue
            if field.related_model is None:
                continue
            rtable = field.related_model._meta.db_table
            key = (table, rtable, field.name)
            if key in seen:
                continue
            seen.add(key)
            if getattr(field, "one_to_one", False):
                out.append(f"    {table} ||--|| {rtable} : {field.name}")
            else:
                out.append(f"    {rtable} ||--o{{ {table} : {field.name}")
    out.append("```")
    return out


def _dictionary(models):
    out = ["## Diccionario de datos", ""]
    for model in models:
        meta = model._meta
        out.append(f"### {meta.db_table} ({meta.app_label}.{meta.object_name})")
        out.append("")
        out.append(f"{meta.verbose_name}.")
        out.append("")
        out.append("| Campo | Tipo | Nulo | Unico | FK y on_delete | Descripcion |")
        out.append("|---|---|---|---|---|---|")
        for field in meta.get_fields():
            if getattr(field, "auto_created", False) and not getattr(field, "concrete", False):
                continue
            if getattr(field, "many_to_many", False):
                through = field.remote_field.through._meta.db_table
                rel = field.related_model._meta.db_table
                out.append(
                    f"| {field.name} | M2M a {rel} (tabla {through}) "
                    f"| - | - | - | {field.verbose_name} |"
                )
                continue
            if not hasattr(field, "get_internal_type"):
                continue
            null = "si" if getattr(field, "null", False) else "no"
            unique = "si" if getattr(field, "unique", False) else "no"
            fk = ""
            is_fk = getattr(field, "many_to_one", False) or getattr(field, "one_to_one", False)
            if is_fk:
                rel = field.related_model._meta.db_table
                fk = f"{rel} {field.remote_field.on_delete.__name__}"
            desc = str(getattr(field, "verbose_name", "") or "")
            out.append(
                f"| {field.name} | {field.get_internal_type()} | {null} | {unique} | {fk} | {desc} |"
            )
        for c in getattr(meta, "constraints", []) or []:
            if hasattr(c, "fields"):
                out.append("")
                out.append(f"Restriccion unica: {c.name} ({', '.join(c.fields)}).")
        out.append("")
    return out


RULES = [
    "## Reglas de integridad y convenciones",
    "",
    "- Tablas en espanol, singular y snake_case (delegacion, funcionario,",
    "  tarea_agenda, item_proyecto, tipo_atencion, sub_atencion, vecino,",
    "  atencion). Excepcion historica: portal conserva `portal_`",
    "  (portal_audit_log) porque ya existia con",
    "  datos; no se renombra.",
    "- Clases y campos en ingles; verbose_name en espanol (es-cl).",
    "- Borrado logico con `deleted_at`: `objects` no cambia;",
    "  el manager adicional `alive` excluye `deleted_at` no nulo.",
    "- RESTRICT/PROTECT en catalogos y referencias historicas; CASCADE solo en",
    "  detalles internos como RolePermission.",
    "- CASCADE historicos existentes (no retocados, fuera de alcance):",
    "  cumplimiento.meta, item_medicion.meta, tarea_agenda.meta,",
    "  actividad.tarea_agenda, evidencia.actividad, derivacion_tarea.tarea_agenda,",
    "  funcionario.usuario, beneficio.funcionario, rol_permiso.rol.",
    "- portal_password_reset_code se elimino en la Evaluacion 3: la",
    "  recuperacion usa un token firmado de Django (sin tabla).",
    "- Grupos y permisos: rol.group -> auth_group (un grupo por rol);",
    "  auth_group_permissions guarda la matriz y auth_user_groups al usuario.",
    "- Auditoria: portal_audit_log registra 403 y acciones relevantes.",
    "- Unicidades sin distinguir mayusculas se validan en formularios y con",
    "  collation utf8mb4 en MariaDB; sin restricciones con funciones.",
    "- Seed de atenciones: clave natural (vecino.identifier, subtipo.code,",
    "  delegacion.code, descripcion unica); numero ATN-0001 lo genera el modelo;",
    "  created_at repartido en ultimos 10 dias solo al crear.",
    "",
]


class Command(BaseCommand):
    help = "Genera la documentacion del modelo ER (diagrama Mermaid + diccionario)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            default=None,
            help="Ruta del .md a generar (por defecto docs/db/modelo_entidad_relacion.md).",
        )

    def handle(self, *args, **options):
        # .../operaciones/management/commands/generar_modelo_docs.py -> parents[3] = raiz del proyecto
        base_dir = Path(__file__).resolve().parents[3]
        if options.get("output"):
            out_path = Path(options["output"])
        else:
            out_path = base_dir / "docs" / "db" / "modelo_entidad_relacion.md"
        out_path.parent.mkdir(parents=True, exist_ok=True)
        models = _targets()
        lines = [
            "# Modelo entidad-relacion - SGR Municipalidad de La Serena",
            "",
            "> Generado con `python manage.py generar_modelo_docs`. No se edita",
            "> a mano: se regenera desde los modelos reales.",
            "",
            "## Diagrama",
            "",
        ]
        lines.extend(_diagram(models))
        lines.append("")
        lines.extend(_dictionary(models))
        lines.extend(RULES)
        out_path.write_text("\n".join(lines), encoding="utf-8")
        self.stdout.write(self.style.SUCCESS(f"Documentacion generada en {out_path}"))



