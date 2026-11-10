# Imagen única para los servicios Python: api, ui y relay.
# Cada servicio elige qué programa ejecutar con "command" en compose.yaml.

# Python 3.12, la versión del grupo. "slim" = imagen oficial reducida.
FROM python:3.12-slim

# PYTHONUNBUFFERED: los logs aparecen al instante en "docker compose logs"
# PYTHONDONTWRITEBYTECODE: no genera archivos .pyc dentro del contenedor
# PIP_*: no guarda caché de descargas (imagen más chica) ni avisa versiones de pip
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# 1) Primero solo las dependencias: Docker reutiliza esta capa mientras
#    requirements no cambie, y los rebuilds tardan segundos en vez de minutos.
#    Se instala requirements-dev.txt (incluye requirements.txt + pytest)
#    para poder correr "docker compose exec api pytest -q".
COPY requirements.txt requirements-dev.txt ./
RUN pip install -r requirements-dev.txt

# 2) Después el código. Lo que está en .dockerignore (.env, data/, .git, n8n/...)
#    no se copia: las claves llegan por variables de entorno y los datos por volumen.
COPY . .

# 3) Usuario sin privilegios de administrador (uid 1000, el habitual en WSL/Linux).
#    data/ se crea vacía por si el contenedor arranca sin el volumen montado.
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /app/data/cuentos \
    && chown -R appuser:appuser /app
USER appuser

# Documentar los puertos que usan los servicios (la publicación real está en compose.yaml)
EXPOSE 8000 8501

# Sin CMD: cada servicio define su comando en compose.yaml.
