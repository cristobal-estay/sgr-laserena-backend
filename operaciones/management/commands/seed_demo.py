"""
Carga datos ficticios de demostración para el SGR (modelos actualizados).

Uso:
    python manage.py seed_demo

Es idempotente: se puede ejecutar varias veces sin duplicar registros.
Todos los funcionarios, RUT, correos y URLs de evidencia son FICTICIOS
(la guía del proyecto prohíbe cargar datos reales de funcionarios o
ciudadanos). Las delegaciones y sus descripciones corresponden a
información pública de la Municipalidad de La Serena.
"""
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.contrib.auth.models import Permission
from django.core.management.base import BaseCommand
from django.db import transaction
from django.utils import timezone

from operaciones.models import (
    Activity, Attention, Benefit, Employee, Evidence,
    Neighbor, Task, TaskReassignment,
)
from sgr_core.models import (
    Achievement, AttentionSubtype, AttentionType, Delegation,
    InstitutionalGoal, MeasurementItem, Period, ProjectItem,
    Role, RolePermission,
)
from sgr_core.roles import ensure_base_roles

DEMO_PASSWORD = "Demo2026!"
ADMIN_USER = "admin_demo"
LIMITED_USER = "limitado_demo"
BOSS_USER = "jefatura_centro"

# (nombre, descripción, color, código)
DELEGATIONS = [
    ("Avenida del Mar", "Borde costero, turismo, residencial y servicios", "#1D6FA5", "DEL02"),
    ("Centro", "Centro histórico, administrativo, comercial y patrimonial", "#C62828", "DEL01"),
    ("La Antena-La Florida", "Sector urbano oriental y barrios asociados", "#2E7D32", "DEL03"),
    ("Las Compañías", "Sector urbano norte de alta densidad y fuerte identidad territorial", "#6A1B9A", "DEL04"),
    ("La Pampa", "Sector urbano sur y áreas residenciales asociadas", "#E65100", "DEL05"),
    ("Rural", "Localidades y comunidades rurales dispersas", "#00796B", "DEL06"),
]

# (username, first_name, last_name, rut, delegacion, rol_code)
EMPLOYEES = [
    ("diego.molina", "Diego", "Molina Pinto", "10.000.004-4", "Centro", "ROL04"),
    ("elena.campas", "Elena", "Campas Mora", "10.000.005-5", "Centro", "ROL04"),
    ("gabriela.rojas", "Gabriela", "Rojas Lagos", "10.000.007-7", "Avenida del Mar", "ROL04"),
    ("hugo.pizarro", "Hugo", "Pizarro Reyes", "10.000.008-8", "Avenida del Mar", "ROL04"),
]

# delegacion -> [(nombre_meta, ponderacion, [(item, unidad, objetivo)])]
GOALS = {
    "Centro": [
        ("Atención territorial y operativos", "60.00", [
            ("Operativos en terreno realizados", "operativos", "12.00"),
            ("Solicitudes vecinales atendidas", "solicitudes", "40.00"),
        ]),
        ("Gestión del espacio público", "40.00", [
            ("Reportes de deterioro gestionados", "reportes", "20.00"),
        ]),
    ],
    "Avenida del Mar": [
        ("Coordinación estacional y espacios públicos", "60.00", [
            ("Reuniones con comercio y residentes", "reuniones", "8.00"),
            ("Inspecciones de espacios públicos", "inspecciones", "15.00"),
        ]),
        ("Seguridad y prevención", "40.00", [
            ("Actividades preventivas realizadas", "actividades", "10.00"),
        ]),
    ],
}

# (username_empleado, titulo, estado, dias_al_plazo, nombre_meta, descripcion)
TASKS = [
    ("diego.molina", "Operativo de limpieza calle Cienfuegos", "Completada", -10,
    "Atención territorial y operativos", "Coordinar retiro de escombros."),
    ("diego.molina", "Visita a junta vecinal Centro Histórico", "En Progreso", 5,
    "Atención territorial y operativos", "Levantar requerimientos de alumbrado."),
    ("elena.campas", "Reporte de deterioro en plaza", "Completada", -3,
    "Gestión del espacio público", "Informar a Obras Municipales."),
    ("elena.campas", "Reunión con comerciantes del casco antiguo", "Pendiente", 12,
    "Atención territorial y operativos", "Agendar reunión de coordinación."),
    ("gabriela.rojas", "Reunión con residentes de edificios costeros", "Completada", -7,
    "Coordinación estacional y espacios públicos", "Recoger opinión sobre temporada estival."),
    ("gabriela.rojas", "Inspección de accesos a playa", "En Progreso", 4,
    "Coordinación estacional y espacios públicos", "Revisar señalética y baños públicos."),
    ("hugo.pizarro", "Charla de prevención en borde costero", "Completada", -15,
    "Seguridad y prevención", "Coordinar con Seguridad Ciudadana."),
    # Tarea visible para limitado_demo (usuario de Centro): se asigna a elena
    # aquí y se reasigna a su Employee propio más abajo, cuando ya existe.
    ("elena.campas", "Catastro de luminarias apagadas en Centro", "Pendiente", 7,
    "Gestión del espacio público", "Registrar postes sin luz para derivar a Obras."),
]

# (titulo_tarea, nombre_actividad, dias_ejecucion_relativos)
ACTIVITIES = [
    ("Operativo de limpieza calle Cienfuegos", "Retiro de escombros y limpieza de vereda", -10),
    ("Visita a junta vecinal Centro Histórico", "Reunión con dirigentes vecinales", -1),
    ("Reporte de deterioro en plaza", "Inspección y registro fotográfico del daño", -3),
    ("Reunión con residentes de edificios costeros", "Encuesta de percepción vecinal", -7),
    ("Inspección de accesos a playa", "Revisión de señalética existente", -1),
    ("Charla de prevención en borde costero", "Charla informativa a comerciantes", -15),
    ("Catastro de luminarias apagadas en Centro", "Relevamiento de postes sin iluminación", -1),
]

# (nombre_actividad, url_imagen, validado)
EVIDENCES = [
    ("Retiro de escombros y limpieza de vereda", "https://ejemplo.cl/evidencias/ev-0001.jpg", True),
    ("Inspección y registro fotográfico del daño", "https://ejemplo.cl/evidencias/ev-0002.jpg", False),
    ("Reunión con dirigentes vecinales", "https://ejemplo.cl/evidencias/ev-0003.jpg", False),
    ("Encuesta de percepción vecinal", "https://ejemplo.cl/evidencias/ev-0004.jpg", True),
    ("Revisión de señalética existente", "https://ejemplo.cl/evidencias/ev-0005.jpg", False),
    ("Charla informativa a comerciantes", "https://ejemplo.cl/evidencias/ev-0006.jpg", False),
    ("Relevamiento de postes sin iluminación", "https://ejemplo.cl/evidencias/ev-0007.jpg", False),
]

# (titulo_tarea, username_origen, username_destino, motivo, dias_atras, notas)
REASSIGNMENTS = [
    ("Operativo de limpieza calle Cienfuegos", "diego.molina", "elena.campas", "vacation", 8,
    "La funcionaria asume el operativo durante las vacaciones del titular."),
    ("Reunión con comerciantes del casco antiguo", "elena.campas", "diego.molina", "absence", 3,
    "Derivación por licencia médica del titular."),
    ("Inspección de accesos a playa", "gabriela.rojas", "hugo.pizarro", "other", 2,
    "Apoyo del equipo en la inspección de señalética."),
]

# (username, tipo_beneficio, dias_atras, entregado)
BENEFITS = [
    ("diego.molina", "food_basket", 5, True),
    ("elena.campas", "school_kit", 3, False),
    ("gabriela.rojas", "medical_aid", 1, True),
]


# --- Catálogos de la Parte 2B (idempotentes) ---
# (code, name, description, status)
PROJECT_ITEMS = [
    ("ITM01", "Operativos en terreno", "Operativos municipales realizados en las delegaciones.", "Activo"),
    ("ITM02", "Solicitudes vecinales", "Solicitudes de vecinos atendidas por la delegación.", "Activo"),
    ("ITM03", "Reportes de deterioro", "Reportes de deterioro del espacio público gestionados.", "Activo"),
    ("ITM04", "Reuniones comunitarias", "Reuniones con comercio, residentes y organizaciones.", "Activo"),
    ("ITM05", "Inspecciones preventivas", "Inspecciones de espacios públicos y seguridad.", "Activo"),
    ("ITM06", "Actividades preventivas", "Actividades de prevención y seguridad realizadas.", "Activo"),
    ("ITM07", "Certificados emitidos", "Certificados y documentos entregados a vecinos.", "Activo"),
]

# (code, name, description, status)
ATTENTION_TYPES = [
    ("TAT01", "Social", "Apoyo social, ayudas y beneficios.", "Activo"),
    ("TAT02", "Territorial", "Intervenciones en terreno y espacio público.", "Activo"),
    ("TAT03", "Administrativa", "Trámites, certificados y patentes.", "Activo"),
    ("TAT04", "Orientación ciudadana", "Orientación y consultas generales.", "Activo"),
    ("TAT05", "Emergencias", "Atención de emergencias (catálogo en revisión).", "Inactivo"),
]

# (code, name, type_code, status)
ATTENTION_SUBTYPES = [
    ("SAT01", "Ayuda social", "TAT01", "Activo"),
    ("SAT02", "Subsidio y beneficios", "TAT01", "Activo"),
    ("SAT03", "Visita a terreno", "TAT02", "Activo"),
    ("SAT04", "Reparación de luminaria", "TAT02", "Activo"),
    ("SAT05", "Certificado de residencia", "TAT03", "Activo"),
    ("SAT06", "Patente comercial", "TAT03", "Activo"),
    ("SAT07", "Orientación de trámites", "TAT04", "Activo"),
    ("SAT08", "Consulta general", "TAT04", "Inactivo"),
]

# (identifier, full_name, phone, email, status)
NEIGHBORS = [
    ("11.111.111-1", "María González Rojas", "+56911111111", "maria.gonzalez@ejemplo.cl", "Activo"),
    ("22.222.222-2", "Juan Pérez Soto", "+56922222222", "juan.perez@ejemplo.cl", "Activo"),
    ("33.333.333-3", "Ana Muñoz Contreras", "+56933333333", "ana.munoz@ejemplo.cl", "Activo"),
    ("44.444.444-4", "Pedro Álvarez Paredes", "+56944444444", "pedro.alvarez@ejemplo.cl", "Activo"),
    ("55.555.555-5", "Lucía Fernández Díaz", "+56955555555", "lucia.fernandez@ejemplo.cl", "Activo"),
    ("66.666.666-6", "Carlos Ramírez Vega", "+56966666666", "carlos.ramirez@ejemplo.cl", "Activo"),
    ("77.777.777-7", "Sofía Torres Aguilar", "+56977777777", "sofia.torres@ejemplo.cl", "Activo"),
    ("88.888.888-8", "Diego Hernández Mora", "+56988888888", "diego.hernandez@ejemplo.cl", "Activo"),
    ("99.999.999-9", "Elena Rivera Campos", "+56999999999", "elena.rivera@ejemplo.cl", "Activo"),
    ("10.101.010-1", "Miguel Soto Navarro", "+56910101010", "miguel.soto@ejemplo.cl", "Activo"),
    ("12.121.212-2", "Carmen Díaz Fuentes", "+56912121212", "carmen.diaz@ejemplo.cl", "Activo"),
    ("13.131.313-3", "Jorge Paredes León", "+56913131313", "jorge.paredes@ejemplo.cl", "Activo"),
    ("14.141.414-4", "Rosa Aguilar Cárdenas", "+56914141414", "rosa.aguilar@ejemplo.cl", "Activo"),
    ("15.151.515-5", "Luis Navarro Salas", "+56915151515", "luis.navarro@ejemplo.cl", "Activo"),
]

# Atenciones demo (clave natural estable: vecino + subtipo + delegación +
# descripción única). El número (ATN-0001, ...) lo genera el modelo.
# (neighbor_id, subtype_code, delegation_name, responsible_username, description, status)
ATTENTIONS = [
    ("11.111.111-1", "SAT01", "Centro", "funcionario", "Solicitud de ayuda social para grupo familiar.", "received"),
    ("22.222.222-2", "SAT03", "Centro", "funcionario", "Visita a terreno por denuncia de microbasural.", "in_progress"),
    ("33.333.333-3", "SAT05", "Centro", "funcionario", "Emisión de certificado de residencia.", "resolved"),
    ("44.444.444-4", "SAT02", "Avenida del Mar", "funcionario.mar", "Postulación a subsidio y beneficios sociales.", "received"),
    ("55.555.555-5", "SAT04", "Avenida del Mar", "funcionario.mar", "Reparación de luminaria en mal estado.", "in_progress"),
    ("66.666.666-6", "SAT03", "La Antena-La Florida", "funcionario", "Visita a terreno por sede vecinal.", "received"),
    ("77.777.777-7", "SAT01", "La Antena-La Florida", "funcionario", "Ayuda social por emergencia familiar.", "in_progress"),
    ("88.888.888-8", "SAT06", "Las Compañías", "coordinador2", "Solicitud de patente comercial.", "received"),
    ("99.999.999-9", "SAT07", "Las Compañías", "coordinador2", "Orientación de trámites municipales.", "resolved"),
    ("10.101.010-1", "SAT02", "La Pampa", "coordinador2", "Consulta por subsidio y beneficios.", "received"),
    ("12.121.212-2", "SAT05", "La Pampa", "coordinador2", "Certificado de residencia para postulación.", "in_progress"),
    ("13.131.313-3", "SAT03", "Rural", "coordinador2", "Visita a terreno en localidad rural.", "received"),
    ("14.141.414-4", "SAT07", "Rural", "coordinador2", "Orientación de trámites para comité rural.", "in_progress"),
    ("15.151.515-5", "SAT04", "Centro", "coordinador", "Reparación de luminaria en plaza central.", "received"),
]


class Command(BaseCommand):
    help = "Carga datos ficticios de demostración sobre los modelos actuales (idempotente)."

    @transaction.atomic
    def handle(self, *args, **options):
        hoy = timezone.localdate()
        User = get_user_model()

        # --- Roles base (idempotente) ---
        roles = {role.code: role for role in ensure_base_roles(Role, RolePermission)}

        # Normaliza el nombre legado (también lo hace la migración de datos).
        if not Delegation.objects.filter(name="La Antena-La Florida").exists():
            Delegation.objects.filter(name="La Antena").update(name="La Antena-La Florida")

        # --- Delegaciones (asegura código, color y descripción) ---
        delegs = {}
        for nombre, desc, color, code in DELEGATIONS:
            d, creado = Delegation.objects.get_or_create(
                name=nombre, defaults={"description": desc, "color": color, "code": code},
            )
            if not creado:
                campos = {
                    campo: valor
                    for campo, valor in (
                        ("description", desc),
                        ("color", color),
                        ("code", code),
                    )
                    if getattr(d, campo) != valor
                }
                if campos:
                    for campo, valor in campos.items():
                        setattr(d, campo, valor)
                    d.save(update_fields=list(campos))
            delegs[nombre] = d

        # --- Usuarios + Funcionarios (Employee) ---
        empleados = {}
        for username, first, last, rut, deleg, rol in EMPLOYEES:
            u, creado = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first, "last_name": last, "email": f"{username}@ejemplo.cl", "is_staff": True},
            )
            if creado:
                u.set_password(DEMO_PASSWORD)
                u.save()
            emp, _ = Employee.objects.get_or_create(
                user=u, defaults={"rut": rut, "delegation": delegs[deleg], "role": roles[rol]},
            )
            if emp.role_id != roles[rol].pk:
                emp.role = roles[rol]
                emp.save(update_fields=["role"])
            empleados[username] = emp

        # --- Períodos ---
        periodo, _ = Period.objects.get_or_create(
            name="Trimestre Jul-Sep 2026",
            defaults={"start_date": date(2026, 7, 1), "end_date": date(2026, 9, 30),
                    "quarter": 3, "status": "En curso"},
        )
        Period.objects.get_or_create(
            name="Trimestre Abr-Jun 2026",
            defaults={"start_date": date(2026, 4, 1), "end_date": date(2026, 6, 30),
                    "quarter": 2, "status": "Cerrado"},
        )

        # --- Metas institucionales + ítems + cumplimiento ---
        goals = {}
        for deleg, lista in GOALS.items():
            for nombre_meta, pond, items in lista:
                goal, _ = InstitutionalGoal.objects.get_or_create(
                    name=nombre_meta, period=periodo, delegation=delegs[deleg],
                    defaults={"description": f"Meta de {deleg}", "weight": pond},
                )
                goals[nombre_meta] = goal
                Achievement.objects.get_or_create(goal=goal, defaults={"percentage": "45.00"})
                for it_nombre, unidad, objetivo in items:
                    MeasurementItem.objects.get_or_create(
                        goal=goal, name=it_nombre,
                        defaults={"unit_of_measure": unidad, "baseline": "0.00", "target_value": objetivo},
                    )

        # --- Tareas (Task) ---
        tasks = {}
        for username, titulo, estado, dias, meta, desc in TASKS:
            goal = goals[meta]
            plazo = hoy + timedelta(days=dias)
            # el plazo debe caer dentro del período de la meta (lo exige el clean() de TaskForm)
            if not (goal.period.start_date <= plazo <= goal.period.end_date):
                plazo = goal.period.start_date + timedelta(days=15)
            t, _ = Task.objects.get_or_create(
                title=titulo, goal=goal,
                defaults={"description": desc, "due_date": plazo, "status": estado},
            )
            resp = empleados[username]
            if t.assigned_to_id != resp.id:
                t.assigned_to = resp
                t.save(update_fields=["assigned_to"])
            tasks[titulo] = t

        # --- Actividades (Activity) ---
        activities = {}
        for titulo_tarea, nombre_act, dias in ACTIVITIES:
            a, _ = Activity.objects.get_or_create(
                task=tasks[titulo_tarea], name=nombre_act,
                defaults={"execution_date": hoy + timedelta(days=dias)},
            )
            activities[nombre_act] = a

        # --- Evidencias (Evidence) ---
        for nombre_act, url, validado in EVIDENCES:
            Evidence.objects.get_or_create(
                activity=activities[nombre_act],
                defaults={"image_url": url, "is_validated": validado},
            )

        # --- Derivaciones de tareas (TaskReassignment) ---
        # Repartidas entre 2 delegaciones (Centro y Avenida del Mar) para poder
        # comprobar el scoping por delegación en el admin.
        for titulo, origen, destino, motivo, dias, notas in REASSIGNMENTS:
            TaskReassignment.objects.get_or_create(
                task=tasks[titulo],
                original_employee=empleados[origen],
                reassigned_employee=empleados[destino],
                defaults={
                    "reason": motivo,
                    "reassigned_at": timezone.now() - timedelta(days=dias),
                    "notes": notas,
                },
            )

        # --- Beneficios (Benefit) ---
        # delivery_area debe coincidir con la delegación del funcionario (lo valida clean())
        for username, tipo, dias, entregado in BENEFITS:
            emp = empleados[username]
            Benefit.objects.get_or_create(
                employee=emp, benefit_type=tipo,
                defaults={
                    "delivery_area": emp.delegation,
                    "delivered_at": (timezone.now() - timedelta(days=dias)) if entregado else None,
                    "delivered": entregado,
                },
            )

        # --- Usuarios del Django Admin (administrador y limitado) ---
        admin_u, _ = User.objects.get_or_create(
            username=ADMIN_USER, defaults={"email": f"{ADMIN_USER}@ejemplo.cl"},
        )
        admin_u.is_staff = admin_u.is_superuser = True
        admin_u.set_password(DEMO_PASSWORD)
        admin_u.save()

        lim_u, _ = User.objects.get_or_create(
            username=LIMITED_USER,
            defaults={"first_name": "Usuario", "last_name": "Limitado", "email": f"{LIMITED_USER}@ejemplo.cl"},
        )
        lim_u.is_staff, lim_u.is_superuser = True, False
        lim_u.set_password(DEMO_PASSWORD)
        lim_u.save()
        # el usuario limitado también necesita su propio Employee, para que
        # TaskAdmin.get_queryset() pueda filtrar por su delegación (scoping)
        lim_emp, _ = Employee.objects.get_or_create(
            user=lim_u, defaults={"rut": "10.000.099-9", "delegation": delegs["Centro"], "role": roles["ROL04"]},
        )
        if lim_emp.role_id != roles["ROL04"].pk:
            lim_emp.role = roles["ROL04"]
            lim_emp.save(update_fields=["role"])
        permisos = Permission.objects.filter(
            content_type__app_label="operaciones",
            codename__in=["view_task", "change_task", "view_activity", "view_evidence", "change_evidence"],
        )
        lim_u.user_permissions.set(permisos)
        # Tarea propia del usuario limitado: se reasigna a su Employee para
        # poder probar el scoping de Usuario (assigned_to propio).
        t_lim = tasks.get("Catastro de luminarias apagadas en Centro")
        if t_lim is not None and t_lim.assigned_to_id != lim_emp.id:
            t_lim.assigned_to = lim_emp
            t_lim.save(update_fields=["assigned_to"])

        # --- Jefatura de delegación (Centro): ve todo lo de su delegación ---
        boss_u, _ = User.objects.get_or_create(
            username=BOSS_USER,
            defaults={"first_name": "Jefatura", "last_name": "Centro", "email": f"{BOSS_USER}@ejemplo.cl", "is_staff": True},
        )
        boss_u.is_staff = True
        boss_u.is_superuser = False
        boss_u.set_password(DEMO_PASSWORD)
        boss_u.save()
        boss_emp, _ = Employee.objects.get_or_create(
            user=boss_u, defaults={"rut": "10.000.100-2", "delegation": delegs["Centro"], "role": roles["ROL03"]},
        )
        if boss_emp.role_id != roles["ROL03"].pk or boss_emp.delegation_id != delegs["Centro"].id:
            boss_emp.role, boss_emp.delegation = roles["ROL03"], delegs["Centro"]
            boss_emp.save(update_fields=["role", "delegation"])
        boss_u.user_permissions.set(permisos)

        # --- Usuarios demo de acceso (correo + clave Demo2026!) ---
        def demo_user(username, first_name, last_name, *, superuser=False, active=True):
            email = f"{username}@example.test"
            user, _ = User.objects.get_or_create(
                username=username,
                defaults={"first_name": first_name, "last_name": last_name, "email": email},
            )
            user.email = email
            if superuser:
                user.is_staff = True
                user.is_superuser = True
            user.is_active = active
            user.set_password(DEMO_PASSWORD)
            user.save()
            return user

        def demo_employee(user, rut, delegacion, rol_code, autorizadas=()):
            emp, creado = Employee.objects.get_or_create(
                user=user,
                defaults={"rut": rut, "delegation": delegs[delegacion], "role": roles[rol_code]},
            )
            if not creado:
                cambios = []
                if emp.delegation_id != delegs[delegacion].pk:
                    emp.delegation = delegs[delegacion]
                    cambios.append("delegation")
                if emp.role_id != roles[rol_code].pk:
                    emp.role = roles[rol_code]
                    cambios.append("role")
                if cambios:
                    emp.save(update_fields=cambios)
            esperadas = {delegs[nombre].pk for nombre in autorizadas}
            actuales = set(emp.authorized_delegations.values_list("pk", flat=True))
            if actuales != esperadas:
                emp.authorized_delegations.set(esperadas)
            return emp

        # Superadministrador: SIN Employee (rol virtual por ser superusuario).
        demo_user("superadmin", "Super", "Administrador", superuser=True)

        # Coordinador de DEL01-DEL03 y coordinador de DEL04-DEL06.
        demo_employee(
            demo_user("coordinador", "Coordinadora", "Zona 1"),
            "10.000.110-1", "Centro", "ROL02",
            autorizadas=("Centro", "Avenida del Mar", "La Antena-La Florida"),
        )
        demo_employee(
            demo_user("coordinador2", "Coordinadora", "Zona 2"),
            "10.000.111-9", "Las Compañías", "ROL02",
            autorizadas=("Las Compañías", "La Pampa", "Rural"),
        )

        # Delegado y funcionario en DEL01 (Centro).
        demo_employee(demo_user("delegado", "Delegada", "Centro"), "10.000.112-7", "Centro", "ROL03")
        demo_employee(demo_user("funcionario", "Funcionaria", "Centro"), "10.000.113-5", "Centro", "ROL04")

        # Al menos un delegado y un funcionario en DEL02 (Avenida del Mar).
        demo_employee(
            demo_user("delegado.mar", "Delegada", "Avenida del Mar"), "10.000.114-3", "Avenida del Mar", "ROL03",
        )
        demo_employee(
            demo_user("funcionario.mar", "Funcionaria", "Avenida del Mar"), "10.000.115-1", "Avenida del Mar", "ROL04",
        )

        # Funcionario de DEL03 (La Antena-La Florida), usuario inactivo.
        demo_employee(
            demo_user("ignacio.vera", "Ignacio", "Vera", active=False),
            "10.000.116-6", "La Antena-La Florida", "ROL04",
        )

        # --- Catálogos de la Parte 2B (idempotentes) ---
        for code, name, description, status in PROJECT_ITEMS:
            ProjectItem.objects.update_or_create(
                code=code,
                defaults={"name": name, "description": description, "status": status},
            )
        for code, name, description, status in ATTENTION_TYPES:
            AttentionType.objects.update_or_create(
                code=code,
                defaults={"name": name, "description": description, "status": status},
            )
        types = {t.code: t for t in AttentionType.objects.all()}
        subtypes = {}
        for code, name, type_code, status in ATTENTION_SUBTYPES:
            subtype, _ = AttentionSubtype.objects.update_or_create(
                code=code,
                defaults={
                    "name": name, "attention_type": types[type_code],
                    "status": status,
                },
            )
            subtypes[code] = subtype
        for identifier, full_name, phone, email, status in NEIGHBORS:
            Neighbor.objects.update_or_create(
                identifier=identifier,
                defaults={
                    "full_name": full_name, "phone": phone,
                    "email": email, "status": status,
                },
            )

        # --- Atenciones demo (clave natural estable, sin duplicar) ---
        # Clave natural: (vecino, subtipo, delegación, descripción única).
        # El número (ATN-0001, ...) lo genera el modelo en save().
        # created_at se reparte en los últimos 10 días (solo al crear, para
        # que una segunda corrida no mueva las fechas).
        base_now = timezone.now()
        for i, (neighbor_id, subtype_code, deleg_name, resp_username, description, status) in enumerate(ATTENTIONS):
            subtype = subtypes[subtype_code]
            attention, created = Attention.objects.get_or_create(
                neighbor=Neighbor.objects.get(identifier=neighbor_id),
                attention_subtype=subtype,
                delegation=delegs[deleg_name],
                description=description,
                defaults={
                    "attention_type": subtype.attention_type,
                    "responsible": User.objects.get(username=resp_username),
                    "status": status,
                },
            )
            if created:
                created_at = base_now - timedelta(days=(i % 10), hours=i)
                Attention.objects.filter(pk=attention.pk).update(created_at=created_at)

        # Evaluación 3: los superusuarios (sin Employee) también quedan en el
        # grupo de Django del Superadministrador, para mostrarlo en el listado.
        from django.contrib.auth.models import User as AuthUser
        from sgr_core.groups import sync_user_groups

        rol_super = Role.objects.filter(code="ROL01").first()
        for superuser in AuthUser.objects.filter(is_superuser=True, employee__isnull=True):
            sync_user_groups(superuser, rol_super)

        self.stdout.write(self.style.SUCCESS("Datos de demostración cargados."))
        self.stdout.write(f"  Administrador:  {ADMIN_USER} / {DEMO_PASSWORD}")
        self.stdout.write(f"  Usuario limitado (delegación Centro): {LIMITED_USER} / {DEMO_PASSWORD}")
        self.stdout.write(f"  Jefatura (delegación Centro): {BOSS_USER} / {DEMO_PASSWORD}")
        self.stdout.write("  Usuarios demo de acceso (example.test):")
        for demo in (
            "superadmin", "coordinador", "coordinador2", "delegado", "delegado.mar",
            "funcionario", "funcionario.mar", "ignacio.vera",
        ):
            self.stdout.write(f"    {demo}@example.test / {DEMO_PASSWORD}")