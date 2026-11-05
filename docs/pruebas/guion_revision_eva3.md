# Guion de pruebas para la revisión presencial (Evaluación Sumativa 3)

Pruebas para hacer frente al profesor, ordenadas según la escala de apreciación.
Cada prueba dice **qué hacer**, **qué debe pasar** y **qué explicar**.
Ensáyalas antes en tu computador (`python manage.py runserver`) y después en la EC2.

Todos los usuarios demo usan la clave **`Demo2026!`** (se puede entrar con el
usuario o con el correo).

| Usuario | Rol | Dashboard |
|---|---|---|
| `superadmin` | Superadministrador | Administrador (acceso total) |
| `coordinador` | Coordinador (DEL01 a DEL03) | Supervisor |
| `delegado` | Delegado municipal (DEL01) | Supervisor |
| `funcionario` | Funcionario (DEL01) | Administrativo (permisos mínimos) |
| `funcionario.mar` | Funcionario (DEL02) | Úsalo para la recuperación (pon tu Gmail) |
| `delegado.mar` | Delegado (DEL02) | Úsalo para probar el bloqueo por intentos |
| `ignacio.vera` | Funcionario inactivo | Para mostrar que una cuenta inactiva no entra |

---

## Antes de que llegue el profesor (checklist)

- [ ] Learner Lab iniciado e instancia EC2 **En ejecución**. Anota la IP pública.
- [ ] `http://IP/` abre el login y `http://IP/phpmyadmin/` abre phpMyAdmin.
- [ ] En la EC2: `cd ~/sgr-laserena-backend && venv/bin/python manage.py verificar_despliegue --correo tu-correo@gmail.com`
      termina con "Todo listo para la revisión" y **te llega el correo de prueba**.
- [ ] Como `superadmin`: Usuarios → editar **Funcionaria Avenida del Mar**
      (`funcionario.mar`) → Correo electrónico = **tu Gmail** → Guardar.
      Desde ahora ese usuario entra con tu Gmail como usuario.
- [ ] Gmail abierto en otra pestaña.
- [ ] Una ventana normal y otra de **incógnito**, para tener dos perfiles a la vez.
- [ ] VS Code con el proyecto abierto (para mostrar el código) y GitHub abierto en el repositorio.

---

## 1. Sistema de autenticación (15 pts)

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| 1.1 | Entrar con `superadmin` / `Demo2026!` | Llega al **Dashboard Administrador** |
| 1.2 | Salir y entrar con el **correo** `superadmin@example.test` | También entra (acepta usuario o correo) |
| 1.3 | Entrar con una clave incorrecta | "El usuario o la contraseña no son correctos." |
| 1.4 | Con `delegado.mar`, poner 5 veces una clave mala y luego la buena | Al 5.º intento: "Has superado el límite de intentos. Espera 10 minutos…"; después no entra ni con la clave buena |
| 1.5 | Entrar con `ignacio.vera@example.test` | "Tu cuenta está inactiva…" |
| 1.6 | Botón **Salir** | Vuelve al login (el cierre es por POST con token CSRF) |
| 1.7 | Sin sesión, escribir `http://IP/usuarios/` en la barra | Redirige al login: las vistas están protegidas |

**Qué explicar:** login en `portal/views.py` (`PortalLoginView`), acepta usuario o
correo con `portal/backends.py`, bloqueo de 5 intentos por 10 minutos, y todas las
vistas exigen sesión con `LoginRequiredMixin`.

## 2. Gestión de perfiles y permisos (15 pts)

**2.1 Crear un usuario y asignarle un grupo**

1. Como `superadmin`: **Usuarios → Nuevo registro**.
2. RUT `15.678.432-K`, Nombre `Pedro`, Apellido `Prueba`, Correo `pedro.prueba@example.test`,
   Rol **Funcionario**, delegación **DEL01**, contraseña inicial `Municipal2026` (dos veces) → **Guardar**.
3. **Debe pasar:** aparece en el listado y la columna **Grupo de Django** dice `ROL04 · Funcionario`.
4. Entrar con `pedro.prueba@example.test` / `Municipal2026` (en incógnito): ve el Dashboard Administrativo.
   (Django rechaza claves parecidas al nombre o al correo, por ejemplo "Prueba2026x" para Pedro Prueba: es el validador de similitud.)

**2.2 Cambiar el grupo:** editar a Pedro y cambiarle el rol a **Delegado municipal** → Guardar.
La columna cambia a `ROL03 · Delegado municipal` (el usuario sale del grupo anterior).
En phpMyAdmin se ve en la tabla `auth_user_groups`.

**2.3 Restricción funcional editando permisos:**

1. Como `superadmin`: **Roles** → editar **Coordinador** → en la matriz, desmarcar
   **Ítems de medición: Exportar** → Guardar.
2. Como `coordinador` (incógnito): **Ítems y metas** ya no muestra "Exportar a Excel", y
   escribir `http://IP/items/exportar/` da **Acceso restringido (403)**.
3. Volver a marcar la casilla y guardar (dejarlo como estaba).

**2.4 Acceso diferenciado:** como `funcionario`, el menú solo tiene Inicio, Atenciones y
Agenda. Escribir `http://IP/delegaciones/` o `http://IP/usuarios/` → **Acceso restringido (403)**,
y el intento queda en la auditoría (se ve en el Dashboard Administrador).

**2.5 Alcance de datos:** `delegado` solo ve atenciones de DEL01; `coordinador` cambia la
delegación activa en el selector de arriba y el listado cambia; `funcionario` solo ve las que él ingresó.

**Qué explicar:**

- Cada rol tiene un **Grupo de Django** y cada casilla de la matriz es un **Permiso de Django**
  (`sgr_core.create_attentions`, `sgr_core.view_users`…): 55 en total (`sgr_core/groups.py`).
- Al guardar la matriz, una señal copia los permisos al grupo (`sgr_core/signals.py`); al
  guardar un usuario con un rol, otra señal lo deja en ese grupo (`operaciones/signals.py`).
- Cada vista valida con `user.has_perm(...)` en `portal/access.py` (`ModulePermissionMixin`).
  Esconder el botón no basta: el servidor responde 403 aunque se escriba la URL a mano.

## 3. Recuperación de contraseña con token (15 pts)

1. Cerrar sesión → **¿Olvidaste tu contraseña?** → escribir **tu Gmail** → **Enviar enlace**.
   **Debe pasar:** pantalla "Revisa tu correo" (paso 2 de 4).
2. En Gmail llega **"Recupera tu contraseña - Sistema Municipal"** con el botón
   **Crear nueva contraseña** (si no está, revisa spam).
3. Abrir el enlace → pantalla **Crear nueva contraseña** (paso 3) → escribir una clave nueva
   (8 caracteres, mayúscula, minúscula y número), por ejemplo `Serena2026x` → **Guardar contraseña**.
4. **Debe pasar:** "Contraseña actualizada" (paso 4) y llega un segundo correo de confirmación.
5. Entrar con tu Gmail y la clave nueva → entra. Con `Demo2026!` ya no.
6. Abrir **otra vez el mismo enlace** → "Enlace no válido o vencido" (es de un solo uso).
7. Pedir recuperación con un correo que no existe → muestra la misma pantalla (no revela si la cuenta existe).

**Qué explicar:**

- El token lo genera `default_token_generator` de Django: es un HMAC-SHA256 firmado con la
  `SECRET_KEY` que incluye el id del usuario, el hash de su contraseña y su último acceso. Por
  eso deja de servir apenas se cambia la clave, y vence a los 30 minutos (`PASSWORD_RESET_TIMEOUT`).
- El enlace es `/recuperar/enlace/<uid>/<token>/`. Al abrirlo, el token se valida y se guarda
  en la sesión, y se redirige a `/recuperar/nueva-clave/` para que no quede en la URL.
- El correo sale por el SMTP de Gmail con una contraseña de aplicación guardada en el `.env`.
- Código: `portal/views.py` (`PasswordReset...View`), plantillas en
  `portal/templates/portal/password_recovery/` y `portal/templates/portal/email/`.

## 4. Dashboard por perfil (10 pts)

| Usuario | Debe mostrar |
|---|---|
| `superadmin` | **Dashboard Administrador**: indicadores globales, los 6 mantenedores con su cantidad, Transacciones, botón Nuevo usuario, atenciones por estado y por delegación, actividad de la auditoría |
| `coordinador` | **Dashboard Supervisor**: información operacional (estados, tipos más solicitados, carga por funcionario) y solo los mantenedores autorizados (sin Delegaciones ni Roles) |
| `funcionario` | **Dashboard Administrativo**: sus atenciones, funcionalidades asignadas (Ver, Crear, Exportar) y la lista de operaciones restringidas |

**Qué explicar:** `portal/dashboards.py` elige el panel según el alcance del rol; los datos
respetan la delegación activa y los registros propios. Arriba a la derecha se ve el grupo de
Django y cuántos permisos tiene. Las plantillas están en `portal/templates/portal/dashboard/`
y usan Bootstrap (grilla, tarjetas, tablas y barras de progreso).

## 5. Dos mantenedores CRUD completos (20 pts)

**Mantenedor 1: Delegaciones** (como `superadmin`)

| # | Qué hacer | Qué debe pasar |
|---|---|---|
| 5.1 Crear | Nuevo registro → código `DEL07`, nombre `Delegación Prueba`, comuna `La Serena`, color `#2E7D32` → Guardar | "Delegación: registro creado correctamente." y aparece en la lista |
| 5.2 Validar | Crear otra con código `DEL01` y color `rojo` | "Ya existe una delegación con este código." y "El color debe tener el formato #RRGGBB" |
| 5.3 Buscar | Escribir `prueba` y luego `compañias` (sin tilde) | Filtra; la búsqueda no distingue tildes ni mayúsculas |
| 5.4 Listar | Paginación de 5, filtro de estado Activa/Inactiva | La lista cambia |
| 5.5 Modificar | Editar `DEL07` → cambiar nombre o estado | Se guarda y se ve en la lista |
| 5.6 Eliminar | Papelera en `DEL07` → confirmar | Desaparece (borrado lógico: en phpMyAdmin queda con `deleted_at`) |
| 5.7 Regla | Intentar eliminar `DEL01` | No deja: tiene usuarios y atenciones asociados |
| 5.8 Exportar | Exportar a Excel | Descarga un .xlsx con lo filtrado |

**Mantenedor 2: Tipo de Atención** (o Ítems y metas): repetir crear (`TAT09`), buscar,
editar y eliminar. Un tipo con sub atenciones no se puede eliminar.

**Qué explicar:** todos los mantenedores usan el mismo motor (`portal/crud/views.py`); cada
uno solo declara su configuración (`portal/crud/delegations.py`…). Los formularios de Django
validan en el servidor (`portal/crud/forms.py`), el borrado es lógico y todo queda en la auditoría.

## 6. Transacción funcional: Atenciones (10 pts)

1. Como `funcionario`: **Atenciones → Ingresar atención** → **Guardar** sin llenar nada →
   aparecen los errores de validación.
2. Buscar el vecino escribiendo `Mar` y elegirlo, Tipo **Social**, Sub atención **Ayuda social**,
   descripción de al menos 10 caracteres → **Guardar atención**.
3. **Debe pasar:** "Atención ATN-00xx ingresada correctamente en DEL01…". Número, fecha, hora y
   responsable se asignan solos y la delegación es fija por perfil.
4. Ver el detalle (ojo): muestra vecino, delegación, tipo, sub atención y responsable.
5. Como `delegado`: editar esa atención → estado **En gestión** → Guardar.
6. Como `funcionario`: no aparece el lápiz de editar, y `http://IP/atenciones/<id>/editar/` da 403.
7. En phpMyAdmin, tabla `atencion`: la fila nueva con `neighbor_id`, `delegation_id`,
   `attention_type_id`, `attention_subtype_id` y `responsible_id`.

**Qué explicar:** la transacción relaciona 5 entidades (Vecino, Delegación, Tipo, Sub atención
y Funcionario responsable). Valida que la sub atención pertenezca al tipo, que estén activos,
que la delegación esté permitida para el perfil y el largo de la descripción
(`AttentionForm` en `portal/crud/forms.py`). El número ATN-0001 lo genera el modelo en una
transacción (`Attention.save` en `operaciones/models.py`).

## 7. Base de datos y ORM (5 pts)

- phpMyAdmin → base `sgr_laserena` → tablas `atencion`, `vecino`, `delegacion`, `rol`,
  `rol_permiso`, `funcionario`, `auth_group`, `auth_group_permissions`, `auth_user_groups`.
- En la EC2: `venv/bin/python manage.py showmigrations` (todas con [X]).
- Modelos en `sgr_core/models.py` y `operaciones/models.py`. Relaciones: 1:1 Usuario–Funcionario,
  1:N Delegación–Atención, N:M Funcionario–Delegaciones autorizadas y Grupo–Permiso.
- Diagrama y diccionario de datos: `docs/db/modelo_entidad_relacion.md`.

## 8. AWS EC2 (5 pts)

- Consola de AWS → EC2 → instancia **En ejecución** con su IP pública.
- Navegador: `http://IP/` funcionando.
- Terminal: `sudo systemctl status sgr` → **active (running)**.

## 9. GitHub (3 pts) y uso de IA (2 pts)

- GitHub: README, historial de **commits** (uno por etapa de la Evaluación 3) y `.gitignore`
  (el `.env` con las claves nunca se sube).
- IA: sección 7 del Documento Técnico (prompts, respuestas y cómo se aplicaron).

---

## Preguntas probables del profesor (respuestas cortas)

1. **¿Dónde se validan los permisos?** En el servidor: `portal/access.py`, con
   `ModulePermissionMixin`, que llama a `user.has_perm`. Si falta el permiso, responde 403 y
   lo registra en la auditoría.
2. **¿Cómo se asigna un grupo a un usuario?** Al guardar el usuario con un rol: la señal
   `post_save` de Funcionario (`operaciones/signals.py`) lo deja en el grupo de ese rol.
3. **¿Dónde están los grupos y permisos en la base?** `auth_group`, `auth_permission`,
   `auth_group_permissions` (permisos de cada grupo) y `auth_user_groups` (grupos de cada usuario).
4. **¿Cómo se genera y valida el token?** `default_token_generator.make_token(user)` y
   `check_token(user, token)`: un HMAC con la SECRET_KEY, de un solo uso y que vence en 30 minutos.
5. **¿Qué pasa si alguien adivina el enlace?** No puede: sin la SECRET_KEY no se puede
   fabricar un token válido. Además vence y deja de servir al cambiar la clave.
6. **¿Por qué no usaste Django Admin?** La pauta lo prohíbe: se quitó de `INSTALLED_APPS`
   y de las URL (`/admin/` da 404). Todo se hace desde las plantillas propias.
7. **¿Qué es una migración?** Un archivo que describe un cambio del esquema de la base.
   `migrate` las aplica en orden. Ejemplo: `sgr_core/migrations/0008_role_group.py`.
8. **¿Dónde está la conexión a MariaDB?** `config/settings.py` lee `DB_ENGINE`, `DB_NAME`,
   `DB_USER`, `DB_PASSWORD`, `DB_HOST` y `DB_PORT` desde el `.env`. En tu PC, sin esas
   variables, usa SQLite.
9. **¿Por qué variables de entorno?** Para no subir claves a GitHub: el `.env` está en
   `.gitignore` y cada servidor tiene el suyo.
10. **¿Cómo está desplegado?** EC2 Ubuntu → Nginx (puerto 80) → Gunicorn (servicio systemd
    `sgr`) → Django → MariaDB. Lo instala `deploy/instalar_ec2.sh`.
11. **¿Cómo evitas que un funcionario vea atenciones de otro?** El listado filtra por
    `responsible = usuario` cuando el rol es "solo registros propios" (`attentions_scope`
    en `portal/crud/attentions.py`), y un registro fuera de alcance responde 403.
12. **¿Qué protege el token CSRF?** Que otro sitio envíe formularios en nombre del usuario.
    Todos los POST (incluido Salir) lo llevan.
13. **¿Dónde usas Bootstrap?** Se carga en `base.html` desde `static/portal/vendor/bootstrap/`.
    Los dashboards usan su grilla, tarjetas, tablas, insignias y barras de progreso.

## Si algo falla durante la revisión

| Problema | Qué hacer |
|---|---|
| No llega el correo | Revisa spam. Ejecuta `verificar_despliegue --correo …`, que muestra el error. Plan B: el enlace queda en `sudo journalctl -u sgr -n 50 --no-pager` si el correo está por consola. |
| Bad Request (400) | La IP cambió: `cd ~/sgr-laserena-backend && bash deploy/instalar_ec2.sh` (responde `no` a datos demo). |
| 502 Bad Gateway | `sudo systemctl restart sgr` y `sudo journalctl -u sgr -n 50 --no-pager`. |
| Usuario bloqueado por intentos | Espera 10 minutos o reinicia el servicio (`sudo systemctl restart sgr`). |
| Olvidaste una clave demo | `venv/bin/python manage.py seed_demo` las vuelve a `Demo2026!`. |
