"""Pruebas de la Etapa 2: configuración y errores.

Ejecutar:  pytest -q
"""
from pathlib import Path

import pytest

from app.config import Config, _lista
from app.errores import (
    ErrorDominio,
    EstadoInvalido,
    NoEncontrado,
    ServicioNoDisponible,
    ValidacionFallida,
)


# ------------------------------------------------------------- configuración
def test_lista_limpia_espacios_y_mayusculas():
    assert _lista(" Mock, Gemini ,, groq ") == ["mock", "gemini", "groq"]


def test_config_lee_variables_de_entorno(monkeypatch):
    monkeypatch.setenv("IA_PROVEEDORES", "mock")
    monkeypatch.setenv("PRECIO_POR_DEFECTO", "1500")
    cfg = Config()  # instancia nueva: lee el entorno en este momento
    assert cfg.ia_proveedores == ["mock"]
    assert cfg.precio_por_defecto == 1500.0


def test_config_usa_valores_por_defecto(monkeypatch):
    monkeypatch.delenv("IA_PROVEEDORES", raising=False)
    monkeypatch.delenv("GROQ_MODEL", raising=False)
    cfg = Config()
    assert cfg.ia_proveedores == ["gemini", "groq"]
    assert cfg.groq_model == "openai/gpt-oss-120b"


def test_rutas_se_calculan_desde_data_dir(tmp_path):
    cfg = Config(data_dir=tmp_path)
    assert cfg.db_path == tmp_path / "tienda.db"
    assert cfg.cuentos_dir == tmp_path / "cuentos"
    assert isinstance(cfg.db_path, Path)


# ------------------------------------------------------------------- errores
@pytest.mark.parametrize(
    "clase, codigo",
    [
        (NoEncontrado, 404),
        (EstadoInvalido, 409),
        (ValidacionFallida, 422),
        (ServicioNoDisponible, 503),
    ],
)
def test_cada_error_tiene_su_codigo_http(clase, codigo):
    error = clase("mensaje de prueba")
    assert error.status_code == codigo
    assert error.mensaje == "mensaje de prueba"
    assert isinstance(error, ErrorDominio)


def test_un_solo_except_atrapa_todos_los_errores():
    with pytest.raises(ErrorDominio) as info:
        raise NoEncontrado("No existe el producto 9999")
    assert info.value.status_code == 404