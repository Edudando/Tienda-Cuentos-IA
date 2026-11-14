"""Pruebas del relay Telegram -> n8n, con Telegram y n8n simulados (httpx.MockTransport)."""
from __future__ import annotations

import json

import httpx

from relay import main as relay


def _mensaje(update_id: int, **campos) -> dict:
    return {
        "update_id": update_id,
        "message": {
            "message_id": update_id,
            "chat": {"id": 111, "type": "private"},
            "from": {"id": 111, "is_bot": False, "username": "ana"},
            **campos,
        },
    }


# ------------------------------------------------------------------ normalizar
def test_texto():
    d = relay.normalizar(_mensaje(1, text=" /start prod_1 "))
    assert d == {"update_id": 1, "chat_id": "111", "usuario": "ana", "tipo": "texto",
                 "texto": "/start prod_1", "file_id": None}


def test_foto_toma_la_de_mayor_tamano():
    d = relay.normalizar(_mensaje(2, photo=[{"file_id": "chica"}, {"file_id": "grande"}], caption="pago"))
    assert d["tipo"] == "foto" and d["file_id"] == "grande" and d["texto"] == "pago"


def test_comprobante_mandado_como_archivo_de_imagen():
    d = relay.normalizar(_mensaje(3, document={"file_id": "doc1", "mime_type": "image/png"}))
    assert d["tipo"] == "foto" and d["file_id"] == "doc1"


def test_sticker_es_otro():
    assert relay.normalizar(_mensaje(4, sticker={"file_id": "s"}))["tipo"] == "otro"


def test_sin_username_usa_el_nombre():
    u = _mensaje(5, text="hola")
    u["message"]["from"] = {"id": 111, "is_bot": False, "first_name": "Ana", "last_name": "Paz"}
    assert relay.normalizar(u)["usuario"] == "Ana Paz"


def test_ignora_canal_grupos_y_bots():
    assert relay.normalizar({"update_id": 6, "channel_post": {"text": "x"}}) is None
    grupo = _mensaje(7, text="hola")
    grupo["message"]["chat"]["type"] = "group"
    assert relay.normalizar(grupo) is None
    bot = _mensaje(8, text="hola")
    bot["message"]["from"]["is_bot"] = True
    assert relay.normalizar(bot) is None


# ------------------------------------------------------------------ una vuelta
def _relay_con(updates: list[dict], respuesta_n8n: int = 200):
    recibidos, offsets = [], []

    def manejar(req: httpx.Request) -> httpx.Response:
        if req.url.path.endswith("/getUpdates"):
            offsets.append(req.url.params.get("offset"))
            return httpx.Response(200, json={"ok": True, "result": updates})
        if req.url.path == "/webhook/telegram":
            recibidos.append(json.loads(req.content))
            return httpx.Response(respuesta_n8n, json={"message": "Workflow was started"})
        return httpx.Response(404)

    cliente = httpx.Client(transport=httpx.MockTransport(manejar))
    return relay.Relay("TOKEN", "http://n8n:5678", cliente=cliente), recibidos, offsets


def test_una_vuelta_reenvia_a_n8n_y_avanza_el_offset():
    r, recibidos, offsets = _relay_con([_mensaje(10, text="hola"), {"update_id": 11, "channel_post": {}}])
    assert r.una_vuelta() == 1
    assert [d["texto"] for d in recibidos] == ["hola"]
    assert r.offset == 12          # avanza también por el post del canal ignorado
    assert offsets == [None]


def test_si_n8n_no_tiene_el_webhook_no_se_traba(monkeypatch):
    monkeypatch.setattr(relay, "PAUSA_ERROR", 0)
    r, recibidos, _ = _relay_con([_mensaje(20, text="hola")], respuesta_n8n=404)
    assert r.una_vuelta() == 0
    assert len(recibidos) == 1     # con 404 no reintenta: el workflow no está activo
    assert r.offset == 21          # y sigue con el próximo mensaje
