"""Modelos de entrada (Pydantic). FastAPI responde 422 si no se cumplen."""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field, field_validator


class GenerarCuento(BaseModel):
    tema: str = Field(min_length=3, max_length=80, examples=["un dragón que tenía miedo a la oscuridad"])
    edad: int = Field(ge=3, le=12, description="Edad lectora objetivo (3 a 12)")
    valores: str | None = Field(default=None, max_length=80, examples=["la valentía"])
    personaje: str | None = Field(default=None, max_length=40, examples=["Tomi"])
    precio: float | None = Field(default=None, ge=0, le=100000)

    @field_validator("tema", "valores", "personaje")
    @classmethod
    def sin_espacios_vacios(cls, v: str | None) -> str | None:
        if v is not None and not v.strip():
            raise ValueError("No puede estar vacío")
        return v.strip() if v else v


class EditarProducto(BaseModel):
    contenido_md: str | None = Field(default=None, min_length=50)
    promo: str | None = Field(default=None, min_length=10)
    precio: float | None = Field(default=None, ge=0, le=100000)


class Revision(BaseModel):
    decision: Literal["aprobar", "rechazar"]
    nota: str | None = Field(default=None, max_length=300)


class MarcarPublicado(BaseModel):
    telegram_msg_id: int | None = None


class NuevaConsulta(BaseModel):
    chat_id: str = Field(min_length=1)
    usuario: str | None = None
    texto: str = Field(min_length=1, max_length=2000)


class NuevoPedido(BaseModel):
    producto_id: int = Field(gt=0)
    chat_id: str = Field(min_length=1)
    usuario: str | None = None


class CambioEstadoPedido(BaseModel):
    estado: Literal["esperando_pago"]


class Comprobante(BaseModel):
    chat_id: str = Field(min_length=1)
    file_id: str = Field(min_length=1)


class ValidacionPago(BaseModel):
    accion: Literal["validar", "rechazar"]
    nota: str | None = Field(default=None, max_length=300)