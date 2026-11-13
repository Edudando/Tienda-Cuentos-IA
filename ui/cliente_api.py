"""Cliente HTTP del panel: el único lugar donde Streamlit habla con la API.

El panel no tiene lógica de negocio. Todo lo que decide (validar, aprobar,
cobrar, entregar) lo decide la API; acá solo se piden datos y se muestran.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT = float(os.getenv("UI_TIMEOUT", "120"))  # generar un cuento con IA puede tardar


class ErrorAPI(Exception):
    """Error devuelto por la API, ya traducido para mostrar en pantalla."""

    def __init__(self, status: int, mensaje: str):
        super().__init__(mensaje)
        self.status = status
        self.mensaje = mensaje


EXPLICACION = {
    404: "No existe",
    409: "No corresponde al estado actual",
    422: "Datos inválidos",
    503: "Servicio externo no disponible (IA o Telegram)",
}


def _detalle(r: httpx.Response) -> str:
    try:
        datos = r.json()
    except ValueError:
        return r.text[:300] or "Respuesta vacía"
    if isinstance(datos, dict) and "detalle" in datos:  # errores de dominio: {"error", "detalle"}
        return str(datos["detalle"])
    if isinstance(datos, dict) and isinstance(datos.get("detail"), list):  # 422 automático de FastAPI
        partes = []
        for e in datos["detail"]:
            campo = ".".join(str(x) for x in e.get("loc", [])[1:]) or "dato"
            partes.append(f"{campo}: {e.get('msg', '')}")
        return "; ".join(partes)
    return str(datos)


def _pedir(metodo: str, ruta: str, **kwargs: Any) -> httpx.Response:
    try:
        r = httpx.request(metodo, f"{API_URL}{ruta}", timeout=TIMEOUT, **kwargs)
    except httpx.HTTPError as exc:
        raise ErrorAPI(0, f"No se pudo conectar con la API en {API_URL} ({type(exc).__name__})") from exc
    if r.status_code >= 400:
        titulo = EXPLICACION.get(r.status_code, "Error")
        raise ErrorAPI(r.status_code, f"{r.status_code} · {titulo}: {_detalle(r)}")
    return r


def _json(metodo: str, ruta: str, **kwargs: Any) -> Any:
    return _pedir(metodo, ruta, **kwargs).json()


# ------------------------------------------------------------ sistema
def salud() -> dict:
    return _json("GET", "/salud")


def estadisticas() -> dict:
    return _json("GET", "/estadisticas")


# ------------------------------------------------------------ productos
def generar(datos: dict) -> dict:
    return _json("POST", "/productos/generar", json=datos)


def productos(estado: str | None = None) -> list[dict]:
    return _json("GET", "/productos", params={"estado": estado} if estado else None)


def producto(producto_id: int) -> dict:
    return _json("GET", f"/productos/{producto_id}")


def editar(producto_id: int, cambios: dict) -> dict:
    return _json("PATCH", f"/productos/{producto_id}", json=cambios)


def revisar(producto_id: int, decision: str, nota: str | None) -> dict:
    return _json("POST", f"/productos/{producto_id}/revision", json={"decision": decision, "nota": nota or None})


def archivo(producto_id: int) -> bytes:
    return _pedir("GET", f"/productos/{producto_id}/archivo").content


# ------------------------------------------------------------ pedidos
def pedidos(estado: str | None = None) -> list[dict]:
    return _json("GET", "/pedidos", params={"estado": estado} if estado else None)


def comprobante(pedido_id: int) -> bytes:
    return _pedir("GET", f"/pedidos/{pedido_id}/comprobante").content


def validar_pago(pedido_id: int, accion: str, nota: str | None) -> dict:
    return _json("PATCH", f"/pedidos/{pedido_id}/pago", json={"accion": accion, "nota": nota or None})


def entregar(pedido_id: int) -> dict:
    return _json("POST", f"/pedidos/{pedido_id}/entregar")


# ------------------------------------------------------------ consultas
def consultas(limite: int = 100) -> list[dict]:
    return _json("GET", "/consultas", params={"limite": limite})


def probar_consulta(texto: str) -> dict:
    return _json("POST", "/consultas", json={"chat_id": "panel", "usuario": "prueba-panel", "texto": texto})
