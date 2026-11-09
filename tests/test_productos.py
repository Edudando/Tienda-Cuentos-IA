"""Pruebas de la Etapa 5: cliente de Telegram y ciclo de vida del cuento.

Ejecutar:  pytest -q
Se prueban los servicios directamente, sin FastAPI. Telegram se reemplaza
por respuestas falsas y la IA por el proveedor "mock".
"""
import httpx
import pytest

from app import db, ia, telegram_client
from app.config import config
from app.errores import EstadoInvalido, NoEncontrado, ServicioNoDisponible, ValidacionFallida
from app.modelos import EditarProducto, GenerarCuento
from app.servicios import productos


@pytest.fixture()
def tienda(tmp_path, monkeypatch):
    """Base vacía, IA simulada y un usuario de bot ficticio."""
    monkeypatch.setattr(config, "data_dir", tmp_path)
    monkeypatch.setattr(config, "ia_proveedores", ["mock"])
    monkeypatch.setattr(config, "telegram_bot_username", "CuentosDemoBot")
    db.inicializar()
    return tmp_path


def _generar(tema="un dragón miedoso", edad=5, **extra):
    return productos.generar(GenerarCuento(tema=tema, edad=edad, **extra))


# ------------------------------------------------------------------ Telegram
def test_telegram_sin_token_es_503(monkeypatch):
    monkeypatch.setattr(config, "telegram_token", "")
    with pytest.raises(ServicioNoDisponible) as info:
        telegram_client.enviar_mensaje("123", "hola")
    assert info.value.status_code == 503


def test_telegram_envia_y_devuelve_el_resultado(monkeypatch):
    monkeypatch.setattr(config, "telegram_token", "token-falso")
    enviados = []

    def post_falso(url, **kwargs):
        enviados.append((url, kwargs["json"]))
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}},
                              request=httpx.Request("POST", url))

    monkeypatch.setattr(telegram_client.httpx, "post", post_falso)
    assert telegram_client.enviar_mensaje("123", "hola") == {"message_id": 7}
    url, cuerpo = enviados[0]
    assert url.endswith("/sendMessage")
    assert cuerpo == {"chat_id": "123", "text": "hola"}


def test_telegram_rechaza_el_envio(monkeypatch):
    monkeypatch.setattr(config, "telegram_token", "token-falso")
    monkeypatch.setattr(
        telegram_client.httpx, "post",
        lambda url, **kw: httpx.Response(400, json={"ok": False, "description": "chat not found"},
                                         request=httpx.Request("POST", url)),
    )
    with pytest.raises(ServicioNoDisponible) as info:
        telegram_client.enviar_mensaje("999", "hola")
    assert "chat not found" in info.value.mensaje


# ------------------------------------------------------- generar un cuento
def test_generar_deja_el_cuento_pendiente_y_guardado(tienda):
    p = _generar(personaje="Tomi", precio=1500)
    assert p["estado"] == "pendiente"
    assert p["proveedor_ia"] == "mock"
    assert p["titulo"] == "Tomi y un dragón miedoso"
    assert p["precio"] == 1500
    assert p["aprobable"] is True
    assert p["promo"]                                   # la IA también escribió la promo
    assert (tienda / "cuentos" / p["archivo"]).exists()  # y quedó el .md en disco
    assert p["link_pedido"] == f"https://t.me/CuentosDemoBot?start=prod_{p['id']}"


def test_nombre_de_archivo_sin_tildes_ni_espacios():
    assert productos._slug("¡El Dragón Miedoso!") == "el-dragon-miedoso"


def test_si_la_ia_falla_las_reglas_reintenta_con_correcciones(tienda, monkeypatch):
    prompts = []
    original = ia.generar_texto

    def ia_falsa(prompt, sistema, **kwargs):
        if kwargs.get("tarea") == "cuento":
            prompts.append(prompt)
            if len(prompts) == 1:
                return ia.RespuestaIA("Cuento sin título y cortito.", "mock")
        return original(prompt, sistema, **kwargs)

    monkeypatch.setattr(ia, "generar_texto", ia_falsa)
    p = _generar()
    assert len(prompts) == 2                       # hubo un segundo intento...
    assert "corregilo" in prompts[1]               # ...con las fallas del primero
    assert "Falta una línea '# Título'" in prompts[1]
    assert p["aprobable"] is True


# ------------------------------------------------ revisión y publicación
def test_ciclo_completo_pendiente_aprobado_publicado(tienda):
    p = _generar()
    aprobado = productos.revisar(p["id"], "aprobar", "Muy lindo")
    assert aprobado["estado"] == "aprobado"
    assert aprobado["nota_revision"] == "Muy lindo"
    publicado = productos.marcar_publicado(p["id"], telegram_msg_id=42)
    assert publicado["estado"] == "publicado"
    assert publicado["telegram_msg_id"] == 42


def test_no_se_publica_sin_aprobacion(tienda):
    p = _generar()
    with pytest.raises(EstadoInvalido):            # 409
        productos.marcar_publicado(p["id"], None)


def test_no_se_aprueba_si_fallan_reglas(tienda):
    p = _generar()
    malo = "# Título\n\nEste texto tiene la palabra sangre y es muy corto.\n\nFin\n\nchau " * 3
    editado = productos.editar(p["id"], EditarProducto(contenido_md=malo))
    assert editado["aprobable"] is False
    with pytest.raises(ValidacionFallida) as info:  # 422 de negocio
        productos.revisar(p["id"], "aprobar", None)
    assert "sangre" in info.value.mensaje


def test_rechazar_siempre_se_puede(tienda):
    p = _generar()
    assert productos.revisar(p["id"], "rechazar", "No me convence")["estado"] == "rechazado"


def test_editar_vuelve_a_pendiente_y_no_se_edita_lo_publicado(tienda):
    p = _generar()
    productos.revisar(p["id"], "aprobar", None)
    editado = productos.editar(p["id"], EditarProducto(precio=500))
    assert editado["estado"] == "pendiente"        # una edición vuelve a revisión
    productos.revisar(p["id"], "aprobar", None)
    productos.marcar_publicado(p["id"], None)
    with pytest.raises(EstadoInvalido):
        productos.editar(p["id"], EditarProducto(precio=800))


def test_editar_sin_cambios_es_422(tienda):
    p = _generar()
    with pytest.raises(ValidacionFallida):
        productos.editar(p["id"], EditarProducto())


# ------------------------------------------------------------- consultas
def test_producto_inexistente_es_404(tienda):
    with pytest.raises(NoEncontrado):
        productos.obtener(9999)


def test_listar_con_estado_invalido_es_422(tienda):
    with pytest.raises(ValidacionFallida):
        productos.listar("borrador")


def test_el_archivo_se_reconstruye_si_se_borro(tienda):
    p = _generar()
    (tienda / "cuentos" / p["archivo"]).unlink()
    nombre, contenido = productos.leer_archivo(p["id"])
    assert nombre == p["archivo"]
    assert contenido.decode("utf-8") == p["contenido_md"]

    