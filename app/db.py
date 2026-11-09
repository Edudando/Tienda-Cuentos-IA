"""Persistencia en SQLite.

Una función por operación, sin ORM, para que cada consulta sea fácil de
explicar en la defensa. Las filas se devuelven como diccionarios.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from typing import Any, Iterator

from app.config import config

ESQUEMA = """
CREATE TABLE IF NOT EXISTS productos (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    titulo          TEXT NOT NULL,
    tema            TEXT NOT NULL,
    edad            INTEGER NOT NULL,
    valores         TEXT,
    contenido_md    TEXT NOT NULL,
    archivo         TEXT,
    promo           TEXT,
    precio          REAL NOT NULL DEFAULT 0,
    estado          TEXT NOT NULL DEFAULT 'pendiente',  -- pendiente | aprobado | publicado | rechazado
    validaciones    TEXT NOT NULL DEFAULT '[]',         -- JSON: resultado de las reglas
    proveedor_ia    TEXT,
    nota_revision   TEXT,
    telegram_msg_id INTEGER,
    creado          TEXT NOT NULL,
    actualizado     TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS pedidos (
    id               INTEGER PRIMARY KEY AUTOINCREMENT,
    producto_id      INTEGER NOT NULL REFERENCES productos(id),
    chat_id          TEXT NOT NULL,
    usuario          TEXT,
    precio           REAL NOT NULL DEFAULT 0,
    estado           TEXT NOT NULL DEFAULT 'nuevo',     -- nuevo | esperando_pago | comprobante_recibido | pagado | entregado
    estado_pago      TEXT NOT NULL DEFAULT 'no_aplica', -- no_aplica | pendiente | validado | rechazado
    comprobante_file TEXT,
    nota             TEXT,
    creado           TEXT NOT NULL,
    actualizado      TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS consultas (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    chat_id      TEXT NOT NULL,
    usuario      TEXT,
    texto        TEXT NOT NULL,
    intencion    TEXT NOT NULL,
    producto_id  INTEGER,
    respuesta    TEXT NOT NULL,
    origen       TEXT NOT NULL,   -- regla | ia
    proveedor_ia TEXT,
    creado       TEXT NOT NULL
);
"""


def ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


@contextmanager
def conexion() -> Iterator[sqlite3.Connection]:
    config.data_dir.mkdir(parents=True, exist_ok=True)
    con = sqlite3.connect(config.db_path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys = ON")
    try:
        yield con
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.close()


def inicializar() -> None:
    config.cuentos_dir.mkdir(parents=True, exist_ok=True)
    with conexion() as con:
        con.executescript(ESQUEMA)


def _a_dict(fila: sqlite3.Row | None) -> dict[str, Any] | None:
    if fila is None:
        return None
    datos = dict(fila)
    if "validaciones" in datos and isinstance(datos["validaciones"], str):
        datos["validaciones"] = json.loads(datos["validaciones"] or "[]")
    return datos


# ---------------------------------------------------------------- productos
def insertar_producto(datos: dict[str, Any]) -> int:
    datos = {**datos, "validaciones": json.dumps(datos.get("validaciones", []), ensure_ascii=False)}
    datos.setdefault("creado", ahora())
    datos.setdefault("actualizado", datos["creado"])
    columnas = ", ".join(datos)
    marcas = ", ".join(f":{c}" for c in datos)
    with conexion() as con:
        cur = con.execute(f"INSERT INTO productos ({columnas}) VALUES ({marcas})", datos)
        return int(cur.lastrowid)


def obtener_producto(producto_id: int) -> dict[str, Any] | None:
    with conexion() as con:
        return _a_dict(con.execute("SELECT * FROM productos WHERE id = ?", (producto_id,)).fetchone())


def listar_productos(estado: str | None = None) -> list[dict[str, Any]]:
    sql, params = "SELECT * FROM productos", ()
    if estado:
        sql, params = sql + " WHERE estado = ?", (estado,)
    with conexion() as con:
        return [_a_dict(f) for f in con.execute(sql + " ORDER BY id DESC", params).fetchall()]


def actualizar_producto(producto_id: int, cambios: dict[str, Any]) -> None:
    if "validaciones" in cambios:
        cambios = {**cambios, "validaciones": json.dumps(cambios["validaciones"], ensure_ascii=False)}
    cambios = {**cambios, "actualizado": ahora()}
    asignaciones = ", ".join(f"{c} = :{c}" for c in cambios)
    with conexion() as con:
        con.execute(f"UPDATE productos SET {asignaciones} WHERE id = :id", {**cambios, "id": producto_id})


# ------------------------------------------------------------------ pedidos
def insertar_pedido(datos: dict[str, Any]) -> int:
    datos = {**datos}
    datos.setdefault("creado", ahora())
    datos.setdefault("actualizado", datos["creado"])
    columnas = ", ".join(datos)
    marcas = ", ".join(f":{c}" for c in datos)
    with conexion() as con:
        cur = con.execute(f"INSERT INTO pedidos ({columnas}) VALUES ({marcas})", datos)
        return int(cur.lastrowid)


def obtener_pedido(pedido_id: int) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            """SELECT p.*, pr.titulo AS producto_titulo
               FROM pedidos p JOIN productos pr ON pr.id = p.producto_id
               WHERE p.id = ?""",
            (pedido_id,),
        ).fetchone()
        return _a_dict(fila)


def listar_pedidos(estado: str | None = None) -> list[dict[str, Any]]:
    sql = """SELECT p.*, pr.titulo AS producto_titulo
             FROM pedidos p JOIN productos pr ON pr.id = p.producto_id"""
    params: tuple = ()
    if estado:
        sql, params = sql + " WHERE p.estado = ?", (estado,)
    with conexion() as con:
        return [_a_dict(f) for f in con.execute(sql + " ORDER BY p.id DESC", params).fetchall()]


def buscar_pedido_activo(chat_id: str, producto_id: int) -> dict[str, Any] | None:
    """Pedido no entregado del mismo cliente y producto (evita duplicados)."""
    with conexion() as con:
        fila = con.execute(
            "SELECT id FROM pedidos WHERE chat_id = ? AND producto_id = ? AND estado != 'entregado' "
            "ORDER BY id DESC LIMIT 1",
            (chat_id, producto_id),
        ).fetchone()
    return obtener_pedido(fila["id"]) if fila else None


def ultimo_pedido_esperando_pago(chat_id: str) -> dict[str, Any] | None:
    with conexion() as con:
        fila = con.execute(
            "SELECT id FROM pedidos WHERE chat_id = ? AND estado IN ('esperando_pago', 'nuevo') "
            "AND precio > 0 ORDER BY id DESC LIMIT 1",
            (chat_id,),
        ).fetchone()
    return obtener_pedido(fila["id"]) if fila else None


def actualizar_pedido(pedido_id: int, cambios: dict[str, Any]) -> None:
    cambios = {**cambios, "actualizado": ahora()}
    asignaciones = ", ".join(f"{c} = :{c}" for c in cambios)
    with conexion() as con:
        con.execute(f"UPDATE pedidos SET {asignaciones} WHERE id = :id", {**cambios, "id": pedido_id})


# ---------------------------------------------------------------- consultas
def insertar_consulta(datos: dict[str, Any]) -> int:
    datos = {**datos}
    datos.setdefault("creado", ahora())
    columnas = ", ".join(datos)
    marcas = ", ".join(f":{c}" for c in datos)
    with conexion() as con:
        cur = con.execute(f"INSERT INTO consultas ({columnas}) VALUES ({marcas})", datos)
        return int(cur.lastrowid)


def listar_consultas(limite: int = 100) -> list[dict[str, Any]]:
    with conexion() as con:
        filas = con.execute("SELECT * FROM consultas ORDER BY id DESC LIMIT ?", (limite,)).fetchall()
        return [_a_dict(f) for f in filas]


# ------------------------------------------------------------- estadísticas
def contar(tabla: str, columna: str) -> dict[str, int]:
    if tabla not in {"productos", "pedidos", "consultas"} or not columna.isidentifier():
        raise ValueError("Tabla o columna no permitida")
    with conexion() as con:
        filas = con.execute(f"SELECT {columna} AS clave, COUNT(*) AS n FROM {tabla} GROUP BY {columna}").fetchall()
        return {str(f["clave"]): int(f["n"]) for f in filas}