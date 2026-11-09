"""Generación, revisión humana y publicación de cuentos."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

from app import db, ia
from app.config import config
from app.errores import EstadoInvalido, NoEncontrado, ValidacionFallida
from app.modelos import EditarProducto, GenerarCuento
from app.validaciones import (
    extraer_titulo,
    hay_bloqueos,
    rango_para_edad,
    validar_cuento,
    validar_promo,
)

SISTEMA_CUENTO = (
    "Sos un autor de cuentos infantiles en español rioplatense. Escribís historias "
    "tiernas, con un conflicto simple y un final positivo. Nunca incluís violencia, "
    "lenguaje inapropiado ni enlaces. Respondés SOLO con el cuento en Markdown."
)

SISTEMA_PROMO = (
    "Sos community manager de una tienda de cuentos infantiles. Escribís textos "
    "breves, cálidos y sin exagerar para un canal de Telegram. Sin hashtags, sin "
    "enlaces y sin emojis en exceso (máximo dos)."
)

MAX_INTENTOS = 2


def _slug(texto: str) -> str:
    texto = unicodedata.normalize("NFKD", texto).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", "-", texto.lower()).strip("-")[:50] or "cuento"


def _prompt_cuento(datos: GenerarCuento, correcciones: list[str]) -> str:
    minimo, maximo = rango_para_edad(datos.edad)
    partes = [
        f"Escribí un cuento infantil sobre: {datos.tema}.",
        f"Edad lectora: {datos.edad} años. Largo: entre {minimo} y {maximo} palabras.",
        "Formato: primera línea '# Título', luego párrafos separados por una línea en blanco.",
    ]
    if datos.personaje:
        partes.append(f"Protagonista: {datos.personaje}.")
    if datos.valores:
        partes.append(f"El cuento transmite: {datos.valores}.")
    if correcciones:
        partes.append("El intento anterior no cumplió estas reglas, corregilo: " + "; ".join(correcciones))
    return "\n".join(partes)


def _guardar_archivo(producto_id: int, titulo: str, contenido: str) -> str:
    config.cuentos_dir.mkdir(parents=True, exist_ok=True)
    nombre = f"{producto_id:04d}-{_slug(titulo)}.md"
    (config.cuentos_dir / nombre).write_text(contenido, encoding="utf-8", newline="\n")
    return nombre


def generar(datos: GenerarCuento) -> dict[str, Any]:
    """IA escribe el cuento -> reglas lo validan -> si falla, un reintento con feedback."""
    contexto = datos.model_dump()
    correcciones: list[str] = []
    for _ in range(MAX_INTENTOS):
        respuesta = ia.generar_texto(
            _prompt_cuento(datos, correcciones), SISTEMA_CUENTO, tarea="cuento", contexto=contexto
        )
        contenido = respuesta.texto
        validaciones = validar_cuento(contenido, datos.edad)
        if not hay_bloqueos(validaciones):
            break
        correcciones = [v["detalle"] for v in validaciones if not v["ok"] and v["bloqueante"]]

    titulo = extraer_titulo(contenido) or f"Cuento sobre {datos.tema}"

    promo_resp = ia.generar_texto(
        f"Escribí un texto de 2 o 3 oraciones para promocionar el cuento '{titulo}', "
        f"pensado para chicos de {datos.edad} años, sobre {datos.tema}. "
        "Terminá invitando a pedirlo con el botón de abajo.",
        SISTEMA_PROMO,
        tarea="promo",
        contexto={**contexto, "titulo": titulo},
    )
    promo = promo_resp.texto
    validaciones += validar_promo(promo)

    producto_id = db.insertar_producto(
        {
            "titulo": titulo,
            "tema": datos.tema,
            "edad": datos.edad,
            "valores": datos.valores,
            "contenido_md": contenido,
            "promo": promo,
            "precio": datos.precio if datos.precio is not None else config.precio_por_defecto,
            "estado": "pendiente",
            "validaciones": validaciones,
            "proveedor_ia": respuesta.proveedor,
        }
    )
    archivo = _guardar_archivo(producto_id, titulo, contenido)
    db.actualizar_producto(producto_id, {"archivo": archivo})
    return obtener(producto_id)


def obtener(producto_id: int) -> dict[str, Any]:
    producto = db.obtener_producto(producto_id)
    if producto is None:
        raise NoEncontrado(f"No existe el producto {producto_id}")
    producto["aprobable"] = not hay_bloqueos(producto["validaciones"])
    producto["link_pedido"] = link_pedido(producto_id)
    return producto


def listar(estado: str | None = None) -> list[dict[str, Any]]:
    estados_validos = {None, "pendiente", "aprobado", "publicado", "rechazado"}
    if estado not in estados_validos:
        raise ValidacionFallida(f"Estado inválido: {estado}")
    productos = db.listar_productos(estado)
    for p in productos:
        p["aprobable"] = not hay_bloqueos(p["validaciones"])
        p["promo_valida"] = not hay_bloqueos(validar_promo(p.get("promo")))
        p["link_pedido"] = link_pedido(p["id"])
    return productos


def editar(producto_id: int, cambios: EditarProducto) -> dict[str, Any]:
    """Edición humana del texto. Se vuelve a validar con las mismas reglas."""
    producto = obtener(producto_id)
    if producto["estado"] == "publicado":
        raise EstadoInvalido("No se puede editar un cuento ya publicado")
    datos = cambios.model_dump(exclude_none=True)
    if not datos:
        raise ValidacionFallida("No se envió ningún cambio")

    contenido = datos.get("contenido_md", producto["contenido_md"])
    promo = datos.get("promo", producto["promo"])
    datos["validaciones"] = validar_cuento(contenido, producto["edad"]) + validar_promo(promo)
    if "contenido_md" in datos:
        datos["titulo"] = extraer_titulo(contenido) or producto["titulo"]
        _guardar_archivo(producto_id, datos["titulo"], contenido)
        if producto.get("archivo") and producto["archivo"] != f"{producto_id:04d}-{_slug(datos['titulo'])}.md":
            (config.cuentos_dir / producto["archivo"]).unlink(missing_ok=True)
        datos["archivo"] = f"{producto_id:04d}-{_slug(datos['titulo'])}.md"
    # Una edición vuelve el producto a revisión
    datos["estado"] = "pendiente"
    db.actualizar_producto(producto_id, datos)
    return obtener(producto_id)


def revisar(producto_id: int, decision: str, nota: str | None) -> dict[str, Any]:
    """Supervisión humana: nada se publica sin esta aprobación."""
    producto = obtener(producto_id)
    if producto["estado"] not in {"pendiente", "rechazado"}:
        raise EstadoInvalido(f"El producto está '{producto['estado']}', no se puede revisar")
    if decision == "aprobar" and not producto["aprobable"]:
        fallas = [v["detalle"] for v in producto["validaciones"] if not v["ok"] and v["bloqueante"]]
        raise ValidacionFallida("No se puede aprobar, fallan reglas: " + "; ".join(fallas))
    nuevo_estado = "aprobado" if decision == "aprobar" else "rechazado"
    db.actualizar_producto(producto_id, {"estado": nuevo_estado, "nota_revision": nota})
    return obtener(producto_id)


def marcar_publicado(producto_id: int, telegram_msg_id: int | None) -> dict[str, Any]:
    producto = obtener(producto_id)
    if producto["estado"] != "aprobado":
        raise EstadoInvalido(f"Solo se publica lo aprobado (estado actual: {producto['estado']})")
    db.actualizar_producto(producto_id, {"estado": "publicado", "telegram_msg_id": telegram_msg_id})
    return obtener(producto_id)


def leer_archivo(producto_id: int) -> tuple[str, bytes]:
    producto = obtener(producto_id)
    ruta = config.cuentos_dir / (producto.get("archivo") or "")
    if not producto.get("archivo") or not ruta.exists():
        # Si el archivo se perdió, se reconstruye desde la base
        nombre = _guardar_archivo(producto_id, producto["titulo"], producto["contenido_md"])
        db.actualizar_producto(producto_id, {"archivo": nombre})
        ruta = config.cuentos_dir / nombre
    return ruta.name, ruta.read_bytes()


def link_pedido(producto_id: int) -> str | None:
    if not config.telegram_bot_username:
        return None
    return f"https://t.me/{config.telegram_bot_username.lstrip('@')}?start=prod_{producto_id}"