"""Pruebas de los encargos: un cliente pide por el bot un cuento nuevo.

Ejecutar:  pytest -q
La IA es el proveedor "mock" y Telegram se reemplaza por una función falsa
que anota los mensajes que se le pidió enviar.
"""
import sqlite3

import pytest

from app import db, telegram_client
from app.config import config
from app.errores import ServicioNoDisponible
from app.servicios import consultas, encargos, productos

CLIENTE = "123456"  # chat_id de Telegram (siempre numérico)
PEDIDO = "quiero que me escriban un cuento sobre un dinosaurio que aprende a nadar, para 5 años"


@pytest.fixture()
def tienda(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", tmp_path)
    monkeypatch.setattr(config, "ia_proveedores", ["mock"])
    monkeypatch.setattr(config, "telegram_bot_username", "CuentosDemoBot")
    db.inicializar()
    encargos._en_proceso.clear()
    mensajes: list[tuple[str, str]] = []
    monkeypatch.setattr(telegram_client, "enviar_mensaje", lambda chat_id, texto: mensajes.append((chat_id, texto)) or {})
    return mensajes


def _encargar(chat_id=CLIENTE, usuario="ana", texto=PEDIDO):
    """Lo mismo que hace POST /consultas: atender y, si es encargo, generar."""
    r = consultas.atender(chat_id, usuario, texto)
    producto = None
    if r.get("encargo"):
        producto = encargos.procesar(chat_id, usuario, r["encargo"]["tema"], r["encargo"]["edad"])
    return r, producto


# ------------------------------------------------------------ detección
def test_el_bot_detecta_un_encargo_con_tema_y_edad(tienda):
    r = consultas.atender(CLIENTE, "ana", PEDIDO)
    assert r["intencion"] == "encargo"
    assert r["encargo"] == {"tema": "un dinosaurio que aprende a nadar", "edad": 5}
    assert "revisa una persona" in r["respuesta"]
    assert db.listar_consultas()[0]["intencion"] == "encargo"


def test_si_falta_la_edad_el_bot_la_pide(tienda):
    r = consultas.atender(CLIENTE, "ana", "escribime un cuento sobre piratas")
    assert r["intencion"] == "consulta"
    assert "encargo" not in r
    assert "edad" in r["respuesta"]


def test_edad_fuera_de_rango_no_se_acepta(tienda):
    r = consultas.atender(CLIENTE, "ana", "escribime un cuento sobre la luna para 30 años")
    assert r["intencion"] == "consulta"
    assert "encargo" not in r


def test_la_propuesta_de_la_ia_se_valida():
    datos = {"intencion": "encargo", "tema": "x", "edad": 5, "respuesta": "ok"}
    assert consultas._validar_propuesta_ia(datos, [])["intencion"] == "consulta"  # tema muy corto
    datos = {"intencion": "encargo", "tema": "un gato", "edad": "cinco", "respuesta": "ok"}
    assert consultas._validar_propuesta_ia(datos, [])["intencion"] == "consulta"  # edad no numérica


# -------------------------------------------------- queda en la bandeja
def test_el_encargo_queda_pendiente_con_el_solicitante(tienda):
    _, producto = _encargar()
    assert producto["estado"] == "pendiente"
    assert producto["tema"] == "un dinosaurio que aprende a nadar"
    assert producto["edad"] == 5
    assert producto["solicitante_chat_id"] == CLIENTE
    assert producto["solicitante_usuario"] == "ana"
    assert productos.listar("pendiente")[0]["id"] == producto["id"]


def test_un_solo_encargo_pendiente_por_cliente(tienda):
    _encargar()
    r, producto = _encargar()
    assert producto is None
    assert r["intencion"] == "consulta"
    assert "Ya tenés un cuento encargado" in r["respuesta"]
    assert len(productos.listar("pendiente")) == 1


def test_otro_cliente_si_puede_encargar(tienda):
    _encargar()
    _, producto = _encargar(chat_id="999", usuario="beto")
    assert producto["solicitante_usuario"] == "beto"


def test_despues_de_revisado_puede_encargar_otro(tienda):
    _, primero = _encargar()
    productos.revisar(primero["id"], "aprobar", None)
    _, segundo = _encargar()
    assert segundo is not None


def test_desde_el_panel_no_hay_limite_ni_avisos(tienda):
    _encargar(chat_id="panel", usuario="prueba-panel")
    _, segundo = _encargar(chat_id="panel", usuario="prueba-panel")
    productos.revisar(segundo["id"], "aprobar", None)
    assert segundo is not None
    assert tienda == []  # "panel" no es un chat de Telegram


def test_si_la_ia_falla_se_avisa_y_se_libera(tienda, monkeypatch):
    def falla(*a, **k):
        raise ServicioNoDisponible("sin IA")

    monkeypatch.setattr(productos, "generar", falla)
    r, producto = _encargar()
    assert r["intencion"] == "encargo" and producto is None
    assert "no pudimos escribir tu cuento" in tienda[-1][1]
    assert CLIENTE not in encargos._en_proceso


# ------------------------------------------------------------- avisos
def test_al_aprobar_se_avisa_al_cliente(tienda):
    _, producto = _encargar()
    productos.revisar(producto["id"], "aprobar", None)
    chat_id, texto = tienda[-1]
    assert chat_id == CLIENTE
    assert "aprobado" in texto and producto["titulo"] in texto


def test_al_rechazar_se_avisa_al_cliente(tienda):
    _, producto = _encargar()
    productos.revisar(producto["id"], "rechazar", "no es apto")
    chat_id, texto = tienda[-1]
    assert chat_id == CLIENTE
    assert "no pasó nuestra revisión" in texto
    assert "no es apto" not in texto  # la nota interna no se le muestra al cliente


def test_al_publicar_recibe_el_link_para_pedirlo(tienda):
    _, producto = _encargar()
    productos.revisar(producto["id"], "aprobar", None)
    productos.marcar_publicado(producto["id"], telegram_msg_id=7)
    chat_id, texto = tienda[-1]
    assert chat_id == CLIENTE
    assert f"https://t.me/CuentosDemoBot?start=prod_{producto['id']}" in texto


def test_un_cuento_del_panel_no_avisa_a_nadie(tienda):
    from app.modelos import GenerarCuento

    p = productos.generar(GenerarCuento(tema="un barco de papel", edad=6))
    productos.revisar(p["id"], "aprobar", None)
    productos.marcar_publicado(p["id"], telegram_msg_id=1)
    assert tienda == []


def test_si_telegram_falla_la_aprobacion_sigue_igual(tienda, monkeypatch):
    def falla(chat_id, texto):
        raise ServicioNoDisponible("Telegram caído")

    _, producto = _encargar()
    monkeypatch.setattr(telegram_client, "enviar_mensaje", falla)
    aprobado = productos.revisar(producto["id"], "aprobar", None)
    assert aprobado["estado"] == "aprobado"


# ---------------------------------------------------- base de datos vieja
def test_una_base_vieja_recibe_las_columnas_nuevas(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "data_dir", tmp_path)
    con = sqlite3.connect(tmp_path / "tienda.db")
    con.execute("CREATE TABLE productos (id INTEGER PRIMARY KEY, titulo TEXT)")  # sin las columnas nuevas
    con.close()
    db.inicializar()
    con = sqlite3.connect(tmp_path / "tienda.db")
    columnas = {f[1] for f in con.execute("PRAGMA table_info(productos)")}
    con.close()
    assert {"solicitante_chat_id", "solicitante_usuario"} <= columnas
    db.inicializar()  # correrlo dos veces no falla


# ------------------------------------------------------- de punta a punta
def test_api_encargo_completo(tienda):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as cliente:
        r = cliente.post("/consultas", json={"chat_id": CLIENTE, "usuario": "ana", "texto": PEDIDO})
        assert r.status_code == 200
        assert r.json()["intencion"] == "encargo"
        # TestClient ejecuta la tarea en segundo plano antes de devolver la respuesta
        pendientes = cliente.get("/productos", params={"estado": "pendiente"}).json()
        assert len(pendientes) == 1
        assert pendientes[0]["solicitante_usuario"] == "ana"

        cliente.post(f"/productos/{pendientes[0]['id']}/revision", json={"decision": "aprobar"})
        assert tienda[-1][0] == CLIENTE and "aprobado" in tienda[-1][1]
