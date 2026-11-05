#!/usr/bin/env bash
# =============================================================================
# Instalación del SGR en una instancia AWS EC2 (Ubuntu Server 24.04 LTS).
#
# Deja funcionando: MariaDB (base de datos), el proyecto Django en un entorno
# virtual, Gunicorn como servicio systemd ("sgr"), Nginx en el puerto 80 y,
# si se pide, phpMyAdmin en http://<IP>/phpmyadmin/ para ver las tablas.
#
# Uso (en la EC2, dentro de la carpeta del proyecto ya clonado):
#     bash deploy/instalar_ec2.sh
#
# Se puede volver a ejecutar sin problemas (no borra datos): sirve también para
# actualizar después de un "git pull". Las preguntas se pueden responder por
# variables de entorno, por ejemplo:
#     DB_PASSWORD=MiClave2026 GMAIL_USER=yo@gmail.com GMAIL_APP_PASSWORD=xxxx \
#     INSTALAR_PHPMYADMIN=si CARGAR_DEMO=si bash deploy/instalar_ec2.sh
# =============================================================================
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_USER="$(id -un)"
APP_GROUP="$(id -gn)"
VENV="$PROJECT_DIR/venv"
ENV_FILE="$PROJECT_DIR/.env"
DB_NAME="${DB_NAME:-sgr_laserena}"
DB_USER="${DB_USER:-sgr_user}"

paso() { printf '\n\033[1;31m==> %s\033[0m\n' "$*"; }
ok()   { printf '    \033[1;32m✓\033[0m %s\n' "$*"; }
aviso(){ printf '    \033[1;33m!\033[0m %s\n' "$*"; }

preguntar() {  # preguntar VARIABLE "Texto" "valor por defecto" [secreto]
    local var="$1" texto="$2" defecto="${3:-}" secreto="${4:-}" valor
    if [ -n "${!var:-}" ]; then return; fi
    if [ -n "$secreto" ]; then
        read -rsp "    $texto: " valor; echo
    else
        read -rp "    $texto [${defecto}]: " valor
    fi
    printf -v "$var" '%s' "${valor:-$defecto}"
}

if [ "$APP_USER" = "root" ]; then
    echo "Ejecuta el script con el usuario normal (ubuntu), no con sudo." >&2
    exit 1
fi
if [ ! -f "$PROJECT_DIR/manage.py" ]; then
    echo "No encuentro manage.py en $PROJECT_DIR." >&2
    exit 1
fi

# -----------------------------------------------------------------------------
paso "1/8 Memoria de intercambio (evita que la instancia se quede sin RAM)"
if [ "$(awk '/MemTotal/{print $2}' /proc/meminfo)" -lt 2000000 ] && ! swapon --show | grep -q .; then
    sudo fallocate -l 2G /swapfile && sudo chmod 600 /swapfile
    sudo mkswap /swapfile >/dev/null && sudo swapon /swapfile
    grep -q '/swapfile' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
    ok "Swap de 2 GB activado"
else
    ok "No hace falta swap"
fi

# -----------------------------------------------------------------------------
paso "2/8 Paquetes del sistema (Python, MariaDB, Nginx)"
sudo apt-get update -qq
sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq \
    python3-venv python3-dev build-essential pkg-config default-libmysqlclient-dev \
    mariadb-server nginx git curl >/dev/null
sudo systemctl enable --now mariadb >/dev/null 2>&1
ok "Paquetes instalados y MariaDB en ejecución"

# -----------------------------------------------------------------------------
paso "3/8 Base de datos MariaDB ($DB_NAME, usuario $DB_USER)"
if [ -f "$ENV_FILE" ] && grep -q '^DB_PASSWORD=' "$ENV_FILE" && [ -z "${DB_PASSWORD:-}" ]; then
    DB_PASSWORD="$(grep '^DB_PASSWORD=' "$ENV_FILE" | head -1 | cut -d= -f2-)"
    ok "Se reutiliza la contraseña de la base que ya está en .env"
fi
preguntar DB_PASSWORD "Contraseña para el usuario $DB_USER de MariaDB (invéntala y anótala)" "" secreto
if [ -z "$DB_PASSWORD" ]; then echo "La contraseña de la base no puede quedar vacía." >&2; exit 1; fi
if [[ "$DB_PASSWORD" == *"'"* ]]; then echo "La contraseña no puede llevar comillas simples (')." >&2; exit 1; fi
sudo mariadb <<SQL
CREATE DATABASE IF NOT EXISTS \`$DB_NAME\` CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
CREATE USER IF NOT EXISTS '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
ALTER USER '$DB_USER'@'localhost' IDENTIFIED BY '$DB_PASSWORD';
GRANT ALL PRIVILEGES ON \`$DB_NAME\`.* TO '$DB_USER'@'localhost';
FLUSH PRIVILEGES;
SQL
ok "Base $DB_NAME lista (utf8mb4)"

# -----------------------------------------------------------------------------
paso "4/8 Entorno virtual y dependencias de Python"
[ -d "$VENV" ] || python3 -m venv "$VENV"
"$VENV/bin/pip" install -q --upgrade pip
"$VENV/bin/pip" install -q -r "$PROJECT_DIR/requirements.txt"
ok "Dependencias instaladas en $VENV"

# -----------------------------------------------------------------------------
paso "5/8 Archivo .env (configuración y secretos; nunca se sube a GitHub)"
# IP y nombre públicos de la instancia (servicio de metadatos de EC2, IMDSv2).
TOKEN="$(curl -sf -m 3 --noproxy '*' -X PUT http://169.254.169.254/latest/api/token \
    -H 'X-aws-ec2-metadata-token-ttl-seconds: 60' || true)"
meta() { curl -sf -m 3 --noproxy '*' -H "X-aws-ec2-metadata-token: $TOKEN" \
    "http://169.254.169.254/latest/meta-data/$1" || true; }
PUBLIC_IP="$(meta public-ipv4)"
PUBLIC_DNS="$(meta public-hostname)"
[[ "$PUBLIC_IP" =~ ^[0-9]{1,3}(\.[0-9]{1,3}){3}$ ]] || PUBLIC_IP=""
[[ "$PUBLIC_DNS" =~ ^[A-Za-z0-9.-]+$ ]] || PUBLIC_DNS=""
HOSTS="localhost,127.0.0.1"
[ -n "$PUBLIC_IP" ] && HOSTS="$PUBLIC_IP,$HOSTS"
[ -n "$PUBLIC_DNS" ] && HOSTS="$PUBLIC_DNS,$HOSTS"

if [ ! -f "$ENV_FILE" ]; then
    preguntar GMAIL_USER "Correo de Gmail para enviar la recuperación (Enter para omitir)" ""
    if [ -n "${GMAIL_USER:-}" ]; then
        preguntar GMAIL_APP_PASSWORD "Contraseña de aplicación de Gmail (16 letras)" "" secreto
    fi
    SECRET="$("$VENV/bin/python" -c 'import secrets; print(secrets.token_urlsafe(50))')"
    {
        echo "DJANGO_SECRET_KEY=$SECRET"
        echo "DEBUG=False"
        echo "ALLOWED_HOSTS=$HOSTS"
        echo "DB_ENGINE=django.db.backends.mysql"
        echo "DB_NAME=$DB_NAME"
        echo "DB_USER=$DB_USER"
        echo "DB_PASSWORD=$DB_PASSWORD"
        echo "DB_HOST=127.0.0.1"
        echo "DB_PORT=3306"
        echo "PASSWORD_RESET_TIMEOUT=1800"
        if [ -n "${GMAIL_USER:-}" ]; then
            echo "EMAIL_BACKEND=django.core.mail.backends.smtp.EmailBackend"
            echo "EMAIL_HOST=smtp.gmail.com"
            echo "EMAIL_PORT=587"
            echo "EMAIL_USE_TLS=True"
            echo "EMAIL_HOST_USER=$GMAIL_USER"
            echo "EMAIL_HOST_PASSWORD=${GMAIL_APP_PASSWORD// /}"
            echo "DEFAULT_FROM_EMAIL=\"SGR La Serena <$GMAIL_USER>\""
        fi
    } > "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok ".env creado (DEBUG=False, MariaDB, ALLOWED_HOSTS=$HOSTS)"
    [ -z "${GMAIL_USER:-}" ] && aviso "Sin Gmail: los correos se imprimirán en el log (agrégalo después en .env)"
else
    # Actualiza ALLOWED_HOSTS por si la IP pública cambió al reiniciar el lab.
    if grep -q '^ALLOWED_HOSTS=' "$ENV_FILE"; then
        sed -i "s|^ALLOWED_HOSTS=.*|ALLOWED_HOSTS=$HOSTS|" "$ENV_FILE"
    else
        echo "ALLOWED_HOSTS=$HOSTS" >> "$ENV_FILE"
    fi
    ok ".env existente conservado (ALLOWED_HOSTS=$HOSTS)"
fi

# -----------------------------------------------------------------------------
paso "6/8 Migraciones, archivos estáticos y datos de demostración"
cd "$PROJECT_DIR"
"$VENV/bin/python" manage.py migrate --noinput
"$VENV/bin/python" manage.py collectstatic --noinput >/dev/null
mkdir -p "$PROJECT_DIR/media"
preguntar CARGAR_DEMO "¿Cargar/actualizar los datos de demostración (usuarios demo con clave Demo2026!)? si/no" "si"
if [ "${CARGAR_DEMO,,}" = "si" ] || [ "${CARGAR_DEMO,,}" = "s" ]; then
    "$VENV/bin/python" manage.py seed_demo >/dev/null
    ok "Datos de demostración cargados"
fi
ok "Base de datos y estáticos al día"

# -----------------------------------------------------------------------------
paso "7/8 Servicio systemd 'sgr' (Gunicorn en 127.0.0.1:8000)"
sudo tee /etc/systemd/system/sgr.service >/dev/null <<UNIT
[Unit]
Description=SGR Municipalidad de La Serena (gunicorn)
After=network.target mariadb.service

[Service]
User=$APP_USER
Group=$APP_GROUP
WorkingDirectory=$PROJECT_DIR
EnvironmentFile=$ENV_FILE
# Un proceso con 4 hilos: la caché en memoria (bloqueo tras 5 intentos de login
# y espera para reenviar el enlace) queda compartida entre todas las peticiones.
ExecStart=$VENV/bin/gunicorn config.wsgi:application --bind 127.0.0.1:8000 --workers 1 --threads 4 --timeout 60
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
UNIT
sudo systemctl daemon-reload
sudo systemctl enable sgr >/dev/null 2>&1
sudo systemctl restart sgr
ok "Servicio sgr activo (se inicia solo al encender la instancia)"

# -----------------------------------------------------------------------------
paso "8/8 Nginx en el puerto 80 (y phpMyAdmin opcional)"
preguntar INSTALAR_PHPMYADMIN "¿Instalar phpMyAdmin para ver las tablas en el navegador? si/no" "si"
PMA_BLOCK=""
if [ "${INSTALAR_PHPMYADMIN,,}" = "si" ] || [ "${INSTALAR_PHPMYADMIN,,}" = "s" ]; then
    echo "phpmyadmin phpmyadmin/dbconfig-install boolean false" | sudo debconf-set-selections
    echo "phpmyadmin phpmyadmin/reconfigure-webserver multiselect" | sudo debconf-set-selections
    sudo DEBIAN_FRONTEND=noninteractive apt-get install -y -qq --no-install-recommends \
        phpmyadmin php-cli php-fpm php-mysql php-mbstring php-zip php-gd php-curl >/dev/null
    PHP_VER="$(php -r 'echo PHP_MAJOR_VERSION.".".PHP_MINOR_VERSION;')"
    sudo systemctl enable --now "php$PHP_VER-fpm" >/dev/null 2>&1 || true
    PHP_SOCK="/run/php/php$PHP_VER-fpm.sock"
    PMA_BLOCK="    location /phpmyadmin {
        root /usr/share/;
        index index.php;
        try_files \$uri \$uri/ =404;
        location ~ ^/phpmyadmin/(.+\\.php)\$ {
            root /usr/share/;
            fastcgi_pass unix:$PHP_SOCK;
            fastcgi_index index.php;
            fastcgi_param SCRIPT_FILENAME \$document_root\$fastcgi_script_name;
            include fastcgi_params;
        }
        location ~* ^/phpmyadmin/(.+\\.(jpg|jpeg|gif|css|png|js|ico|html|xml|txt|svg|woff|woff2|ttf|map))\$ {
            root /usr/share/;
        }
    }"
    ok "phpMyAdmin instalado: entra con el usuario $DB_USER y su contraseña"
fi
TMP_CONF="$(mktemp)"
export PMA_BLOCK PROJECT_DIR
python3 - "$PROJECT_DIR/deploy/nginx-sgr.conf" "$TMP_CONF" <<'PY'
import os, sys
src, dst = sys.argv[1], sys.argv[2]
text = open(src, encoding="utf-8").read()
text = text.replace("__PROJECT_DIR__", os.environ["PROJECT_DIR"])
text = "\n".join(
    os.environ["PMA_BLOCK"] if line.strip() == "__PHPMYADMIN__" else line
    for line in text.splitlines()
) + "\n"
open(dst, "w", encoding="utf-8").write(text)
PY
sudo mv "$TMP_CONF" /etc/nginx/sites-available/sgr
sudo chmod 644 /etc/nginx/sites-available/sgr
sudo ln -sf /etc/nginx/sites-available/sgr /etc/nginx/sites-enabled/sgr
sudo rm -f /etc/nginx/sites-enabled/default
# Nginx (usuario www-data) necesita atravesar la carpeta personal para servir /media/.
chmod o+x "$HOME"
chmod -R o+rX "$PROJECT_DIR/media"
sudo nginx -t
sudo systemctl enable nginx >/dev/null 2>&1
sudo systemctl restart nginx
ok "Nginx sirviendo el sitio en el puerto 80"

# -----------------------------------------------------------------------------
paso "Listo"
"$VENV/bin/python" manage.py verificar_despliegue || true
echo
if [ -n "$PUBLIC_IP" ]; then
    echo "    Abre en el navegador:  http://$PUBLIC_IP/"
    [ -n "$PMA_BLOCK" ] && echo "    phpMyAdmin:            http://$PUBLIC_IP/phpmyadmin/  (usuario: $DB_USER)"
fi
echo "    Estado del servicio:   sudo systemctl status sgr"
echo "    Errores recientes:     sudo journalctl -u sgr -n 50 --no-pager"
