"""Envíos a Telegram que necesitan Python.

n8n manda los mensajes de texto con nodos HTTP Request. Desde Python solo
enviamos el archivo del cuento (multipart) y descargamos comprobantes.
"""
from __future__ import annotations

import httpx

from app.config import config
from app.errores import ServicioNoDisponible

TIMEOUT = 30


def _url(metodo: str) -> str:
    if not config.telegram_token:
        raise ServicioNoDisponible("Telegram no está configurado (falta TELEGRAM_BOT_TOKEN)")
    return f"https://api.telegram.org/bot{config.telegram_token}/{metodo}"


def _verificar(r: httpx.Response) -> dict:
    datos = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
    if r.status_code != 200 or not datos.get("ok"):
        raise ServicioNoDisponible(f"Telegram rechazó el envío: {datos.get('description', r.text[:200])}")
    return datos["result"]


def enviar_mensaje(chat_id: str, texto: str) -> dict:
    try:
        r = httpx.post(_url("sendMessage"), json={"chat_id": chat_id, "text": texto}, timeout=TIMEOUT)
    except httpx.HTTPError as exc:
        raise ServicioNoDisponible(f"No se pudo contactar a Telegram: {exc}") from exc
    return _verificar(r)


def enviar_documento(chat_id: str, nombre: str, contenido: bytes, leyenda: str = "") -> dict:
    try:
        r = httpx.post(
            _url("sendDocument"),
            data={"chat_id": chat_id, "caption": leyenda[:1024]},
            files={"document": (nombre, contenido, "text/markdown")},
            timeout=TIMEOUT,
        )
    except httpx.HTTPError as exc:
        raise ServicioNoDisponible(f"No se pudo contactar a Telegram: {exc}") from exc
    return _verificar(r)


def descargar_archivo(file_id: str) -> bytes:
    try:
        info = _verificar(httpx.get(_url("getFile"), params={"file_id": file_id}, timeout=TIMEOUT))
        url = f"https://api.telegram.org/file/bot{config.telegram_token}/{info['file_path']}"
        r = httpx.get(url, timeout=TIMEOUT)
        r.raise_for_status()
        return r.content
    except httpx.HTTPError as exc:
        raise ServicioNoDisponible(f"No se pudo descargar el archivo de Telegram: {exc}") from exc