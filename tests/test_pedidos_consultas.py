"""Pruebas de la Etapa 6: pedidos, pagos y atención de mensajes.

Ejecutar:  pytest -q
Telegram y n8n se reemplazan por funciones falsas que anotan lo que se les
pidió; la IA es el proveedor "mock".
"""
import json

import httpx
import pytest

from app import db, ia, telegram_client
from app.config import config
from app.errores import EstadoInvalido, NoEncontrado, ServicioNoDisponible
from app.modelos import GenerarCuento
from app.servicios import consultas, pedidos, productos


@pytest.fixture()
def tienda(tmp_path, monkeypatch):
    """Base vacía, IA simulada, Telegram y n8n falsos."""
    monkeypatch.setattr(config, "data_dir", tmp_path)
    monkeypatch.setattr(config, "ia_proveedores", ["mock"])
    monkeypatch.setattr(config, "telegram_token", "")
    monkeypatch.setattr(config, "alias_transferencia", "cuentos.demo")
    db.inicializar()

    registro = {"documentos": [], "mensajes": [], "entregas": []}
    monkeypatch.setattr(
        telegram_client, "enviar_documento",
        lambda chat_id, nombre, contenido, leyenda="": registro["documentos"].append((chat_id, nombre)) or {},
    )
    monkeypatch.setattr(
        telegram_client, "enviar_mensaje",
        lambda chat_id, texto: registro["mensajes"].append((chat_id, texto)) or {},
    )
    monkeypatch.setattr(pedidos, "disparar_entrega", lambda pedido_id: registro["entregas"].append(pedido_id) or True)
    return registro


def _publicado(precio=0, tema="un gato astronauta"):
    p = productos.generar(GenerarCuento(tema=tema, edad=6, precio=precio))
    productos.revisar(p["id"], "aprobar", None)
    return productos.marcar_publicado(p["id"], telegram_msg_id=10)


# ================================================================== pedidos
def test_no_se_vende_un_cuento_sin_publicar(tienda):
    p = productos.generar(GenerarCuento(tema="un barco de papel", edad=6))
    with pytest.raises(EstadoInvalido):
        pedidos.crear(p["id"], "555", "ana")


def test_pedido_gratis_se_entrega_directo(tienda):
    prod = _publicado(precio=0)
    pedido, es_nuevo = pedidos.crear(prod["id"], "555", "ana")
    assert es_nuevo is True
    assert pedido["es_gratis"] is True
    assert pedido["puede_entregar"] is True
    assert pedido["instrucciones_pago"] is None

    entregado = pedidos.entregar(pedido["id"])
    assert entregado["estado"] == "entregado"
    chat_id, nombre = tienda["documentos"][0]
    assert chat_id == "555" and nombre.endswith(".md")


def test_pedido_repetido_reutiliza_el_abierto(tienda):
    prod = _publicado(precio=1500)
    a, nuevo_a = pedidos.crear(prod["id"], "9", None)
    b, nuevo_b = pedidos.crear(prod["id"], "9", None)
    assert (nuevo_a, nuevo_b) == (True, False)
    assert a["id"] == b["id"]


def test_despues_de_entregado_se_puede_volver_a_pedir(tienda):
    prod = _publicado(precio=0)
    a, _ = pedidos.crear(prod["id"], "9", None)
    pedidos.entregar(a["id"])
    b, es_nuevo = pedidos.crear(prod["id"], "9", None)
    assert es_nuevo is True and b["id"] != a["id"]


def test_flujo_de_pago_con_validacion_humana(tienda):
    prod = _publicado(precio=1500)
    pedido, _ = pedidos.crear(prod["id"], "777", "beto")
    assert pedido["puede_entregar"] is False
    assert "cuentos.demo" in pedido["instrucciones_pago"]
    assert "$1,500" in pedido["instrucciones_pago"]

    with pytest.raises(EstadoInvalido):                      # 409: no se entrega sin pagar
        pedidos.entregar(pedido["id"])

    pedidos.cambiar_estado(pedido["id"], "esperando_pago")
    con_foto = pedidos.registrar_comprobante("777", "foto123")
    assert con_foto["estado"] == "comprobante_recibido"
    assert con_foto["comprobante_file"] == "foto123"

    validado = pedidos.validar_pago(pedido["id"], "validar", "Transferencia recibida")
    assert validado["estado"] == "pagado"
    assert validado["puede_entregar"] is True
    assert validado["entrega_disparada"] is True
    assert tienda["entregas"] == [pedido["id"]]              # se avisó a n8n

    assert pedidos.entregar(pedido["id"])["estado"] == "entregado"


def test_pago_rechazado_vuelve_a_esperar_y_avisa(tienda):
    prod = _publicado(precio=1500)
    pedido, _ = pedidos.crear(prod["id"], "777", None)
    pedidos.registrar_comprobante("777", "foto-borrosa")
    rechazado = pedidos.validar_pago(pedido["id"], "rechazar", "No se lee el monto.")
    assert rechazado["estado"] == "esperando_pago"
    assert rechazado["estado_pago"] == "rechazado"
    assert rechazado["entrega_disparada"] is False
    chat_id, texto = tienda["mensajes"][0]
    assert chat_id == "777" and "No se lee el monto." in texto


def test_rechazo_sin_telegram_no_rompe(tienda, monkeypatch):
    def telegram_caido(chat_id, texto):
        raise ServicioNoDisponible("Telegram caído")

    monkeypatch.setattr(telegram_client, "enviar_mensaje", telegram_caido)
    prod = _publicado(precio=1500)
    pedido, _ = pedidos.crear(prod["id"], "777", None)
    rechazado = pedidos.validar_pago(pedido["id"], "rechazar", None)
    assert rechazado["estado_pago"] == "rechazado"           # el cambio se guardó igual


def test_reglas_de_pedidos_gratuitos(tienda):
    prod = _publicado(precio=0)
    pedido, _ = pedidos.crear(prod["id"], "1", None)
    with pytest.raises(EstadoInvalido):
        pedidos.cambiar_estado(pedido["id"], "esperando_pago")
    with pytest.raises(EstadoInvalido):
        pedidos.validar_pago(pedido["id"], "validar", None)


def test_comprobante_sin_pedido_es_404(tienda):
    with pytest.raises(NoEncontrado):
        pedidos.registrar_comprobante("nadie", "foto")


def test_si_n8n_no_responde_la_entrega_devuelve_false(monkeypatch):
    def n8n_caido(url, **kwargs):
        raise httpx.ConnectError("n8n apagado")

    monkeypatch.setattr(pedidos.httpx, "post", n8n_caido)
    assert pedidos.disparar_entrega(1) is False


# ================================================================ consultas
def test_boton_del_canal_es_un_pedido_por_regla(tienda):
    prod = _publicado()
    r = consultas.atender("1", "ana", f"/start prod_{prod['id']}")
    assert (r["intencion"], r["producto_id"], r["origen"]) == ("pedido", prod["id"], "regla")
    assert r["proveedor_ia"] is None                           # no se gastó IA


def test_catalogo_por_regla(tienda):
    prod = _publicado(precio=0)
    r = consultas.atender("1", None, "/catalogo")
    assert r["origen"] == "regla"
    assert f"N° {prod['id']}" in r["respuesta"] and "gratis" in r["respuesta"]


def test_pedido_escrito_con_numero(tienda):
    prod = _publicado()
    r = consultas.atender("1", None, f"Hola! quiero el N° {prod['id']} por favor")
    assert (r["intencion"], r["producto_id"], r["origen"]) == ("pedido", prod["id"], "regla")


def test_pedido_de_un_cuento_que_no_existe(tienda):
    _publicado()
    r = consultas.atender("1", None, "/start prod_999")
    assert r["intencion"] == "consulta"
    assert "no está disponible" in r["respuesta"]


def test_texto_libre_lo_interpreta_la_ia(tienda):
    _publicado()
    r = consultas.atender("1", None, "¿qué cuentos tienen para 6 años?")
    assert (r["origen"], r["proveedor_ia"], r["intencion"]) == ("ia", "mock", "consulta")


def test_el_codigo_corrige_a_la_ia_si_inventa_un_producto(tienda, monkeypatch):
    _publicado()
    inventado = json.dumps({"intencion": "pedido", "producto_id": 999, "respuesta": "¡Te mando el 999!"})
    monkeypatch.setattr(ia, "generar_texto", lambda *a, **k: ia.RespuestaIA(inventado, "mock"))
    r = consultas.atender("1", None, "dame ese que me gustó")
    assert r["intencion"] == "consulta"                       # no se crea un pedido falso
    assert r["producto_id"] is None
    assert "¿Qué cuento te gustaría?" in r["respuesta"]


def test_si_no_hay_ia_responde_igual(tienda, monkeypatch):
    monkeypatch.setattr(config, "ia_proveedores", ["gemini"])
    monkeypatch.setattr(config, "gemini_api_key", "")
    r = consultas.atender("1", None, "hola, ¿cómo funciona?")
    assert r["proveedor_ia"] == "sin_ia"
    assert "/catalogo" in r["respuesta"]


def test_las_consultas_quedan_registradas_y_cuentan(tienda):
    prod = _publicado(precio=1500)
    consultas.atender("1", None, "/catalogo")
    consultas.atender("1", None, "¿tienen algo de dragones?")
    pedido, _ = pedidos.crear(prod["id"], "1", None)
    pedidos.registrar_comprobante("1", "foto")

    assert len(consultas.listar()) == 2
    est = consultas.estadisticas()
    assert est["consultas_por_origen"] == {"regla": 1, "ia": 1}
    assert est["pagos_por_validar"] == 1
    assert est["hay_pendientes"] is True