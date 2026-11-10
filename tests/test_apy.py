"""Pruebas de punta a punta de la API con IA simulada y Telegram falso.

Ejecutar:  pytest -q
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import telegram_client
from app.config import config
from app.servicios import pedidos as servicio_pedidos


@pytest.fixture()
def cliente(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", tmp_path)
    monkeypatch.setattr(config, "ia_proveedores", ["mock"])
    monkeypatch.setattr(config, "telegram_bot_username", "CuentosDemoBot")
    enviados: list[dict] = []
    monkeypatch.setattr(
        telegram_client, "enviar_documento",
        lambda chat_id, nombre, contenido, leyenda="": enviados.append({"chat_id": chat_id, "nombre": nombre}) or {},
    )
    monkeypatch.setattr(telegram_client, "enviar_mensaje", lambda chat_id, texto: {})
    monkeypatch.setattr(servicio_pedidos, "disparar_entrega", lambda pedido_id: True)
    from app.main import app

    with TestClient(app) as c:
        c.enviados = enviados
        yield c


def _publicar(cliente, precio=0) -> dict:
    p = cliente.post("/productos/generar", json={"tema": "un gato astronauta", "edad": 6, "precio": precio}).json()
    cliente.post(f"/productos/{p['id']}/revision", json={"decision": "aprobar"})
    return cliente.patch(f"/productos/{p['id']}/publicacion", json={"telegram_msg_id": 10}).json()


def test_generar_cuento_queda_pendiente_y_validado(cliente):
    r = cliente.post("/productos/generar", json={"tema": "un dragón miedoso", "edad": 5, "personaje": "Tomi"})
    assert r.status_code == 201
    p = r.json()
    assert p["estado"] == "pendiente"
    assert p["proveedor_ia"] == "mock"
    assert p["aprobable"] is True
    assert p["contenido_md"].startswith("# ")
    assert {v["regla"] for v in p["validaciones"]} >= {"titulo", "largo", "vocabulario", "promo_largo"}
    assert p["link_pedido"].endswith(f"start=prod_{p['id']}")


def test_datos_invalidos_devuelven_422(cliente):
    assert cliente.post("/productos/generar", json={"tema": "x", "edad": 20}).status_code == 422
    assert cliente.post("/pedidos", json={"producto_id": 0, "chat_id": "1"}).status_code == 422


def test_no_se_publica_sin_aprobacion(cliente):
    p = cliente.post("/productos/generar", json={"tema": "un barco de papel", "edad": 7}).json()
    r = cliente.patch(f"/productos/{p['id']}/publicacion", json={})
    assert r.status_code == 409


def test_regla_bloqueante_impide_aprobar(cliente):
    p = cliente.post("/productos/generar", json={"tema": "un barco de papel", "edad": 7}).json()
    malo = "# Título\n\nEste texto tiene la palabra sangre y es muy corto.\n\nFin\n\nchau " * 3
    editado = cliente.patch(f"/productos/{p['id']}", json={"contenido_md": malo}).json()
    assert editado["aprobable"] is False
    r = cliente.post(f"/productos/{p['id']}/revision", json={"decision": "aprobar"})
    assert r.status_code == 422
    assert "sangre" in r.json()["detalle"]


def test_pedido_gratis_se_entrega(cliente):
    prod = _publicar(cliente, precio=0)
    r = cliente.post("/pedidos", json={"producto_id": prod["id"], "chat_id": "555", "usuario": "ana"})
    assert r.status_code == 201
    pedido = r.json()
    assert pedido["puede_entregar"] is True
    entregado = cliente.post(f"/pedidos/{pedido['id']}/entregar").json()
    assert entregado["estado"] == "entregado"
    assert cliente.enviados[0]["nombre"].endswith(".md")


def test_pedido_duplicado_reutiliza_el_abierto(cliente):
    prod = _publicar(cliente, precio=1500)
    a = cliente.post("/pedidos", json={"producto_id": prod["id"], "chat_id": "9"})
    b = cliente.post("/pedidos", json={"producto_id": prod["id"], "chat_id": "9"})
    assert a.status_code == 201 and b.status_code == 200
    assert a.json()["id"] == b.json()["id"]


def test_flujo_de_pago_con_supervision_humana(cliente):
    prod = _publicar(cliente, precio=1500)
    pedido = cliente.post("/pedidos", json={"producto_id": prod["id"], "chat_id": "777"}).json()
    assert pedido["puede_entregar"] is False
    assert "alias" in pedido["instrucciones_pago"]

    assert cliente.post(f"/pedidos/{pedido['id']}/entregar").status_code == 409

    cliente.patch(f"/pedidos/{pedido['id']}/estado", json={"estado": "esperando_pago"})
    comp = cliente.post("/pedidos/comprobante", json={"chat_id": "777", "file_id": "foto123"}).json()
    assert comp["estado"] == "comprobante_recibido"

    validado = cliente.patch(f"/pedidos/{pedido['id']}/pago", json={"accion": "validar"}).json()
    assert validado["puede_entregar"] is True
    assert validado["entrega_disparada"] is True
    assert cliente.post(f"/pedidos/{pedido['id']}/entregar").json()["estado"] == "entregado"


def test_comprobante_sin_pedido_da_404(cliente):
    r = cliente.post("/pedidos/comprobante", json={"chat_id": "nadie", "file_id": "x"})
    assert r.status_code == 404


def test_consultas_por_regla_y_por_ia(cliente):
    prod = _publicar(cliente)
    deep_link = cliente.post("/consultas", json={"chat_id": "1", "texto": f"/start prod_{prod['id']}"}).json()
    assert deep_link == {**deep_link, "intencion": "pedido", "producto_id": prod["id"], "origen": "regla"}

    libre = cliente.post("/consultas", json={"chat_id": "1", "texto": "¿qué cuentos tienen para 6 años?"}).json()
    assert libre["origen"] == "ia" and libre["intencion"] == "consulta"

    inexistente = cliente.post("/consultas", json={"chat_id": "1", "texto": "/start prod_999"}).json()
    assert inexistente["intencion"] == "consulta"


def test_ia_caida_no_rompe_la_atencion(cliente, monkeypatch):
    monkeypatch.setattr(config, "ia_proveedores", ["gemini"])
    monkeypatch.setattr(config, "gemini_api_key", "")
    r = cliente.post("/consultas", json={"chat_id": "1", "texto": "hola, ¿cómo funciona?"})
    assert r.status_code == 200
    assert r.json()["proveedor_ia"] == "sin_ia"


# ------------------------------------------------- agregados en la Etapa 7
def test_salud_y_estadisticas(cliente):
    salud = cliente.get("/salud").json()
    assert salud["estado"] == "ok" and salud["proveedores_ia"] == ["mock"]
    est = cliente.get("/estadisticas").json()
    assert est["pendientes_revision"] == 0 and est["hay_pendientes"] is False


def test_los_errores_tienen_siempre_la_misma_forma(cliente):
    r = cliente.get("/productos/9999")
    assert r.status_code == 404
    assert r.json() == {"error": "NoEncontrado", "detalle": "No existe el producto 9999"}


def test_descargar_el_archivo_del_cuento(cliente):
    p = cliente.post("/productos/generar", json={"tema": "un dragón miedoso", "edad": 5}).json()
    r = cliente.get(f"/productos/{p['id']}/archivo")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/markdown")
    assert p["archivo"] in r.headers["content-disposition"]
    assert r.text == p["contenido_md"]


def test_cargar_ejemplos_no_duplica(cliente, monkeypatch, capsys):
    from scripts import cargar_ejemplos

    monkeypatch.setattr("sys.argv", ["cargar_ejemplos"])
    cargar_ejemplos.main()
    cargar_ejemplos.main()                      # la segunda vez no tiene que duplicar
    productos = cliente.get("/productos").json()
    assert len(productos) == 2
    assert {p["estado"] for p in productos} == {"aprobado"}
    assert all(p["aprobable"] for p in productos)
    assert sorted(p["precio"] for p in productos) == [0, 1500]
    assert "Ya existe" in capsys.readouterr().out