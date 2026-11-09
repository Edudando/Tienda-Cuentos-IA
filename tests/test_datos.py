"""Pruebas de la Etapa 3: modelos de entrada y base de datos.

Ejecutar:  pytest -q
"""
import sqlite3

import pytest
from pydantic import ValidationError

from app import db
from app.config import config
from app.modelos import GenerarCuento, NuevoPedido, Revision


# ------------------------------------------------------------------- modelos
def test_generar_cuento_limpia_espacios():
    datos = GenerarCuento(tema="  un dragón miedoso  ", edad=5, personaje=" Tomi ")
    assert datos.tema == "un dragón miedoso"
    assert datos.personaje == "Tomi"
    assert datos.precio is None  # campo opcional


@pytest.mark.parametrize(
    "cuerpo",
    [
        {"tema": "un dragón", "edad": 2},       # edad menor a 3
        {"tema": "un dragón", "edad": 13},      # edad mayor a 12
        {"tema": "un dragón", "edad": "cinco"},  # no es un número
        {"tema": "ab", "edad": 5},              # tema demasiado corto
        {"tema": "     ", "edad": 5},           # solo espacios
        {"edad": 5},                            # falta el tema
    ],
)
def test_generar_cuento_rechaza_datos_invalidos(cuerpo):
    with pytest.raises(ValidationError):
        GenerarCuento(**cuerpo)


def test_revision_solo_acepta_aprobar_o_rechazar():
    assert Revision(decision="aprobar").decision == "aprobar"
    with pytest.raises(ValidationError):
        Revision(decision="tal vez")


def test_pedido_exige_producto_positivo():
    with pytest.raises(ValidationError):
        NuevoPedido(producto_id=0, chat_id="123")


# ------------------------------------------------------------ base de datos
@pytest.fixture()
def base(tmp_path, monkeypatch):
    """Base SQLite nueva y vacía en una carpeta temporal para cada test."""
    monkeypatch.setattr(config, "data_dir", tmp_path)
    db.inicializar()
    return tmp_path


def _producto(**cambios):
    datos = {
        "titulo": "Tomi y la noche",
        "tema": "un dragón miedoso",
        "edad": 5,
        "contenido_md": "# Tomi y la noche\n\nHabía una vez...",
        "validaciones": [{"regla": "titulo", "ok": True}],
    }
    return {**datos, **cambios}


def test_inicializar_crea_la_base_y_la_carpeta(base):
    assert (base / "tienda.db").exists()
    assert (base / "cuentos").is_dir()


def test_insertar_y_obtener_producto(base):
    pid = db.insertar_producto(_producto())
    p = db.obtener_producto(pid)
    assert p["titulo"] == "Tomi y la noche"
    assert p["estado"] == "pendiente"          # valor por defecto de la tabla
    assert p["precio"] == 0
    assert p["validaciones"] == [{"regla": "titulo", "ok": True}]  # vuelve como lista, no como texto


def test_obtener_inexistente_devuelve_none(base):
    assert db.obtener_producto(9999) is None


def test_listar_filtra_por_estado(base):
    db.insertar_producto(_producto())
    db.insertar_producto(_producto(titulo="Otro", estado="aprobado"))
    assert len(db.listar_productos()) == 2
    aprobados = db.listar_productos("aprobado")
    assert [p["titulo"] for p in aprobados] == ["Otro"]


def test_actualizar_producto(base):
    pid = db.insertar_producto(_producto())
    db.actualizar_producto(pid, {"estado": "aprobado", "nota_revision": "OK"})
    p = db.obtener_producto(pid)
    assert p["estado"] == "aprobado"
    assert p["nota_revision"] == "OK"


def test_pedido_trae_el_titulo_del_producto(base):
    pid = db.insertar_producto(_producto())
    pedido_id = db.insertar_pedido({"producto_id": pid, "chat_id": "123"})
    pedido = db.obtener_pedido(pedido_id)
    assert pedido["producto_titulo"] == "Tomi y la noche"  # viene del JOIN
    assert pedido["estado"] == "nuevo"


def test_no_se_puede_pedir_un_producto_que_no_existe(base):
    with pytest.raises(sqlite3.IntegrityError):
        db.insertar_pedido({"producto_id": 9999, "chat_id": "123"})


def test_buscar_pedido_activo_evita_duplicados(base):
    pid = db.insertar_producto(_producto())
    pedido_id = db.insertar_pedido({"producto_id": pid, "chat_id": "123"})
    assert db.buscar_pedido_activo("123", pid)["id"] == pedido_id
    assert db.buscar_pedido_activo("otro_cliente", pid) is None
    db.actualizar_pedido(pedido_id, {"estado": "entregado"})
    assert db.buscar_pedido_activo("123", pid) is None  # entregado ya no cuenta


def test_contar_agrupa_y_rechaza_tablas_desconocidas(base):
    db.insertar_producto(_producto())
    db.insertar_producto(_producto())
    db.insertar_producto(_producto(estado="aprobado"))
    assert db.contar("productos", "estado") == {"pendiente": 2, "aprobado": 1}
    with pytest.raises(ValueError):
        db.contar("usuarios; DROP TABLE productos", "estado")