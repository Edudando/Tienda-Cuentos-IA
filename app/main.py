"""API REST de la Tienda de Cuentos IA (FastAPI).

Ejecutar en local:  uvicorn app.main:app --reload
Documentación interactiva: http://localhost:8000/docs
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, Query, Request, Response, status
from fastapi.responses import JSONResponse

from app import db
from app.config import config
from app.errores import ErrorDominio
from app.modelos import (
    CambioEstadoPedido,
    Comprobante,
    EditarProducto,
    GenerarCuento,
    MarcarPublicado,
    NuevaConsulta,
    NuevoPedido,
    Revision,
    ValidacionPago,
)
from app.servicios import consultas, pedidos, productos

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


@asynccontextmanager
async def ciclo_de_vida(_: FastAPI):
    db.inicializar()
    yield


app = FastAPI(
    title="Tienda de Cuentos IA",
    description="Genera cuentos infantiles con IA, los publica en un canal de Telegram y los entrega por el bot.",
    version="1.0.0",
    lifespan=ciclo_de_vida,
)


@app.exception_handler(ErrorDominio)
async def manejar_error_dominio(_: Request, exc: ErrorDominio) -> JSONResponse:
    return JSONResponse(status_code=exc.status_code, content={"error": type(exc).__name__, "detalle": exc.mensaje})


# ------------------------------------------------------------------ sistema
@app.get("/salud", tags=["sistema"])
def salud() -> dict:
    return {
        "estado": "ok",
        "proveedores_ia": config.ia_proveedores,
        "telegram_configurado": bool(config.telegram_token),
    }


@app.get("/estadisticas", tags=["sistema"])
def estadisticas() -> dict:
    return consultas.estadisticas()


# ---------------------------------------------------------------- productos
@app.post("/productos/generar", status_code=status.HTTP_201_CREATED, tags=["productos"])
def generar_producto(datos: GenerarCuento) -> dict:
    """La IA escribe el cuento y el texto promocional; las reglas lo validan. Queda 'pendiente'."""
    return productos.generar(datos)


@app.get("/productos", tags=["productos"])
def listar_productos(estado: str | None = Query(default=None)) -> list[dict]:
    return productos.listar(estado)


@app.get("/productos/{producto_id}", tags=["productos"])
def obtener_producto(producto_id: int) -> dict:
    return productos.obtener(producto_id)


@app.patch("/productos/{producto_id}", tags=["productos"])
def editar_producto(producto_id: int, cambios: EditarProducto) -> dict:
    """Edición humana del cuento, la promo o el precio. Vuelve a 'pendiente'."""
    return productos.editar(producto_id, cambios)


@app.post("/productos/{producto_id}/revision", tags=["productos"])
def revisar_producto(producto_id: int, revision: Revision) -> dict:
    """Supervisión humana: aprobar o rechazar."""
    return productos.revisar(producto_id, revision.decision, revision.nota)


@app.patch("/productos/{producto_id}/publicacion", tags=["productos"])
def marcar_publicado(producto_id: int, datos: MarcarPublicado) -> dict:
    """Lo llama n8n después de publicar en el canal."""
    return productos.marcar_publicado(producto_id, datos.telegram_msg_id)


@app.get("/productos/{producto_id}/archivo", tags=["productos"])
def descargar_archivo(producto_id: int) -> Response:
    nombre, contenido = productos.leer_archivo(producto_id)
    return Response(
        content=contenido,
        media_type="text/markdown; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{nombre}"'},
    )


# ---------------------------------------------------------------- consultas
@app.post("/consultas", tags=["atención"])
def nueva_consulta(datos: NuevaConsulta) -> dict:
    """Clasifica el mensaje (reglas + IA) y devuelve la respuesta sugerida y la intención."""
    return consultas.atender(datos.chat_id, datos.usuario, datos.texto)


@app.get("/consultas", tags=["atención"])
def listar_consultas(limite: int = Query(default=100, ge=1, le=500)) -> list[dict]:
    return consultas.listar(limite)


# ------------------------------------------------------------------ pedidos
@app.post("/pedidos", tags=["pedidos"])
def crear_pedido(datos: NuevoPedido, response: Response) -> dict:
    pedido, es_nuevo = pedidos.crear(datos.producto_id, datos.chat_id, datos.usuario)
    response.status_code = status.HTTP_201_CREATED if es_nuevo else status.HTTP_200_OK
    return {**pedido, "es_nuevo": es_nuevo}


@app.get("/pedidos", tags=["pedidos"])
def listar_pedidos(estado: str | None = Query(default=None)) -> list[dict]:
    return pedidos.listar(estado)


@app.get("/pedidos/{pedido_id}", tags=["pedidos"])
def obtener_pedido(pedido_id: int) -> dict:
    return pedidos.obtener(pedido_id)


@app.patch("/pedidos/{pedido_id}/estado", tags=["pedidos"])
def cambiar_estado_pedido(pedido_id: int, datos: CambioEstadoPedido) -> dict:
    return pedidos.cambiar_estado(pedido_id, datos.estado)


@app.post("/pedidos/comprobante", tags=["pedidos"])
def registrar_comprobante(datos: Comprobante) -> dict:
    """El cliente mandó una foto: se asocia a su último pedido que espera pago."""
    return pedidos.registrar_comprobante(datos.chat_id, datos.file_id)


@app.get("/pedidos/{pedido_id}/comprobante", tags=["pedidos"])
def ver_comprobante(pedido_id: int) -> Response:
    return Response(content=pedidos.comprobante(pedido_id), media_type="image/jpeg")


@app.patch("/pedidos/{pedido_id}/pago", tags=["pedidos"])
def validar_pago(pedido_id: int, datos: ValidacionPago) -> dict:
    """Supervisión humana del pago. Si se valida, dispara el workflow de entrega."""
    return pedidos.validar_pago(pedido_id, datos.accion, datos.nota)


@app.post("/pedidos/{pedido_id}/entregar", tags=["pedidos"])
def entregar_pedido(pedido_id: int) -> dict:
    """Envía el .md por Telegram. Responde 409 si el pedido no está pago."""
    return pedidos.entregar(pedido_id)