"""Cliente de IA con fallback entre proveedores gratuitos.

Orden por defecto (variable IA_PROVEEDORES): gemini -> groq.
Si un proveedor falla por cuota (HTTP 429), error del servidor, timeout,
respuesta sin texto o falta de clave, se pasa al siguiente y se registra
cuál respondió.

Ollama (modelo local) se descartó: las computadoras del grupo no tienen
potencia suficiente para correrlo (ver docs/bitacora_ia.md).

El proveedor "mock" es una simulación determinística, sin IA real. Sirve
para correr los tests y para demostrar el sistema sin internet. Siempre
queda registrado como "mock" para que nunca se confunda con IA real.
"""
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from typing import Any

import httpx

from app.config import config
from app.errores import ServicioNoDisponible

log = logging.getLogger("ia")


class ProveedorNoDisponible(Exception):
    """El proveedor no está configurado o falló de forma recuperable."""


@dataclass
class RespuestaIA:
    texto: str
    proveedor: str


# ------------------------------------------------------------ proveedores
def _gemini(prompt: str, sistema: str, json_mode: bool) -> str:
    if not config.gemini_api_key:
        raise ProveedorNoDisponible("Falta GEMINI_API_KEY")
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{config.gemini_model}:generateContent"
    cuerpo: dict[str, Any] = {
        "systemInstruction": {"parts": [{"text": sistema}]},
        "contents": [{"role": "user", "parts": [{"text": prompt}]}],
        "generationConfig": {"temperature": 0.8},
    }
    if json_mode:
        cuerpo["generationConfig"]["responseMimeType"] = "application/json"
    r = httpx.post(url, params={"key": config.gemini_api_key}, json=cuerpo, timeout=config.ia_timeout)
    _verificar_http(r, "gemini")
    try:
        partes = r.json()["candidates"][0]["content"]["parts"]
        # Gemini puede dividir la respuesta en varias partes: se unen todas
        # (y se ignoran las de "razonamiento" interno, marcadas con thought)
        return "".join(p.get("text", "") for p in partes if not p.get("thought"))
    except (KeyError, IndexError) as exc:  # p. ej. respuesta bloqueada por filtros
        raise ProveedorNoDisponible(f"gemini devolvió una respuesta sin texto: {r.text[:200]}") from exc


def _groq(prompt: str, sistema: str, json_mode: bool) -> str:
    if not config.groq_api_key:
        raise ProveedorNoDisponible("Falta GROQ_API_KEY")
    cuerpo: dict[str, Any] = {
        "model": config.groq_model,
        "messages": [{"role": "system", "content": sistema}, {"role": "user", "content": prompt}],
        "temperature": 0.8,
    }
    if json_mode:
        cuerpo["response_format"] = {"type": "json_object"}
    r = httpx.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {config.groq_api_key}"},
        json=cuerpo,
        timeout=config.ia_timeout,
    )
    _verificar_http(r, "groq")
    try:
        return r.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:  # respuesta con otro formato
        raise ProveedorNoDisponible(f"groq devolvió una respuesta sin texto: {r.text[:200]}") from exc


def _verificar_http(r: httpx.Response, nombre: str) -> None:
    if r.status_code == 429:
        raise ProveedorNoDisponible(f"{nombre}: límite de uso alcanzado (429)")
    if r.status_code >= 500:
        raise ProveedorNoDisponible(f"{nombre}: error del servidor ({r.status_code})")
    if r.status_code >= 400:
        raise ProveedorNoDisponible(f"{nombre}: error {r.status_code}: {r.text[:200]}")


# --------------------------------------------------------- simulación (mock)
def _mock(prompt: str, sistema: str, json_mode: bool, tarea: str, contexto: dict[str, Any]) -> str:
    if tarea == "cuento":
        tema = contexto.get("tema", "la amistad")
        personaje = contexto.get("personaje") or "Lucía"
        valores = contexto.get("valores") or "la amistad"
        parrafo = (
            f"{personaje} vivía en un pueblo pequeño, rodeado de árboles altos y de vecinos que se "
            f"saludaban cada mañana. Un día descubrió algo relacionado con {tema} que cambió su forma "
            f"de mirar el mundo. Al principio tuvo miedo, pero respiró hondo y decidió seguir adelante. "
        )
        cuerpo = "\n\n".join([parrafo] * 6)
        return (
            f"# {personaje} y {tema}\n\n{cuerpo}\n\n"
            f"Al final del día, {personaje} entendió que {valores} se construye con pequeños gestos. "
            f"Y desde entonces, cada vez que alguien necesitaba ayuda, sabía exactamente qué hacer.\n\n"
            f"**Fin.**"
        )
    if tarea == "promo":
        titulo = contexto.get("titulo", "un cuento nuevo")
        return (
            f"Nuevo cuento: \"{titulo}\". Una historia para leer en familia, pensada para "
            f"chicos de {contexto.get('edad', 6)} años. Pedilo gratis con el botón de abajo."
        )
    if tarea == "clasificar":
        texto = contexto.get("texto", "").lower()
        quiere = any(p in texto for p in ("quiero", "comprar", "pedir", "lo llevo", "me lo"))
        catalogo = contexto.get("catalogo", [])
        producto_id = catalogo[0]["id"] if (quiere and catalogo) else None
        return json.dumps(
            {
                "intencion": "pedido" if producto_id else "consulta",
                "producto_id": producto_id,
                "respuesta": (
                    "¡Genial! Ya te preparo el pedido."
                    if producto_id
                    else "Tenemos cuentos para distintas edades. Escribí /catalogo para verlos."
                ),
            },
            ensure_ascii=False,
        )
    return "Respuesta simulada."


# -------------------------------------------------------------- orquestador
_PROVEEDORES = {"gemini": _gemini, "groq": _groq}


def generar_texto(
    prompt: str,
    sistema: str,
    *,
    json_mode: bool = False,
    tarea: str = "",
    contexto: dict[str, Any] | None = None,
) -> RespuestaIA:
    """Pide texto a la IA recorriendo los proveedores en orden.

    Lanza ServicioNoDisponible si ninguno respondió.
    """
    errores: list[str] = []
    for nombre in config.ia_proveedores:
        try:
            if nombre == "mock":
                texto = _mock(prompt, sistema, json_mode, tarea, contexto or {})
            elif nombre in _PROVEEDORES:
                texto = _PROVEEDORES[nombre](prompt, sistema, json_mode)
            else:
                errores.append(f"{nombre}: proveedor desconocido")
                continue
            if not texto or not texto.strip():
                raise ProveedorNoDisponible(f"{nombre}: respuesta vacía")
            log.info("IA respondió con %s (tarea=%s)", nombre, tarea)
            return RespuestaIA(texto=texto.strip(), proveedor=nombre)
        except (ProveedorNoDisponible, httpx.TimeoutException, httpx.TransportError) as exc:
            log.warning("Fallback: %s", exc)
            errores.append(str(exc))
    raise ServicioNoDisponible("Ningún proveedor de IA respondió. Detalle: " + " | ".join(errores))


def extraer_json(texto: str) -> dict[str, Any]:
    """Convierte la respuesta de la IA en dict, tolerando bloques ```json."""
    limpio = re.sub(r"^```(?:json)?\s*|\s*```$", "", texto.strip())
    inicio, fin = limpio.find("{"), limpio.rfind("}")
    if inicio == -1 or fin == -1:
        raise ValueError("La IA no devolvió un JSON")
    return json.loads(limpio[inicio : fin + 1])