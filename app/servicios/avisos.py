"""Avisos al cliente por Telegram sobre el estado de su encargo.

Un aviso que no se puede mandar (Telegram sin configurar, chat inexistente)
NUNCA debe frenar la operación principal: aprobar, rechazar o publicar un
cuento sigue funcionando y el problema solo queda en el log.
"""
from __future__ import annotations

import logging
import re

from app import telegram_client
from app.errores import ServicioNoDisponible

log = logging.getLogger("avisos")


def es_chat_de_telegram(chat_id: str | None) -> bool:
    """Los chat_id de Telegram son números. El panel usa chat_id='panel'."""
    return bool(chat_id) and re.fullmatch(r"-?\d+", str(chat_id)) is not None


def avisar_cliente(chat_id: str | None, texto: str) -> bool:
    """Devuelve True si el mensaje se envió."""
    if not es_chat_de_telegram(chat_id):
        log.info("Aviso no enviado: el chat %r no es de Telegram (prueba desde el panel)", chat_id)
        return False
    try:
        telegram_client.enviar_mensaje(str(chat_id), texto)
        return True
    except ServicioNoDisponible as exc:
        log.warning("No se pudo avisar al cliente %s: %s", chat_id, exc.mensaje)
        return False
