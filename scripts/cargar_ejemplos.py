"""Carga los cuentos de ejemplo en la base (datos ficticios para la demo).

Uso:
    python -m scripts.cargar_ejemplos              # quedan 'aprobado' (n8n los publica)
    python -m scripts.cargar_ejemplos --pendiente  # quedan para revisar en Streamlit

En Docker:
    docker compose exec api python -m scripts.cargar_ejemplos
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app import db
from app.config import config
from app.servicios.productos import _guardar_archivo
from app.validaciones import extraer_titulo, validar_cuento, validar_promo

EJEMPLOS = Path(__file__).resolve().parent.parent / "data" / "ejemplos"


def main() -> None:
    estado = "pendiente" if "--pendiente" in sys.argv else "aprobado"
    db.inicializar()
    for item in json.loads((EJEMPLOS / "productos_ejemplo.json").read_text(encoding="utf-8")):
        contenido = (EJEMPLOS / item["archivo_ejemplo"]).read_text(encoding="utf-8")
        titulo = extraer_titulo(contenido)
        if any(p["titulo"] == titulo for p in db.listar_productos()):
            print(f"Ya existe: {titulo}")
            continue
        validaciones = validar_cuento(contenido, item["edad"]) + validar_promo(item["promo"])
        producto_id = db.insertar_producto(
            {
                "titulo": titulo,
                "tema": item["tema"],
                "edad": item["edad"],
                "valores": item["valores"],
                "contenido_md": contenido,
                "promo": item["promo"],
                "precio": item["precio"],
                "estado": estado,
                "validaciones": validaciones,
                "proveedor_ia": "ejemplo",
            }
        )
        db.actualizar_producto(producto_id, {"archivo": _guardar_archivo(producto_id, titulo, contenido)})
        print(f"Cargado N° {producto_id}: {titulo} ({estado})")
    print(f"Base: {config.db_path}")


if __name__ == "__main__":
    main()