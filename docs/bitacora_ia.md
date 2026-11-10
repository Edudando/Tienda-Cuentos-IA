# Bitácora de uso de IA en el desarrollo

Esta bitácora registra cómo el equipo usó herramientas de IA para desarrollar el proyecto. Es distinta de la IA que forma parte del sistema (ver README, sección Inteligencia artificial). Conviene completarla a medida que avanza el trabajo, con fecha y autor de cada entrada.

## Herramientas utilizadas

| Herramienta | Uso principal |
| --- | --- |
| Claude (claude.ai) | Análisis de la consigna, elección de proveedores de IA, arquitectura, primera versión del código, workflows y documentación |
| *(completar)* | *(por ejemplo: Gemini, ChatGPT, Copilot en VS Code)* |

## Registro

| Fecha | Integrante | Herramienta | Pedido / tarea | Decisión o corrección |
| --- | --- | --- | --- | --- |
| 06/11/2026 | *(completar)* | Claude | Evaluar la idea de tienda de cuentos frente a la consigna y elegir IA gratuita | Se eligió Gemini Flash con fallback a Groq y Ollama; los modelos Pro ya no están en el nivel gratuito |
| 06/11/2026 | *(completar)* | Claude | Analizar riesgos de Instagram y WhatsApp | Se reemplazó WhatsApp por Telegram (bot y canal) para evitar las restricciones de la API de Meta y los costos |
| 06/11/2026 | *(completar)* | Claude | Formato del producto | Se pasó de PDF a Markdown: elimina la generación de PDF; se acepta que algunos celulares lo muestran como texto plano |
| 06/11/2026 | *(completar)* | Claude | Generar la estructura del repo, API, panel, relay, workflows y Docker | Se revisó que cada endpoint tenga uso real en el proceso y que cada workflow tenga una condición |
| *(completar)* | | | Pruebas con Telegram real | *(anotar qué falló y cómo se corrigió)* |
| *(completar)* | | | Ajuste de prompts | *(anotar ejemplos de salidas malas de la IA y el cambio de prompt)* |
| 10/11/2026 | Pablo (Scuuz) | Claude | Preparar el entorno y correr la API con IA simulada | Entorno virtual con Python 3.12.4 (el grupo reportó problemas con 3.13); tests en verde con IA_PROVEEDORES=mock |
| 10/11/2026 | Pablo (Scuuz) | Claude | Evaluar Ollama como respaldo local | Se descartó: las PCs del grupo no tienen potencia para correr un modelo local. El fallback queda Gemini → Groq |
| 10/11/2026 | Pablo (Scuuz) | Claude | Consultar límites gratuitos de Gemini y Groq | Gemini Flash permite 20 pedidos/día: se cambia a Flash Lite (500/día). Pro no está en el nivel gratuito |

## Límites del nivel gratuito (consultados el 10/11/2026)

| Proveedor | Modelo 			| Pedidos/min | Pedidos/día | Tokens/min | Tokens/día |
|-----------| ------------------------- | ----------- | ----------- | -----------| ---------- |
|   Gemini  | Flash (3 / 3.6 / 3.8, 2.5)|      5      |     20      |    250K    |     —      |
|   Gemini  | Flash Lite (3.1 / 3.5)    |      15     |     500     |    250K    |     —      |
|   Gemini  | Pro (2.5 / 3.1)           |      0      |     0       |    0       |     —      |
|    Groq   | openai/gpt-oss-120b       |      30     |     1.000   |    8K      |    200K    |

**Decisión:** se usa Gemini Flash Lite como principal en lugar de Flash. Flash permite solo
20 pedidos por día, y cada cuento consume 2 o 3 (cuento, reintento y promoción), lo que no
alcanza para pruebas y demo. Flash Lite permite 500 por día. Los modelos Pro no están
disponibles en el nivel gratuito (límite 0). Groq queda como respaldo con 1.000 pedidos por
día; su límite más ajustado son los 8K tokens por minuto, que se pueden agotar con varios
cuentos largos seguidos.

## Decisiones técnicas principales

El relay de long polling se agregó porque el disparador de Telegram en n8n requiere una URL pública. La lógica de decisión que n8n necesita (por ejemplo, si un pedido puede entregarse) se calcula en Python y se expone como campos booleanos, para que los workflows sean simples y la regla de cobro esté en un solo lugar. El envío del archivo `.md` se hace desde Python porque subir archivos multipart desde n8n era más frágil. Las reglas de validación se aplican siempre después de la IA, y la aprobación humana es obligatoria antes de publicar.

## Dificultades y correcciones

*(Completar durante el desarrollo: errores que propuso la IA, cómo los detectaron y qué cambiaron.)*
