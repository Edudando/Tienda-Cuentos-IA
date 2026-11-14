# Workflows de n8n y relay de Telegram

Los cuatro workflows están en `n8n/workflows/` y se importan con:

```powershell
docker compose exec n8n n8n import:workflow --separate --input=/workflows
```

Todos llaman a la API con `{{ $env.API_URL }}` (dentro de Docker es `http://api:8000`) y a Telegram con nodos **HTTP Request** que usan `{{ $env.TELEGRAM_BOT_TOKEN }}`. Así no hace falta cargar credenciales a mano en n8n: todo sale del `.env`.

## Resumen

| Workflow | Qué lo dispara | Condición | De dónde sale el dato |
|---|---|---|---|
| 1 · Publicación en el canal | Schedule: cada 2 minutos | ¿La promo es válida? | `promo_valida`, calculado por la API con las reglas de `validaciones.py` |
| 2 · Atención del bot | Webhook `/telegram`, llamado por el relay | ¿Es foto? ¿Es texto? ¿Es un pedido? ¿Es gratis? ¿Había un pedido esperando pago? | `tipo` lo pone el relay; `intencion` lo devuelve `POST /consultas`; `es_gratis` lo devuelve `POST /pedidos` |
| 3 · Entrega del cuento | Webhook `/entrega`, llamado por la API o por el workflow 2 | ¿Puede entregarse? ¿Se entregó? | `puede_entregar` de `GET /pedidos/{id}`: es gratis o el pago fue validado por una persona |
| 4 · Reporte diario | Schedule: todos los días a las 20:00 | ¿Hay tareas pendientes? | `hay_pendientes` de `GET /estadisticas` |

## 1 · Publicación en el canal

Cada 2 minutos pide `GET /productos?estado=aprobado`, es decir, los cuentos que una persona ya aprobó en el panel. Por cada uno:

- **Si la promo es válida**: lo publica en el canal con el botón **📖 Pedir este cuento**. El botón es un link `https://t.me/<bot>?start=prod_<id>` que abre el bot con ese pedido. Después llama a `PATCH /productos/{id}/publicacion` con el `message_id` de Telegram, y el cuento pasa a **publicado**.
- **Si no**: le avisa al admin por Telegram que edite la promo.

Para cambiar el intervalo (tarea cruzada del Integrante 1): nodo **Cada 2 minutos** → *Minutes Between Triggers*.

## 2 · Atención del bot

Lo dispara cada mensaje privado al bot, que llega por el relay. Qué pasa cuando el cliente toca **Pedir este cuento**:

1. Telegram abre el bot y el cliente manda `/start prod_2`. El relay lo pasa al webhook como `{"tipo": "texto", "texto": "/start prod_2", ...}`.
2. **¿Es una foto?** No. **¿Es texto?** Sí.
3. **Clasificar el mensaje** (`POST /consultas`): una regla reconoce `/start prod_N` sin gastar IA y devuelve `intencion: pedido, producto_id: 2`. Si el producto no existe o no está publicado (`/start prod_999`), devuelve una consulta con el catálogo.
4. **Responder al cliente** con la respuesta que armó la API.
5. **¿Es un pedido?** Sí → **Crear pedido** (`POST /pedidos`).
6. **¿Es gratis?**
   - Sí → **Disparar entrega**: llama al workflow 3 por su webhook (`http://localhost:5678/webhook/entrega`). Así se llama un workflow desde otro.
   - No → **Pasar a esperando pago** y **Mandar datos de transferencia** (alias y monto, que arma la API).

Cuando el cliente manda la **foto del comprobante**: **Registrar comprobante** (`POST /pedidos/comprobante`) la asocia a su último pedido que espera pago. Si existía, se le agradece al cliente y se le avisa al admin para que lo valide en el panel. Si no existía (foto suelta, API 404), se le responde que no hay pedidos pendientes. Si manda otra cosa, como un sticker o un audio, se le explica que el bot entiende texto y fotos.

## 3 · Entrega del cuento

Recibe `{"pedido_id": N}` por el webhook `/entrega`. Lo llaman dos lugares:

- El **workflow 2**, para los cuentos gratis.
- La **API**, cuando una persona valida el pago en el panel (`PATCH /pedidos/{id}/pago` → `disparar_entrega()` en `app/servicios/pedidos.py`).

El workflow busca el pedido y evalúa **¿Puede entregarse?** con `puede_entregar`. Si se puede, llama a `POST /pedidos/{id}/entregar`: la API manda el `.md` con `sendDocument` y vuelve a controlar el pago (responde 409 si no está pago). Al final, le avisa al admin si se entregó o si falló. Si el pedido no está pago, no envía nada y avisa al admin.

## 4 · Reporte diario

Todos los días a las 20:00 (hora de Argentina) pide `GET /estadisticas` y le manda al admin un resumen: cuentos publicados, pedidos entregados y consultas resueltas por reglas o por IA. Si hay cuentos por revisar o pagos por validar, el mensaje los destaca.

## El relay (`relay/main.py`)

**Por qué existe:** el nodo *Telegram Trigger* de n8n necesita que Telegram le envíe los mensajes a una URL pública con HTTPS (webhook). Una PC con Docker no tiene esa URL. El relay invierte la dirección: le pregunta a Telegram si hay mensajes nuevos y se los pasa a n8n por la red interna de Docker (`http://n8n:5678/webhook/telegram`).

**Long polling:** el relay llama a `getUpdates` con `timeout=30`. Telegram deja la conexión abierta hasta 30 segundos. Si llega un mensaje, responde en el momento; si no, responde vacío y el relay vuelve a preguntar. Así los mensajes llegan al instante sin consultar a Telegram cada segundo. El parámetro `offset` le indica a Telegram qué mensajes ya se procesaron.

**Qué filtra:** solo pasa mensajes privados de personas. Ignora los posts del canal, los grupos y otros bots. Además, convierte el formato de Telegram en un JSON simple: `chat_id`, `usuario`, `tipo` (`texto`, `foto` u `otro`), `texto` y `file_id`.

Se levanta con el perfil `telegram`:

```powershell
docker compose --profile telegram up -d --build
docker compose logs -f relay
```

## Cómo se verificó

Sin Telegram real, con un servidor que simula la API de Telegram y anota lo que recibe, más n8n 1.94.1, la API y el relay corriendo juntos:

- Workflow 1: publicó los 2 cuentos de ejemplo con el botón y los marcó como publicados.
- Workflow 2: `/start prod_1` (gratis) entregó el `.md`. `/start prod_2` (pago) mandó los datos de transferencia. La foto del comprobante avisó al cliente y al admin. También se probaron una foto suelta, un sticker, `/start prod_999` y una pregunta libre, y cada caso recibió su respuesta.
- Workflow 3: validar el pago desde la API entregó el cuento pago. Pedir la entrega de un pedido sin pagar no envió nada y avisó al admin.
- El relay ignoró un post del canal.

La prueba con Telegram real, desde un celular, sigue pendiente.
