# Tienda de Cuentos IA

Tienda virtual automatizada donde la IA escribe cuentos infantiles en Markdown, una persona los revisa y aprueba, n8n los publica en un canal de Telegram y un bot atiende los pedidos y entrega el archivo. Los cuentos gratuitos se entregan al instante; los pagos se entregan solo después de que una persona valida el comprobante de transferencia.

Trabajo Práctico 2 de **Elementos de Programación IA y LowCode** (UniCABA).

| Servicio | Qué hace | Dirección |
|---|---|---|
| `api` | FastAPI: reglas de negocio, IA con fallback, SQLite | http://localhost:8000/docs |
| `ui` | Panel Streamlit para revisar, aprobar y validar pagos | http://localhost:8501 |
| `n8n` | Workflows de publicación, atención, entrega y reporte | http://localhost:5678 |
| `relay` | Pasa los mensajes de Telegram a n8n (opcional) | — |

La arquitectura completa está en [`docs/arquitectura.md`](docs/arquitectura.md).

## Requisitos

- **Docker Desktop** instalado y abierto, con el cartel **Engine running** abajo a la izquierda. Verificá con `docker --version` y `docker compose version`.
- En Windows, **WSL 2**. Si Docker muestra *"WSL not installed"*, abrí PowerShell **como administrador**, corré `wsl --install` y reiniciá la compu.
- **Git**, para clonar el repo.
- Opcional: una clave gratuita de Gemini o Groq. Sin claves el sistema funciona igual en modo `mock` (simulación sin IA real).
- Opcional: un bot de Telegram creado con @BotFather y un canal donde el bot sea administrador.

## Puesta en marcha

**1. Clonar el repositorio**

```powershell
git clone https://github.com/Edudando/Tienda-Cuentos-IA.git
cd Tienda-Cuentos-IA
```

**2. Crear el archivo `.env`** a partir de la plantilla. Este archivo tiene las claves y nunca se sube a Git.

```powershell
copy .env.example .env      # Windows
# cp .env.example .env      # Linux / macOS
```

Si no tenés claves todavía, abrí `.env` y dejá `IA_PROVEEDORES=mock`. También hace falta `N8N_ENCRYPTION_KEY`, una clave que cifra las credenciales de n8n: `iniciar.bat` la genera sola. Si la cargás a mano, puede ser cualquier texto largo, pero **una vez creada no se cambia**. Con claves, completá `GEMINI_API_KEY` y/o `GROQ_API_KEY` y dejá `IA_PROVEEDORES=gemini,groq,ollama`.

**Atajo:** doble clic en `iniciar.bat` hace los pasos 2 a 5 solo (abre Docker, crea el `.env` y la clave de n8n, levanta todo, carga los ejemplos y abre el panel).

**3. Levantar todo.** Ejecutalo dentro de la carpeta del proyecto, donde está `compose.yaml`. Si no, Docker responde *"no configuration file provided"*.

```powershell
docker compose up -d --build
```

La primera vez tarda unos minutos porque descarga Python y n8n. Cuando termina, `docker compose ps` tiene que mostrar `api` como **healthy** y `ui` y `n8n` como **running**.

**4. Cargar los cuentos de ejemplo**

```powershell
docker compose exec api python -m scripts.cargar_ejemplos
```

Quedan dos cuentos aprobados: uno gratis y uno de $1.500. Si preferís que queden pendientes para aprobarlos desde el panel, agregá `--pendiente` al final.

**5. Abrir el panel** en http://localhost:8501.

**6. Configurar n8n** (solo la primera vez)

1. Entrá a http://localhost:5678 y creá el usuario dueño (queda guardado en el volumen `n8n_data`).
2. Importá los workflows desde la terminal:

   ```powershell
   docker compose exec n8n n8n import:workflow --separate --input=/home/node/workflows
   ```

3. Abrí cada workflow y activalo con el interruptor **Active**. Dentro de n8n la API se llama `http://api:8000`, no `localhost`.

**7. Conectar Telegram** (opcional). Completá `TELEGRAM_BOT_TOKEN`, `TELEGRAM_BOT_USERNAME`, `TELEGRAM_CHANNEL_ID` y `ADMIN_CHAT_ID` en `.env` y levantá también el relay:

```powershell
docker compose --profile telegram up -d --build
```

Para saber tu `ADMIN_CHAT_ID`, mandale cualquier mensaje al bot y abrí `https://api.telegram.org/bot<TOKEN>/getUpdates`: el número está en `message.chat.id`.

## El panel

| Pestaña | Para qué sirve |
|---|---|
| Resumen | Indicadores: cuentos por revisar, pagos por validar, entregas y consultas por regla o IA |
| Generar | Pedirle un cuento nuevo a la IA (tema, edad, personaje, precio) |
| Revisión | Aprobar, rechazar o editar cuentos. Muestra por separado las validaciones del código y el contenido de la IA |
| Catálogo | Cuentos aprobados y publicados, con el link de pedido y la descarga del `.md` |
| Pedidos y pagos | Ver pedidos, mirar el comprobante, validar o rechazar el pago y entregar a mano si n8n no respondió |
| Consultas | Historial de mensajes del bot y un campo para probar el bot sin Telegram |

El panel no tiene lógica de negocio: todo lo decide la API. Si algo falla, el panel muestra el código y el motivo (`404 · No existe`, `409 · No corresponde al estado actual`, `422 · Datos inválidos`, `503 · Servicio externo no disponible`).

## Comandos útiles

| Acción | Comando |
|---|---|
| Ver el estado de los contenedores | `docker compose ps` |
| Ver los logs de la API en vivo | `docker compose logs -f api` |
| Reiniciar un servicio | `docker compose restart api` |
| Reconstruir después de cambiar código | `docker compose up -d --build` |
| Detener todo (los datos quedan) | `docker compose down` |
| Borrar también los datos de n8n | `docker compose down -v` |
| Correr los tests (fuera de Docker) | `pip install -r requirements-dev.txt` y `pytest -q` |

## Problemas frecuentes

- **`port is already allocated`**: otro programa usa el puerto 8000, 8501 o 5678. Cerralo o cambiá el primer número del puerto en `compose.yaml` (por ejemplo `"8001:8000"`).
- **`env file .env not found`**: falta el paso 2.
- **`Falta N8N_ENCRYPTION_KEY`**: agregá esa línea al `.env` o usá `iniciar.bat`, que la genera.
- **n8n no arranca y el log dice `Mismatching encryption keys`**: cambió la clave después de crear la cuenta de n8n. Volvé a poner la anterior o, si la cuenta era solo de prueba, borrá los datos de n8n con `docker volume rm tienda-cuentos_n8n_data` y creala de nuevo.
- **El panel dice "No se pudo conectar con la API"**: la API todavía arranca o falló. Mirá `docker compose logs api`.
- **La entrega devuelve 503**: falta `TELEGRAM_BOT_TOKEN`. Es el comportamiento esperado sin bot.
- **La IA devuelve 503**: no hay claves o se agotó la cuota. Agregá `mock` al final de `IA_PROVEEDORES` para la demo.
- **Cambié el código y no se ve**: hay que reconstruir con `--build`, porque el código está copiado dentro de la imagen.

## Estructura del repositorio

```
app/              API FastAPI (endpoints, servicios, reglas, IA, SQLite)
ui/               Panel Streamlit (app.py + cliente_api.py)
relay/            Puente Telegram → n8n
n8n/workflows/    Workflows exportados en JSON
scripts/          Carga de cuentos de ejemplo
data/             Base SQLite y cuentos .md (no se suben a Git, salvo los ejemplos)
tests/            Pruebas automáticas con pytest
docs/             Arquitectura, bitácora de IA, verificación y responsabilidades
Dockerfile        Imagen de Python compartida por api, ui y relay
iniciar.bat       Arranque con doble clic (llama a iniciar.ps1)
compose.yaml      Levanta todos los servicios con un comando
.env.example      Plantilla de configuración sin secretos
```

## Equipo

Ver [`docs/responsabilidades.md`](docs/responsabilidades.md).
