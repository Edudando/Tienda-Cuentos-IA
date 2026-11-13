# Responsabilidades del equipo

Cada integrante es referente de una parte del sistema, pero todos pueden explicarlo y
modificarlo entero. El proceso completo es responsabilidad de los cuatro.

| Integrante | Nombre | Referente de | Archivos principales |
|---|---|---|---|
| 1 | [completar] | API FastAPI, reglas de validación y base SQLite | `app/main.py`, `app/servicios/`, `app/validaciones.py`, `app/db.py`, `app/modelos.py`, `tests/` |
| 2 | [completar] | IA: prompts, fallback Gemini → Groq → Ollama, bitácora | `app/ia.py`, prompts en `app/servicios/productos.py` y `app/servicios/consultas.py`, `docs/bitacora_ia.md` |
| 3 | [completar] | n8n, bot y canal de Telegram, relay | `n8n/workflows/`, `relay/main.py`, `app/telegram_client.py` |
| 4 | [completar] | Panel Streamlit, Docker, documentación y presentación | `ui/`, `Dockerfile`, `compose.yaml`, `.env.example`, `README.md`, `docs/` |

## Tareas cruzadas (quien hace estos puntos)

| Integrante | Tarea sobre la parte de otro |
|---|---|
| 1 | Cambiar el intervalo del workflow de publicación en n8n y explicar qué nodo lo controla |
| 2 | Agregar una regla de validación nueva en `app/validaciones.py` y una prueba que la cubra |
| 3 | Agregar un campo nuevo al endpoint `/estadisticas` y mostrarlo en el reporte diario |
| 4 | Cambiar el texto de respuesta del bot cuando la IA no está disponible y explicar en qué archivo está |
