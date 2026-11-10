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
| 10/11/2026 | Pablo (Scuuz) | Claude | Prueba de generación con Gemini real: tortuga, 7 años | La promo inventó un personaje ("Bruno", cuando la protagonista era Clementina) y salió cortada ("Pedilo toc"), y aun así el cuento era aprobable. Ver "Dificultades y correcciones" |
| 10/11/2026 | Pablo (Scuuz) | Claude | Corregir la promo | Se pasa el cuento completo al prompt de la promo con la instrucción de no inventar; se unen todas las partes de la respuesta de Gemini; nueva regla bloqueante `promo_completa` con su test |
| 10/11/2026 | Pablo (Scuuz) | Claude | Quitar Ollama del código y blindar Groq | Se eliminó el proveedor Ollama de `ia.py`, `config.py` y `.env.example`; el modelo por defecto pasa a `gemini-flash-lite-latest`; si Groq responde sin texto se pasa al siguiente proveedor en lugar de fallar (test nuevo) |

## Límites del nivel gratuito (consultados el 10/11/2026)

| Proveedor | Modelo | Pedidos/min | Pedidos/día | Tokens/min | Tokens/día |
| --- | --- | --- | --- | --- | --- |
| Gemini | Flash (3 / 3.6 / 3.8, 2.5) | 5 | 20 | 250K | — |
| Gemini | Flash Lite (3.1 / 3.5) | 15 | 500 | 250K | — |
| Gemini | Pro (2.5 / 3.1) | 0 | 0 | 0 | — |
| Groq | openai/gpt-oss-120b | 30 | 1.000 | 8K | 200K |

**Decisión:** se usa Gemini Flash Lite como principal en lugar de Flash. Flash permite solo
20 pedidos por día, y cada cuento consume 2 o 3 (cuento, reintento y promoción), lo que no
alcanza para pruebas y demo. Flash Lite permite 500 por día. Los modelos Pro no están
disponibles en el nivel gratuito (límite 0). Groq queda como respaldo con 1.000 pedidos por
día; su límite más ajustado son los 8K tokens por minuto, que se pueden agotar con varios
cuentos largos seguidos.

## Decisiones técnicas principales

El relay de long polling se agregó porque el disparador de Telegram en n8n requiere una URL pública. La lógica de decisión que n8n necesita (por ejemplo, si un pedido puede entregarse) se calcula en Python y se expone como campos booleanos, para que los workflows sean simples y la regla de cobro esté en un solo lugar. El envío del archivo `.md` se hace desde Python porque subir archivos multipart desde n8n era más frágil. Las reglas de validación se aplican siempre después de la IA, y la aprobación humana es obligatoria antes de publicar.

## Dificultades y correcciones

### La promoción inventaba personajes y salía cortada (10/11/2026)

**Qué pasó.** Al generar un cuento con `{"tema": "una tortuga que quería ganar una carrera", "edad": 7, "valores": "la paciencia"}`, el cuento era correcto (protagonista Clementina, 437 palabras, todas las reglas en verde), pero la promoción hablaba de un tal "Bruno" que no existía en el cuento y terminaba a mitad de palabra: "…Pedilo toc". Aun así el producto salió `aprobable: true`.

**Cómo se detectó.** Leyendo la respuesta de `POST /productos/generar` durante las pruebas con Gemini real: las reglas daban todo bien, pero al comparar la promo con el cuento no coincidían.

**Causas.**

| Problema | Causa | Archivo |
| --- | --- | --- |
| Inventaba personajes | La promo se pedía sin enviar el cuento: la IA solo recibía título, edad y tema | `app/servicios/productos.py` |
| Salía cortada | Gemini puede devolver el texto dividido en varias partes y el código leía solo la primera (`parts[0]`) | `app/ia.py` |
| Se podía aprobar igual | Ninguna regla verificaba que la promo estuviera completa | `app/validaciones.py` |

**Corrección.** El prompt de la promo ahora incluye el cuento completo y pide usar solo personajes y hechos que aparecen en él, sin contar el final. El cliente de Gemini une todas las partes de la respuesta. Se agregó la regla bloqueante `promo_completa` (la promo no puede terminar en letra o número) con su prueba automática.

**Resultado.** Repitiendo la misma prueba, la promo habló de la protagonista real (Donata) y de personajes del cuento, terminó completa y la regla nueva dio `ok`. Se confirmó con un segundo cuento (robot Bolt, 10 años).

**Aprendizaje.** Que todas las reglas den bien no garantiza que el texto sea correcto: la IA puede inventar datos que ninguna regla automática detecta. Por eso el sistema exige aprobación humana antes de publicar.

### Errores que las reglas no detectan

En las pruebas aparecieron errores que solo se ven leyendo el cuento: faltas de ortografía ("enroles", "habìa", "luceces"), incoherencias (un personaje que "se despierta" sin haberse dormido), escenas que quedan sueltas y una historia que repite la fábula de "La liebre y la tortuga" con otros nombres. Son casos para la revisión humana del panel; como mejora del prompt queda pedir historias originales y revisar la ortografía.

## Pruebas con IA real (10/11/2026)

Proveedor: Gemini Flash Lite. Pedido = tema, edad y personaje.

### Antes de corregir la promo

| # | Pedido | Proveedor | Reglas | Aprobable | ¿Promo coherente? | ¿Promo completa? | Observaciones del cuento |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | Nube, 4 años, Nubi | gemini | todas ok | sí | no revisado | no revisado | |
| 2 | Dragón, 6 años, Tomi | gemini | todas ok | sí | no revisado | no revisado | |
| 3 | Tortuga, 7 años | gemini | todas ok | sí | NO: inventó a "Bruno" (la tortuga es Clementina) | NO: termina en "Pedilo toc" | "enroles" en vez de "enrolles"; "habìa" con acento mal |

### Después de corregir la promo

| # | Pedido | Proveedor | Reglas | Aprobable | ¿Promo coherente? | ¿Promo completa? | Observaciones del cuento |
| --- | --- | --- | --- | --- | --- | --- | --- |
| 4 | Tortuga, 7 años | gemini | todas ok, incluida promo_completa | sí | SÍ: Donata, Crispín, conejo y ardilla están en el cuento | SÍ: termina en emoji | "El conejo y la ardilla se despertaron", pero la ardilla nunca se durmió; repite "La liebre y la tortuga"; título igual al de la prueba 3 |
| 5 | Robot, 10 años, Bolt | gemini | todas ok, incluida promo_completa | sí | SÍ: Bolt, Julián, Sofía y Lucas están en el cuento | SÍ: termina en punto | "luceces" en vez de "luces"; "pelota risueña" no tiene sentido; la escena de la pelota bajo el gomero queda suelta |

### Mejoras pendientes para los prompts

- Pedir que la historia sea original y no una versión de fábulas conocidas.
- Evitar títulos repetidos.
- Pedir revisión de ortografía y que no queden escenas sin cerrar.
