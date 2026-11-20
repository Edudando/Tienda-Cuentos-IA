"""Atención de mensajes: primero reglas, después IA.

Las reglas resuelven lo predecible (comandos /start y /catalogo) sin gastar
cuota de IA. La IA interpreta el texto libre: clasifica la intención y
redacta la respuesta. El código valida lo que la IA propone (por ejemplo,
que el producto exista y esté publicado) antes de que n8n actúe.
"""
from __future__ import annotations

import json
import re
from typing import Any

from app import db, ia
from app.errores import ServicioNoDisponible
from app.servicios import encargos

INTENCIONES = {"consulta", "pedido", "encargo", "otro"}

SISTEMA_ATENCION = (
    "Sos el asistente de una tienda de cuentos infantiles en Telegram. Respondés en "
    "español rioplatense, en no más de 3 oraciones, con amabilidad. Solo hablás de los "
    "cuentos del catálogo. Si el cliente quiere uno del catálogo, la intención es 'pedido'. "
    "Si el cliente pide que le escriban un cuento NUEVO sobre un tema, la intención es "
    "'encargo': en 'tema' poné de qué trata en pocas palabras (máximo 80 caracteres) y en "
    "'edad' la edad del chico (número de 3 a 12, o null si no la dijo). "
    "Respondés SOLO un JSON con las claves: intencion ('consulta', 'pedido', 'encargo' u 'otro'), "
    "producto_id (número del catálogo o null), tema (texto o null), edad (número o null) "
    "y respuesta (texto para el cliente)."
)

RESPUESTA_ENCARGO_INCOMPLETO = (
    "¡Te escribimos un cuento nuevo! Contame en un solo mensaje de qué querés que trate y "
    "para qué edad (de 3 a 12 años). Por ejemplo: «quiero un cuento sobre un dinosaurio "
    "que aprende a nadar, para 5 años»."
)

RESPUESTA_ENCARGO_REPETIDO = (
    "Ya tenés un cuento encargado que estamos revisando. Cuando esté listo te aviso por "
    "acá y después podés pedirnos otro."
)

RESPUESTA_SIN_IA = (
    "En este momento no puedo responder consultas automáticas. Escribí /catalogo para "
    "ver los cuentos o tocá el botón 'Pedir' en el canal."
)


def _catalogo() -> list[dict[str, Any]]:
    return [
        {"id": p["id"], "titulo": p["titulo"], "edad": p["edad"], "tema": p["tema"], "precio": p["precio"]}
        for p in db.listar_productos("publicado")
    ]


def _texto_catalogo(catalogo: list[dict[str, Any]]) -> str:
    if not catalogo:
        return "Todavía no hay cuentos publicados. ¡Volvé pronto!"
    lineas = ["Estos son nuestros cuentos:"]
    for c in catalogo:
        precio = "gratis" if c["precio"] == 0 else f"${c['precio']:,.0f}"
        lineas.append(f"• N° {c['id']}: {c['titulo']} ({c['edad']} años, {precio})")
    lineas.append("Para pedir uno escribí, por ejemplo: quiero el N° " + str(catalogo[0]["id"]))
    return "\n".join(lineas)


def _por_reglas(texto: str, catalogo: list[dict[str, Any]]) -> dict[str, Any] | None:
    limpio = texto.strip().lower()

    coincidencia = re.match(r"^/start\s+prod_(\d+)$", limpio)
    if coincidencia:  # deep link del botón del canal
        return {"intencion": "pedido", "producto_id": int(coincidencia.group(1)), "respuesta": "¡Recibimos tu pedido!"}

    if limpio in {"/start", "hola", "/ayuda"}:
        return {
            "intencion": "consulta",
            "producto_id": None,
            "respuesta": "¡Hola! Somos una tienda de cuentos infantiles creados con IA y revisados por personas.\n"
            + _texto_catalogo(catalogo),
        }

    if limpio in {"/catalogo", "catalogo", "catálogo"}:
        return {"intencion": "consulta", "producto_id": None, "respuesta": _texto_catalogo(catalogo)}

    coincidencia = re.search(r"(?:n°|nº|nro\.?|numero|número|#)\s*(\d+)", limpio)
    if coincidencia and any(p in limpio for p in ("quiero", "pedir", "pido", "comprar")):
        return {"intencion": "pedido", "producto_id": int(coincidencia.group(1)), "respuesta": "¡Recibimos tu pedido!"}
    return None


def _por_ia(texto: str, catalogo: list[dict[str, Any]]) -> tuple[dict[str, Any], str]:
    prompt = (
        f"Catálogo disponible (JSON): {json.dumps(catalogo, ensure_ascii=False)}\n\n"
        f"Mensaje del cliente: {texto}"
    )
    respuesta = ia.generar_texto(
        prompt, SISTEMA_ATENCION, json_mode=True, tarea="clasificar", contexto={"texto": texto, "catalogo": catalogo}
    )
    datos = ia.extraer_json(respuesta.texto)
    return datos, respuesta.proveedor


def _validar_propuesta_ia(datos: dict[str, Any], catalogo: list[dict[str, Any]]) -> dict[str, Any]:
    """El código no confía ciegamente en la IA."""
    intencion = datos.get("intencion") if datos.get("intencion") in INTENCIONES else "otro"
    if intencion == "encargo":
        cuento = encargos.validar_datos(datos.get("tema"), datos.get("edad"))
        if cuento is None:
            # Falta el tema o la edad (o están fuera de rango): se piden de nuevo
            return {"intencion": "consulta", "producto_id": None, "respuesta": RESPUESTA_ENCARGO_INCOMPLETO}
        return {
            "intencion": "encargo",
            "producto_id": None,
            "respuesta": "",
            "encargo": {"tema": cuento.tema, "edad": cuento.edad},
        }
    respuesta = str(datos.get("respuesta") or "").strip()[:1000] or RESPUESTA_SIN_IA
    producto_id = datos.get("producto_id")
    ids = {c["id"] for c in catalogo}
    try:
        producto_id = int(producto_id) if producto_id is not None else None
    except (TypeError, ValueError):
        producto_id = None
    if intencion == "pedido" and producto_id not in ids:
        # La IA detectó intención de compra pero no un producto válido: se pide aclaración
        intencion, producto_id = "consulta", None
        respuesta = "¿Qué cuento te gustaría? " + _texto_catalogo(catalogo)
    return {"intencion": intencion, "producto_id": producto_id, "respuesta": respuesta}


def atender(chat_id: str, usuario: str | None, texto: str) -> dict[str, Any]:
    catalogo = _catalogo()
    resultado = _por_reglas(texto, catalogo)
    origen, proveedor = "regla", None

    if resultado and resultado["intencion"] == "pedido" and resultado["producto_id"] not in {c["id"] for c in catalogo}:
        resultado = {
            "intencion": "consulta",
            "producto_id": None,
            "respuesta": "Ese cuento no está disponible. " + _texto_catalogo(catalogo),
        }

    if resultado is None:
        origen = "ia"
        try:
            datos, proveedor = _por_ia(texto, catalogo)
            resultado = _validar_propuesta_ia(datos, catalogo)
        except (ServicioNoDisponible, ValueError):
            resultado = {"intencion": "otro", "producto_id": None, "respuesta": RESPUESTA_SIN_IA}
            origen, proveedor = "regla", "sin_ia"

    if resultado["intencion"] == "encargo":
        resultado = _aceptar_encargo(chat_id, resultado)

    consulta_id = db.insertar_consulta(
        {
            "chat_id": chat_id,
            "usuario": usuario,
            "texto": texto,
            "intencion": resultado["intencion"],
            "producto_id": resultado["producto_id"],
            "respuesta": resultado["respuesta"],
            "origen": origen,
            "proveedor_ia": proveedor,
        }
    )
    return {"consulta_id": consulta_id, **resultado, "origen": origen, "proveedor_ia": proveedor}


def _aceptar_encargo(chat_id: str, resultado: dict[str, Any]) -> dict[str, Any]:
    """Reserva el encargo. La generación la dispara main.py en segundo plano."""
    if not encargos.reservar(chat_id):
        return {"intencion": "consulta", "producto_id": None, "respuesta": RESPUESTA_ENCARGO_REPETIDO}
    datos = resultado["encargo"]
    return {
        **resultado,
        "respuesta": (
            f"¡Gracias! Vamos a escribir un cuento sobre {datos['tema']} para chicos de {datos['edad']} "
            "años. Antes de publicarlo lo revisa una persona, y te aviso por acá cuando esté aprobado."
        ),
    }


def listar(limite: int = 100) -> list[dict[str, Any]]:
    return db.listar_consultas(limite)


def estadisticas() -> dict[str, Any]:
    prod = db.contar("productos", "estado")
    ped = db.contar("pedidos", "estado")
    cons = db.contar("consultas", "origen")
    return {
        "productos": prod,
        "pedidos": ped,
        "consultas_por_origen": cons,
        "pendientes_revision": prod.get("pendiente", 0),
        "aprobados_sin_publicar": prod.get("aprobado", 0),
        "pagos_por_validar": ped.get("comprobante_recibido", 0),
        "entregados": ped.get("entregado", 0),
        "hay_pendientes": bool(prod.get("pendiente", 0) or ped.get("comprobante_recibido", 0)),
    }