"""Relay: pasa los mensajes privados del bot de Telegram a n8n.

Por qué existe: el nodo "Telegram Trigger" de n8n necesita que Telegram le
mande los mensajes a una URL pública con HTTPS (webhook). Con Docker en una
PC no hay URL pública. El relay hace lo contrario: le PREGUNTA a Telegram si
hay mensajes nuevos (long polling con getUpdates) y se los pasa a n8n por la
red interna de Docker.

Long polling: el pedido a getUpdates queda abierto hasta 30 segundos. Si llega
un mensaje en ese tiempo, Telegram responde enseguida; si no, responde vacío y
se vuelve a preguntar. Así los mensajes llegan al instante sin consultar
todo el tiempo.

Qué manda a n8n (POST {N8N_URL}/webhook/telegram), un JSON simple:
    {"update_id", "chat_id", "usuario", "tipo": "texto" | "foto" | "otro", "texto", "file_id"}

Ejecutar:
    docker compose --profile telegram up -d --build     (en Docker)
    python -m relay.main                                 (en local, con N8N_URL=http://localhost:5678)
"""
from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

try:  # en local leemos el .env; en Docker ya vienen las variables
    from dotenv import load_dotenv

    load_dotenv()
except ImportError:  # pragma: no cover
    pass

log = logging.getLogger("relay")

ESPERA_LARGA = 30  # segundos que Telegram mantiene abierto getUpdates
PAUSA_ERROR = 5  # segundos de espera si Telegram o n8n fallan


def normalizar(update: dict[str, Any]) -> dict[str, Any] | None:
    """Convierte un update de Telegram en el JSON que espera el workflow de Atención.

    Devuelve None para lo que no es un mensaje privado al bot (posts del canal,
    mensajes editados, grupos, otros bots), así n8n no recibe ruido.
    """
    mensaje = update.get("message")
    if not mensaje:
        return None
    chat = mensaje.get("chat", {})
    remitente = mensaje.get("from", {})
    if chat.get("type") != "private" or remitente.get("is_bot"):
        return None

    usuario = remitente.get("username") or " ".join(
        p for p in (remitente.get("first_name"), remitente.get("last_name")) if p
    )
    datos: dict[str, Any] = {
        "update_id": update.get("update_id"),
        "chat_id": str(chat["id"]),
        "usuario": usuario or None,
        "tipo": "otro",
        "texto": None,
        "file_id": None,
    }
    if mensaje.get("text"):
        datos["tipo"], datos["texto"] = "texto", mensaje["text"].strip()
    elif mensaje.get("photo"):
        # Telegram manda la misma foto en varios tamaños: la última es la más grande
        datos["tipo"], datos["file_id"] = "foto", mensaje["photo"][-1]["file_id"]
        datos["texto"] = mensaje.get("caption")
    elif (mensaje.get("document") or {}).get("mime_type", "").startswith("image/"):
        # comprobante mandado como archivo en vez de como foto
        datos["tipo"], datos["file_id"] = "foto", mensaje["document"]["file_id"]
    return datos


class Relay:
    def __init__(
        self, token: str, n8n_url: str, cliente: httpx.Client | None = None,
        telegram_url: str = "https://api.telegram.org",
    ) -> None:
        self.api = f"{telegram_url.rstrip('/')}/bot{token}"
        self.destino = f"{n8n_url.rstrip('/')}/webhook/telegram"
        self.http = cliente or httpx.Client(timeout=ESPERA_LARGA + 10)
        self.offset: int | None = None

    def preparar(self) -> None:
        """Si el bot tenía un webhook configurado, getUpdates no funciona: lo borramos."""
        r = self.http.post(f"{self.api}/deleteWebhook", json={"drop_pending_updates": False})
        datos = r.json()
        if not datos.get("ok"):
            raise SystemExit(f"Telegram rechazó el token: {datos.get('description')}")
        yo = self.http.get(f"{self.api}/getMe").json().get("result", {})
        log.info("Conectado como @%s. Reenviando mensajes a %s", yo.get("username"), self.destino)

    def pedir_updates(self) -> list[dict[str, Any]]:
        params: dict[str, Any] = {"timeout": ESPERA_LARGA, "allowed_updates": '["message"]'}
        if self.offset is not None:
            params["offset"] = self.offset
        r = self.http.get(f"{self.api}/getUpdates", params=params)
        datos = r.json()
        if not datos.get("ok"):
            raise httpx.HTTPError(f"getUpdates: {datos.get('description')}")
        return datos["result"]

    def reenviar(self, datos: dict[str, Any]) -> bool:
        for intento in range(3):  # n8n puede estar arrancando: reintentamos un poco
            try:
                r = self.http.post(self.destino, json=datos, timeout=15)
                if r.status_code < 400:
                    return True
                log.warning("n8n respondió %s: %s", r.status_code, r.text[:200])
                if r.status_code == 404:
                    log.warning("¿Está activo el workflow 'Atención'? El webhook /telegram no existe.")
                    return False
            except httpx.HTTPError as exc:
                log.warning("No se pudo contactar a n8n (intento %s): %s", intento + 1, exc)
            time.sleep(PAUSA_ERROR)
        return False

    def una_vuelta(self) -> int:
        """Pide updates una vez y los reenvía. Devuelve cuántos se reenviaron."""
        enviados = 0
        for update in self.pedir_updates():
            # Avanzamos el offset aunque n8n falle, para no quedar trabados en un mensaje
            self.offset = update["update_id"] + 1
            datos = normalizar(update)
            if datos is None:
                continue
            log.info("Mensaje de %s (%s): %s", datos["usuario"], datos["tipo"], (datos["texto"] or "")[:60])
            if self.reenviar(datos):
                enviados += 1
        return enviados

    def correr(self) -> None:
        self.preparar()
        while True:
            try:
                self.una_vuelta()
            except (httpx.HTTPError, ValueError) as exc:
                log.warning("Error hablando con Telegram: %s. Reintento en %s s", exc, PAUSA_ERROR)
                time.sleep(PAUSA_ERROR)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s relay: %(message)s")
    logging.getLogger("httpx").setLevel(logging.WARNING)  # no mostrar URLs (llevan el token)
    token = os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        raise SystemExit("Falta TELEGRAM_BOT_TOKEN en el .env")
    Relay(
        token,
        os.getenv("N8N_URL", "http://localhost:5678"),
        telegram_url=os.getenv("TELEGRAM_API_URL", "https://api.telegram.org"),
    ).correr()


if __name__ == "__main__":
    main()
