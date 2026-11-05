# Despliegue en AWS Academy (EC2) paso a paso

Guía para publicar el SGR en una instancia EC2 del **Learner Lab de AWS Academy**
con **MariaDB** (base de datos), **Gunicorn + systemd** (aplicación Django),
**Nginx** (puerto 80) y **phpMyAdmin** (opcional, para ver las tablas).

Todo lo instala el script `deploy/instalar_ec2.sh`. Se probó de punta a punta en
Ubuntu Server 24.04 LTS con MariaDB 10.11: migraciones, datos demo, las 286
pruebas, Nginx → Gunicorn, archivos subidos (`/media/`) y phpMyAdmin.

> **Base de datos:** en tu computador el proyecto usa **SQLite** (`db.sqlite3`)
> porque el `.env` local no define `DB_ENGINE`. En la EC2 el script deja
> **MariaDB** (`DB_ENGINE=django.db.backends.mysql`). phpMyAdmin no es una base de
> datos: es una página web para ver y administrar la base MariaDB.

---

## 0. Antes de empezar

- El código debe estar en GitHub, en la rama `main`: la EC2 lo descarga desde ahí.
  El repositorio `cristobal-estay/sgr-laserena-backend` es público, así que no
  pide clave.
- Ten a mano (opcional, pero necesaria para mostrar la recuperación de
  contraseña) una **contraseña de aplicación de Gmail**: Cuenta de Google →
  Seguridad → Verificación en 2 pasos (activarla) → Contraseñas de aplicaciones.

## 1. Iniciar el laboratorio

1. Entra a AWS Academy → tu curso → **Módulos** → **Learner Lab**.
2. Presiona **Start Lab** y espera a que el círculo junto a **AWS** se ponga verde.
3. Presiona **AWS**: se abre la consola de AWS (región Norte de Virginia, us-east-1).

> La sesión del laboratorio dura unas 4 horas. Al terminar, AWS **detiene** la
> instancia. La próxima vez: **Start Lab** → EC2 → revisa que la instancia esté
> "En ejecución" (si no, **Estado de la instancia → Iniciar instancia**). La IP
> pública puede cambiar: ver el paso 6.

## 2. Crear la instancia EC2

En la consola: **EC2 → Instancias → Lanzar instancias**.

| Campo | Valor |
|---|---|
| Nombre | `sgr-laserena` |
| Imagen (AMI) | **Ubuntu Server 24.04 LTS** (64 bits x86) |
| Tipo de instancia | `t2.micro` o `t3.micro` (si está disponible, `t3.small` va más holgado; el script agrega memoria swap igual) |
| Par de claves | `vockey` (la del laboratorio) |
| Configuración de red → **Editar** → Crear grupo de seguridad | Nombre `sgr-web` con 2 reglas de entrada: **SSH (22)** desde *Mi IP* (o *Cualquier lugar* si cambias de red) y **HTTP (80)** desde *Cualquier lugar 0.0.0.0/0* |
| Almacenamiento | 15 GiB gp3 (8 GiB también funciona) |

Presiona **Lanzar instancia** y espera el estado **En ejecución** y **2/2
comprobaciones superadas**.

**Recomendado: IP elástica.** EC2 → **Direcciones IP elásticas** → Asignar →
Acciones → **Asociar** a la instancia `sgr-laserena`. Así la IP no cambia entre
sesiones del laboratorio.

## 3. Conectarse a la instancia

**Opción A (la más fácil, desde el navegador):** selecciona la instancia →
**Conectar** → pestaña **EC2 Instance Connect** → usuario `ubuntu` → **Conectar**.

**Opción B (desde tu PC con PowerShell):** en el Learner Lab → **AWS Details** →
**Download PEM** (`labsuser.pem`). Luego:

```powershell
icacls "$HOME\Downloads\labsuser.pem" /inheritance:r /grant:r "$($env:USERNAME):(R)"
ssh -i "$HOME\Downloads\labsuser.pem" ubuntu@TU_IP_PUBLICA
```

## 4. Instalar el proyecto (un solo script)

En la terminal de la instancia:

```bash
git clone https://github.com/cristobal-estay/sgr-laserena-backend.git
cd sgr-laserena-backend
bash deploy/instalar_ec2.sh
```

El script pregunta:

1. **Contraseña para el usuario `sgr_user` de MariaDB**: invéntala y anótala
   (también es la de phpMyAdmin). Sin comillas simples.
2. **Correo de Gmail** y su **contraseña de aplicación** (Enter para omitir; se
   puede agregar después en el `.env`).
3. **Cargar datos de demostración**: `si` (usuarios demo con clave `Demo2026!`).
4. **Instalar phpMyAdmin**: `si`.

Tarda entre 5 y 10 minutos. Al final muestra la verificación (`✓` / `!` / `✗`)
y la dirección del sitio.

El script deja todo esto:

- MariaDB con la base `sgr_laserena` (utf8mb4) y el usuario `sgr_user`.
- Entorno virtual en `~/sgr-laserena-backend/venv` con las dependencias.
- `.env` con `DEBUG=False`, una `DJANGO_SECRET_KEY` nueva, `ALLOWED_HOSTS` con la
  IP pública, MariaDB y Gmail (permisos 600, nunca se sube a GitHub).
- Migraciones aplicadas, `collectstatic` y datos demo.
- Servicio **`sgr`** (Gunicorn en 127.0.0.1:8000) que arranca solo al encender.
- **Nginx** en el puerto 80 (sirve también `/media/` y, si se pidió, `/phpmyadmin/`).

## 5. Probar que funciona

- Sitio: `http://TU_IP_PUBLICA/` (con **http**, no https) → pantalla de login.
- phpMyAdmin: `http://TU_IP_PUBLICA/phpmyadmin/` → usuario `sgr_user` y la
  contraseña del paso 4 → base `sgr_laserena` → tablas (`atencion`, `rol`,
  `auth_group`, `auth_user_groups`...).
- Chequeo completo y correo de prueba:

  ```bash
  cd ~/sgr-laserena-backend
  venv/bin/python manage.py verificar_despliegue --correo tu-correo@gmail.com
  ```

## 6. Actualizar el sitio (cambios nuevos o la IP cambió)

```bash
cd ~/sgr-laserena-backend
git pull origin main
bash deploy/instalar_ec2.sh
```

No borra datos y actualiza `ALLOWED_HOSTS` con la IP pública actual. Si no quieres
que los usuarios demo vuelvan a la clave `Demo2026!`, responde `no` a "cargar
datos de demostración".

Si cambias algo a mano en el `.env`: `sudo systemctl restart sgr`.

## 7. Problemas frecuentes

| Síntoma | Causa y solución |
|---|---|
| La página no carga (se queda esperando) | El grupo de seguridad no tiene **HTTP (80)** abierto, o escribiste `https://`. Usa `http://`. |
| **Bad Request (400)** | La IP pública cambió. Ejecuta de nuevo `bash deploy/instalar_ec2.sh` (o asocia una IP elástica). |
| **502 Bad Gateway** | El servicio `sgr` está detenido o falló: `sudo systemctl status sgr` y `sudo journalctl -u sgr -n 50 --no-pager`. |
| **Server Error (500)** | Mira el detalle con `sudo journalctl -u sgr -n 50 --no-pager`. Si dice "Missing staticfiles manifest", ejecuta `venv/bin/python manage.py collectstatic --noinput` y `sudo systemctl restart sgr`. |
| No llega el correo de recuperación | `verificar_despliegue --correo ...` muestra el error. Revisa `EMAIL_HOST_USER` y `EMAIL_HOST_PASSWORD` (contraseña de aplicación sin espacios) en `.env`, la carpeta de spam y luego `sudo systemctl restart sgr`. El usuario debe tener ese correo registrado. |
| phpMyAdmin no deja entrar | Usa `sgr_user` (no `root`) y la contraseña del paso 4. |
| Error de Nginx | `sudo nginx -t` y `sudo tail -n 50 /var/log/nginx/error.log`. |

## 8. Capturas para el documento técnico

1. Consola EC2 con la instancia **En ejecución** (ID, tipo e IP pública).
2. Navegador con `http://TU_IP_PUBLICA/` mostrando el login o un dashboard.
3. Terminal con `sudo systemctl status sgr` en **active (running)**.
4. phpMyAdmin con las tablas de `sgr_laserena` (sirve para "Capturas de tablas").
