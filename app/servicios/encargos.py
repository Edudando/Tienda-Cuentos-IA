"""Encargos: un cliente le pide al bot un cuento nuevo.

Flujo:
1. El bot detecta la intención "encargo" con el tema y la edad (consultas.py).
2. Se reserva el encargo y el cliente recibe la confirmación al instante.
3. En segundo plano la IA escribe el cuento con la misma función que usa el
   panel, y queda PENDIENTE en Revisión, con el nombre de quien lo pidió.
4. Cuando una persona lo aprueba o lo rechaza, y cuando n8n lo publica, el
   cliente recibe un aviso (productos.py).

Así un encargo nunca llega al cliente sin pasar por la revisión humana.
"""
from __future__ import annotations

import logging
import threading
from typing import Any

from pydantic import ValidationError

from app import db
from app.errores import ErrorDominio
from app.modelos import GenerarCuento
from app.servicios import productos
from app.servicios.avisos import avisar_cliente, es_chat_de_telegram

log = logging.getLogger("encargos")

# Un cliente puede tener un solo encargo esperando revisión: protege la cuota de IA.
MAX_PENDIENTES_POR_CLIENTE = 1

# Encargos que la IA está escribiendo ahora (todavía no están en la base)
_en_proceso: set[str] = set()
_candado = threading.Lock()


def validar_datos(tema: Any, edad: Any) -> GenerarCuento | None:
    """Mismas reglas que el formulario del panel (tema de 3 a 80 caracteres, edad de 3 a 12)."""
    try:
        return GenerarCuento(tema=str(tema or "").strip()[:80], edad=edad)
    except (ValidationError, TypeError, ValueError):
        return None


def reservar(chat_id: str) -> bool:
    """Marca que el cliente tiene un encargo en curso. False si ya tenía uno."""
    if not es_chat_de_telegram(chat_id):
        return True  # pruebas desde el panel: sin límite
    with _candado:
        if chat_id in _en_proceso or db.contar_encargos_pendientes(chat_id) >= MAX_PENDIENTES_POR_CLIENTE:
            return False
        _en_proceso.add(chat_id)
        return True


def liberar(chat_id: str) -> None:
    with _candado:
        _en_proceso.discard(chat_id)


def procesar(chat_id: str, usuario: str | None, tema: str, edad: int) -> dict[str, Any] | None:
    """Escribe el cuento encargado. Corre en segundo plano después de responder al cliente."""
    try:
        producto = productos.generar(
            GenerarCuento(tema=tema, edad=edad),
            solicitante_chat_id=chat_id,
            solicitante_usuario=usuario,
        )
        log.info("Encargo de %s listo: cuento N° %s pendiente de revisión", usuario or chat_id, producto["id"])
        return producto
    except (ErrorDominio, ValidationError) as exc:
        log.warning("No se pudo generar el encargo de %s: %s", usuario or chat_id, exc)
        avisar_cliente(
            chat_id,
            "Uy, no pudimos escribir tu cuento en este momento. Probá de nuevo en un rato, por favor.",
        )
        return None
    finally:
        liberar(chat_id)
