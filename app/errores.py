"""Excepciones de dominio.

La lógica de negocio lanza estas excepciones y `main.py` las traduce a
respuestas HTTP. Así los servicios no dependen de FastAPI.
"""


class ErrorDominio(Exception):
    """Base de todos los errores del sistema."""

    status_code = 400

    def __init__(self, mensaje: str):
        super().__init__(mensaje)
        self.mensaje = mensaje


class NoEncontrado(ErrorDominio):
    status_code = 404


class EstadoInvalido(ErrorDominio):
    """La operación no corresponde al estado actual (p. ej. aprobar algo ya publicado)."""

    status_code = 409


class ValidacionFallida(ErrorDominio):
    status_code = 422


class ServicioNoDisponible(ErrorDominio):
    """Un servicio externo (IA, Telegram) no respondió."""

    status_code = 503