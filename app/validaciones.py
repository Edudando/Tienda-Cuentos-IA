"""Reglas de validación programadas (no IA).

Cada regla devuelve {"regla", "ok", "detalle", "bloqueante"}. Las reglas
bloqueantes impiden aprobar el producto. Así la interfaz puede mostrar por
separado lo que decidió el código y lo que generó la IA.
"""
from __future__ import annotations

import re
from typing import Any

# Rangos de palabras recomendados según la edad lectora
RANGOS_PALABRAS = [
    (3, 5, 120, 600),
    (6, 8, 200, 900),
    (9, 12, 300, 1400),
]

PALABRAS_PROHIBIDAS = {
    "matar", "muerte", "sangre", "arma", "pistola", "droga", "alcohol",
    "odio", "estúpido", "idiota", "suicidio", "sexo",
}

LARGO_MAX_PROMO = 500


def rango_para_edad(edad: int) -> tuple[int, int]:
    for desde, hasta, minimo, maximo in RANGOS_PALABRAS:
        if desde <= edad <= hasta:
            return minimo, maximo
    raise ValueError(f"Edad fuera de rango: {edad}")


def contar_palabras(texto: str) -> int:
    return len(re.findall(r"\b\w+\b", texto))


def extraer_titulo(markdown: str) -> str | None:
    for linea in markdown.splitlines():
        if linea.strip().startswith("# "):
            return linea.strip()[2:].strip() or None
    return None


def _prohibidas_en(texto: str) -> list[str]:
    palabras = set(re.findall(r"\b\w+\b", texto.lower()))
    return sorted(palabras & PALABRAS_PROHIBIDAS)


def _regla(nombre: str, ok: bool, detalle: str, bloqueante: bool = True) -> dict[str, Any]:
    return {"regla": nombre, "ok": ok, "detalle": detalle, "bloqueante": bloqueante}


def validar_cuento(markdown: str, edad: int) -> list[dict[str, Any]]:
    resultados = []

    titulo = extraer_titulo(markdown)
    resultados.append(
        _regla("titulo", titulo is not None, f"Título: {titulo}" if titulo else "Falta una línea '# Título'")
    )

    palabras = contar_palabras(markdown)
    minimo, maximo = rango_para_edad(edad)
    resultados.append(
        _regla(
            "largo",
            minimo <= palabras <= maximo,
            f"{palabras} palabras (rango para {edad} años: {minimo}-{maximo})",
        )
    )

    prohibidas = _prohibidas_en(markdown)
    resultados.append(
        _regla(
            "vocabulario",
            not prohibidas,
            "Sin palabras prohibidas" if not prohibidas else f"Contiene: {', '.join(prohibidas)}",
        )
    )

    tiene_links = bool(re.search(r"https?://|www\.", markdown))
    resultados.append(
        _regla("sin_enlaces", not tiene_links, "Sin enlaces" if not tiene_links else "El cuento contiene enlaces")
    )

    parrafos = [p for p in markdown.split("\n\n") if p.strip()]
    resultados.append(
        _regla(
            "estructura",
            len(parrafos) >= 3,
            f"{len(parrafos)} párrafos",
            bloqueante=False,  # advertencia: no impide aprobar
        )
    )
    return resultados


def validar_promo(promo: str | None) -> list[dict[str, Any]]:
    if not promo or not promo.strip():
        return [_regla("promo", False, "Falta el texto promocional")]
    prohibidas = _prohibidas_en(promo)
    largo_ok = len(promo) <= LARGO_MAX_PROMO
    # si el último carácter es una letra o un número, la promo quedó cortada
    # (una promo completa termina en punto, signo de exclamación/pregunta o emoji)
    completa = not promo.rstrip()[-1].isalnum()
    return [
        _regla("promo_largo", largo_ok, f"{len(promo)} caracteres (máx. {LARGO_MAX_PROMO})"),
        _regla(
            "promo_vocabulario",
            not prohibidas,
            "Sin palabras prohibidas" if not prohibidas else f"Contiene: {', '.join(prohibidas)}",
        ),
        _regla(
            "promo_completa",
            completa,
            "La promo termina bien" if completa else "La promo parece cortada (no termina en punto, signo o emoji)",
        ),
    ]


def hay_bloqueos(validaciones: list[dict[str, Any]]) -> bool:
    return any(not v["ok"] and v["bloqueante"] for v in validaciones)