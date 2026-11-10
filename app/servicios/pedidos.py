"""Pedidos, pagos y entrega del cuento por Telegram."""
from __future__ import annotations

import logging
from typing import Any

import httpx

from app import db, telegram_client
from app.config import config
from app.errores import EstadoInvalido, NoEncontrado, ServicioNoDisponible, ValidacionFallida
from app.servicios import productos

log = logging.getLogger("pedidos")

ESTADOS = {"nuevo", "esperando_pago", "comprobante_recibido", "pagado", "entregado"}


def _enriquecer(pedido: dict[str, Any]) -> dict[str, Any]:
    """Agrega campos calculados que n8n usa en sus condiciones."""
    pedido["es_gratis"] = pedido["precio"] == 0
    pedido["puede_entregar"] = pedido["es_gratis"] or pedido["estado_pago"] == "validado"
    pedido["instrucciones_pago"] = (
        None
        if pedido["es_gratis"]
        else (
            f"Para recibir \"{pedido['producto_titulo']}\" transferí ${pedido['precio']:,.0f} "
            f"al alias {config.alias_transferencia} y mandá la foto del comprobante por este chat. "
            f"Pedido N° {pedido['id']}."
        )
    )
    return pedido


def obtener(pedido_id: int) -> dict[str, Any]:
    pedido = db.obtener_pedido(pedido_id)
    if pedido is None:
        raise NoEncontrado(f"No existe el pedido {pedido_id}")
    return _enriquecer(pedido)


def listar(estado: str | None = None) -> list[dict[str, Any]]:
    if estado is not None and estado not in ESTADOS:
        raise ValidacionFallida(f"Estado inválido: {estado}")
    return [_enriquecer(p) for p in db.listar_pedidos(estado)]


def crear(producto_id: int, chat_id: str, usuario: str | None) -> tuple[dict[str, Any], bool]:
    """Devuelve (pedido, es_nuevo). Si ya hay un pedido abierto, lo reutiliza."""
    producto = productos.obtener(producto_id)
    if producto["estado"] != "publicado":
        raise EstadoInvalido(f"El cuento {producto_id} no está disponible para la venta")

    existente = db.buscar_pedido_activo(chat_id, producto_id)
    if existente:
        return _enriquecer(existente), False

    gratis = producto["precio"] == 0
    pedido_id = db.insertar_pedido(
        {
            "producto_id": producto_id,
            "chat_id": chat_id,
            "usuario": usuario,
            "precio": producto["precio"],
            "estado": "nuevo",
            "estado_pago": "no_aplica" if gratis else "pendiente",
        }
    )
    return obtener(pedido_id), True


def cambiar_estado(pedido_id: int, estado: str) -> dict[str, Any]:
    pedido = obtener(pedido_id)
    if pedido["estado"] == "entregado":
        raise EstadoInvalido("El pedido ya fue entregado")
    if estado == "esperando_pago" and pedido["es_gratis"]:
        raise EstadoInvalido("Un pedido gratuito no espera pago")
    db.actualizar_pedido(pedido_id, {"estado": estado})
    return obtener(pedido_id)


def registrar_comprobante(chat_id: str, file_id: str) -> dict[str, Any]:
    pedido = db.ultimo_pedido_esperando_pago(chat_id)
    if pedido is None:
        raise NoEncontrado("No hay pedidos esperando pago para este chat")
    db.actualizar_pedido(
        pedido["id"], {"estado": "comprobante_recibido", "comprobante_file": file_id, "estado_pago": "pendiente"}
    )
    return obtener(pedido["id"])


def validar_pago(pedido_id: int, accion: str, nota: str | None) -> dict[str, Any]:
    """Decisión humana sobre el comprobante. Si se valida, dispara la entrega en n8n."""
    pedido = obtener(pedido_id)
    if pedido["es_gratis"]:
        raise EstadoInvalido("El pedido es gratuito, no requiere validar pago")
    if pedido["estado"] == "entregado":
        raise EstadoInvalido("El pedido ya fue entregado")

    if accion == "validar":
        db.actualizar_pedido(pedido_id, {"estado_pago": "validado", "estado": "pagado", "nota": nota})
        resultado = obtener(pedido_id)
        resultado["entrega_disparada"] = disparar_entrega(pedido_id)
        return resultado

    db.actualizar_pedido(pedido_id, {"estado_pago": "rechazado", "estado": "esperando_pago", "nota": nota})
    try:
        telegram_client.enviar_mensaje(
            pedido["chat_id"],
            f"No pudimos validar el pago del pedido N° {pedido_id}. "
            f"{nota or ''} Podés mandar otro comprobante por este chat.".strip(),
        )
    except ServicioNoDisponible as exc:
        log.warning("No se avisó el rechazo por Telegram: %s", exc)
    resultado = obtener(pedido_id)
    resultado["entrega_disparada"] = False
    return resultado


def disparar_entrega(pedido_id: int) -> bool:
    """Llama al workflow 'Entrega' de n8n. Si n8n no responde, no rompe la operación."""
    try:
        r = httpx.post(config.n8n_webhook_entrega, json={"pedido_id": pedido_id}, timeout=10)
        return r.status_code < 400
    except httpx.HTTPError as exc:
        log.warning("No se pudo disparar la entrega en n8n: %s", exc)
        return False


def entregar(pedido_id: int) -> dict[str, Any]:
    """Envía el archivo .md al cliente. La regla de cobro se controla acá también."""
    pedido = obtener(pedido_id)
    if not pedido["puede_entregar"]:
        raise EstadoInvalido("El pedido no está pago: no se puede entregar")
    nombre, contenido = productos.leer_archivo(pedido["producto_id"])
    telegram_client.enviar_documento(
        pedido["chat_id"],
        nombre,
        contenido,
        leyenda=f"¡Acá está tu cuento \"{pedido['producto_titulo']}\"! Gracias por tu pedido N° {pedido_id}.",
    )
    db.actualizar_pedido(pedido_id, {"estado": "entregado"})
    return obtener(pedido_id)


def comprobante(pedido_id: int) -> bytes:
    pedido = obtener(pedido_id)
    if not pedido.get("comprobante_file"):
        raise NoEncontrado("El pedido no tiene comprobante")
    return telegram_client.descargar_archivo(pedido["comprobante_file"])