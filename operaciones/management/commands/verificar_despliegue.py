"""Chequeo rápido del despliegue (Evaluación 3).

Uso:
    python manage.py verificar_despliegue
    python manage.py verificar_despliegue --correo tu-correo@gmail.com

Revisa que todo lo que se muestra en la revisión esté listo: base de datos
(MariaDB en la EC2), migraciones, configuración de producción, grupos y
permisos de Django por rol, Django Admin desactivado, correo para la
recuperación de contraseña y archivos estáticos (Bootstrap y SweetAlert2). Con --correo
envía un correo de prueba para confirmar que Gmail funciona.

Termina con código 1 si encuentra algún error (✗); las advertencias (!) no
detienen nada.
"""

from django.conf import settings
from django.contrib.staticfiles import finders
from django.contrib.staticfiles.storage import staticfiles_storage
from django.core.mail import send_mail
from django.core.management.base import BaseCommand, CommandError
from django.db import connection
from django.db.migrations.executor import MigrationExecutor

OK, WARN, FAIL = "✓", "!", "✗"


class Command(BaseCommand):
    help = "Verifica la configuración del despliegue (BD, grupos, correo, estáticos)."

    def add_arguments(self, parser):
        parser.add_argument(
            "--correo", metavar="DESTINO",
            help="Envía un correo de prueba a esta dirección.",
        )

    # ------------------------------------------------------------------
    def handle(self, *args, **options):
        self.errors = 0
        self.stdout.write(self.style.MIGRATE_HEADING("Verificación del despliegue SGR"))
        self.check_database()
        self.check_migrations()
        self.check_settings()
        self.check_groups()
        self.check_email()
        self.check_static()
        if options.get("correo"):
            self.send_test_email(options["correo"])
        self.stdout.write("")
        if self.errors:
            raise CommandError(f"Se encontraron {self.errors} error(es). Revisa las líneas con {FAIL}.")
        self.stdout.write(self.style.SUCCESS("Todo listo para la revisión."))

    def line(self, status, text):
        if status == FAIL:
            self.errors += 1
            self.stdout.write(self.style.ERROR(f"  {status} {text}"))
        elif status == WARN:
            self.stdout.write(self.style.WARNING(f"  {status} {text}"))
        else:
            self.stdout.write(f"  {self.style.SUCCESS(status)} {text}")

    # ------------------------------------------------------------------
    def check_database(self):
        self.stdout.write("Base de datos")
        try:
            connection.ensure_connection()
        except Exception as exc:  # noqa: BLE001
            self.line(FAIL, f"No se pudo conectar: {exc}")
            return
        if connection.vendor == "mysql":
            version = connection.mysql_server_info
            engine = "MariaDB" if "mariadb" in version.lower() else "MySQL"
            name = settings.DATABASES["default"]["NAME"]
            self.line(OK, f"{engine} {version} · base «{name}»")
        elif connection.vendor == "sqlite":
            self.line(WARN, "SQLite (sirve en tu computador; en la EC2 debe ser MariaDB: DB_ENGINE=django.db.backends.mysql)")
        else:
            self.line(OK, f"Motor {connection.vendor}")

    def check_migrations(self):
        try:
            executor = MigrationExecutor(connection)
            plan = executor.migration_plan(executor.loader.graph.leaf_nodes())
        except Exception as exc:  # noqa: BLE001
            self.line(FAIL, f"No se pudieron revisar las migraciones: {exc}")
            return
        if plan:
            self.line(FAIL, f"Faltan {len(plan)} migración(es): ejecuta python manage.py migrate")
        else:
            self.line(OK, "Migraciones aplicadas")

    def check_settings(self):
        self.stdout.write("Configuración")
        if settings.DEBUG:
            self.line(WARN, "DEBUG=True (en la EC2 debe ser False)")
        else:
            self.line(OK, "DEBUG=False")
        if settings.SECRET_KEY.startswith("django-insecure"):
            self.line(WARN if settings.DEBUG else FAIL, "SECRET_KEY de ejemplo: genera una nueva en el .env")
        else:
            self.line(OK, "SECRET_KEY propia")
        self.line(OK, "ALLOWED_HOSTS: " + ", ".join(settings.ALLOWED_HOSTS))
        if "django.contrib.admin" in settings.INSTALLED_APPS:
            self.line(FAIL, "Django Admin sigue instalado")
        else:
            self.line(OK, "Django Admin desactivado (/admin/ no existe)")

    def check_groups(self):
        self.stdout.write("Roles, grupos y permisos de Django")
        try:
            from operaciones.models import Employee
            from sgr_core.models import Role, RolePermission

            roles = list(Role.alive.select_related("group").order_by("code"))
        except Exception as exc:  # noqa: BLE001
            self.line(FAIL, f"No se pudieron leer los roles: {exc}")
            return
        if not roles:
            self.line(FAIL, "No hay roles: ejecuta python manage.py migrate (y seed_demo si quieres datos demo)")
            return
        for role in roles:
            expected = RolePermission.objects.filter(role=role).count()
            if role.group is None:
                self.line(FAIL, f"{role.code} · {role.name}: sin grupo de Django")
                continue
            perms = role.group.permissions.count()
            users = role.group.user_set.count()
            status = OK if perms == expected else FAIL
            self.line(status, f"{role.group.name}: {perms} permisos, {users} usuario(s)")
        missing = [
            employee for employee in Employee.alive.select_related("user", "role")
            if employee.role_id and employee.role.group_id
            and not employee.user.groups.filter(pk=employee.role.group_id).exists()
        ]
        if missing:
            self.line(FAIL, f"{len(missing)} usuario(s) fuera del grupo de su rol")
        else:
            self.line(OK, "Cada usuario está en el grupo de su rol")

    def check_email(self):
        self.stdout.write("Correo (recuperación de contraseña)")
        backend = settings.EMAIL_BACKEND.rsplit(".", 2)[-2] if "." in settings.EMAIL_BACKEND else settings.EMAIL_BACKEND
        if "smtp" in settings.EMAIL_BACKEND:
            if settings.EMAIL_HOST and settings.EMAIL_HOST_USER and settings.EMAIL_HOST_PASSWORD:
                self.line(OK, f"SMTP {settings.EMAIL_HOST}:{settings.EMAIL_PORT} como {settings.EMAIL_HOST_USER}")
            else:
                self.line(FAIL, "SMTP sin EMAIL_HOST / EMAIL_HOST_USER / EMAIL_HOST_PASSWORD")
        elif "console" in settings.EMAIL_BACKEND:
            self.line(WARN, "Correo por consola: el enlace sale en la terminal (configura Gmail para la demo)")
        else:
            self.line(OK, f"Backend de correo: {backend}")
        minutes = max(1, round(int(settings.PASSWORD_RESET_TIMEOUT) / 60))
        self.line(OK, f"El enlace de recuperación vence en {minutes} minutos")

    def check_static(self):
        self.stdout.write("Archivos estáticos (Bootstrap, SweetAlert2 y estilos)")
        if finders.find("portal/vendor/bootstrap/bootstrap.min.css"):
            self.line(OK, "Bootstrap 5 incluido en el proyecto")
        else:
            self.line(FAIL, "No se encuentra Bootstrap en static/portal/vendor/bootstrap")
        # Las alertas (confirmar Salir/Eliminar y mensajes) usan SweetAlert2: va
        # dentro del proyecto para no depender de un CDN durante la revisión.
        if finders.find("portal/vendor/sweetalert2/sweetalert2.all.min.js"):
            self.line(OK, "SweetAlert2 incluido en el proyecto (sin CDN)")
        else:
            self.line(FAIL, "No se encuentra SweetAlert2 en static/portal/vendor/sweetalert2")
        manifest_storage = getattr(staticfiles_storage, "manifest_storage", None)
        manifest_name = getattr(staticfiles_storage, "manifest_name", None)
        if manifest_storage is not None and manifest_name:
            if manifest_storage.exists(manifest_name):
                self.line(OK, "collectstatic ejecutado")
            elif settings.DEBUG:
                self.line(WARN, "Falta collectstatic (obligatorio con DEBUG=False)")
            else:
                self.line(FAIL, "Falta python manage.py collectstatic --noinput (con DEBUG=False las páginas fallan)")

    def send_test_email(self, destino):
        self.stdout.write("Correo de prueba")
        try:
            send_mail(
                "Prueba de correo - SGR La Serena",
                "Si recibes este mensaje, el envío de correos del SGR funciona.",
                settings.DEFAULT_FROM_EMAIL, [destino], fail_silently=False,
            )
        except Exception as exc:  # noqa: BLE001
            self.line(FAIL, f"No se pudo enviar a {destino}: {exc}")
        else:
            self.line(OK, f"Correo enviado a {destino} (revisa la bandeja y el spam)")
