"""Pruebas de la Etapa 4: reglas de validación y cliente de IA.

Ejecutar:  pytest -q
Ninguna prueba usa internet: la IA real se reemplaza por el proveedor "mock"
o por respuestas falsas.
"""
import httpx
import pytest

from app import ia
from app.config import config
from app.errores import ServicioNoDisponible
from app.validaciones import (
    contar_palabras,
    extraer_titulo,
    hay_bloqueos,
    rango_para_edad,
    validar_cuento,
    validar_promo,
)

PARRAFO = "Tomi era un dragón pequeño que vivía en una cueva junto al río del bosque. " * 4
CUENTO_OK = "# Tomi y la noche\n\n" + "\n\n".join([PARRAFO] * 4)


def _regla(resultados, nombre):
    return next(r for r in resultados if r["regla"] == nombre)


# --------------------------------------------------------------- validaciones
def test_cuento_correcto_no_tiene_bloqueos():
    resultados = validar_cuento(CUENTO_OK, edad=6)
    assert all(r["ok"] for r in resultados), resultados
    assert hay_bloqueos(resultados) is False


def test_falta_titulo_bloquea():
    resultados = validar_cuento(CUENTO_OK.replace("# ", ""), edad=6)
    assert _regla(resultados, "titulo")["ok"] is False
    assert hay_bloqueos(resultados) is True


def test_detecta_palabras_prohibidas_enteras():
    con_prohibida = CUENTO_OK + "\n\nY entonces apareció un arma."
    assert "arma" in _regla(validar_cuento(con_prohibida, 6), "vocabulario")["detalle"]
    # "armadura" contiene "arma", pero es otra palabra: no se marca
    con_armadura = CUENTO_OK + "\n\nY entonces apareció una armadura."
    assert _regla(validar_cuento(con_armadura, 6), "vocabulario")["ok"] is True


def test_detecta_enlaces():
    con_link = CUENTO_OK + "\n\nMás en https://ejemplo.com"
    assert _regla(validar_cuento(con_link, 6), "sin_enlaces")["ok"] is False


def test_pocos_parrafos_es_solo_advertencia():
    corto = "# Título\n\n" + PARRAFO * 5  # un solo bloque de texto, largo suficiente
    resultados = validar_cuento(corto, edad=6)
    estructura = _regla(resultados, "estructura")
    assert estructura["ok"] is False
    assert estructura["bloqueante"] is False
    assert hay_bloqueos(resultados) is False  # no impide aprobar


def test_largo_depende_de_la_edad():
    assert rango_para_edad(4) == (120, 600)
    assert rango_para_edad(12) == (300, 1400)
    with pytest.raises(ValueError):
        rango_para_edad(15)


def test_ayudantes_de_texto():
    assert contar_palabras("Había una vez, un gato.") == 5
    assert extraer_titulo("texto\n# Mi cuento\nmás texto") == "Mi cuento"
    assert extraer_titulo("sin título") is None


def test_promo_vacia_bloquea():
    assert hay_bloqueos(validar_promo("")) is True
    assert hay_bloqueos(validar_promo("Nuevo cuento para leer en familia.")) is False


# ------------------------------------------------------------------------- IA
def test_mock_genera_un_cuento_que_pasa_las_reglas(monkeypatch):
    monkeypatch.setattr(config, "ia_proveedores", ["mock"])
    r = ia.generar_texto("p", "s", tarea="cuento", contexto={"tema": "un dragón miedoso", "personaje": "Tomi"})
    assert r.proveedor == "mock"
    assert r.texto.startswith("# Tomi y un dragón miedoso")
    assert hay_bloqueos(validar_cuento(r.texto, edad=6)) is False


def test_fallback_salta_al_siguiente_si_falta_la_clave(monkeypatch):
    monkeypatch.setattr(config, "ia_proveedores", ["gemini", "groq", "mock"])
    monkeypatch.setattr(config, "gemini_api_key", "")
    monkeypatch.setattr(config, "groq_api_key", "")
    r = ia.generar_texto("p", "s", tarea="promo", contexto={"titulo": "Tomi"})
    assert r.proveedor == "mock"


def test_fallback_ante_limite_de_uso_429(monkeypatch):
    monkeypatch.setattr(config, "ia_proveedores", ["gemini", "mock"])
    monkeypatch.setattr(config, "gemini_api_key", "clave-falsa")
    llamadas = []

    def post_falso(url, **kwargs):
        llamadas.append(url)
        return httpx.Response(429, request=httpx.Request("POST", url))

    monkeypatch.setattr(ia.httpx, "post", post_falso)
    r = ia.generar_texto("p", "s", tarea="promo", contexto={})
    assert len(llamadas) == 1          # se intentó Gemini...
    assert r.proveedor == "mock"       # ...y respondió el siguiente


def test_si_ninguno_responde_es_503(monkeypatch):
    monkeypatch.setattr(config, "ia_proveedores", ["gemini", "inventado"])
    monkeypatch.setattr(config, "gemini_api_key", "")
    with pytest.raises(ServicioNoDisponible) as info:
        ia.generar_texto("p", "s")
    assert info.value.status_code == 503
    assert "GEMINI_API_KEY" in info.value.mensaje
    assert "inventado" in info.value.mensaje


def test_extraer_json_tolera_bloques_de_codigo():
    texto = '```json\n{"intencion": "pedido", "producto_id": 3}\n```'
    assert ia.extraer_json(texto) == {"intencion": "pedido", "producto_id": 3}
    with pytest.raises(ValueError):
        ia.extraer_json("no hay json acá")

def test_promo_cortada_bloquea():
    assert hay_bloqueos(validar_promo("Un cuento hermoso para leer en familia. Pedilo toc")) is True
    assert hay_bloqueos(validar_promo("Un cuento hermoso para leer en familia. ¡Pedilo! 🐢")) is False


def test_groq_sin_texto_pasa_al_siguiente(monkeypatch):
    monkeypatch.setattr(config, "ia_proveedores", ["groq", "mock"])
    monkeypatch.setattr(config, "groq_api_key", "clave-falsa")

    def post_falso(url, **kwargs):
        return httpx.Response(200, json={"error": "formato raro"}, request=httpx.Request("POST", url))

    monkeypatch.setattr(ia.httpx, "post", post_falso)
    r = ia.generar_texto("p", "s", tarea="promo", contexto={})
    assert r.proveedor == "mock"
