"""Panel de administración de la Tienda de Cuentos IA (Streamlit).

Ejecutar en local:  streamlit run ui/app.py
En Docker:          http://localhost:8501

Seis pestañas: Resumen, Generar, Revisión, Catálogo, Pedidos y pagos, Consultas.
El panel separa siempre lo que decidió el CÓDIGO (validaciones por reglas)
de lo que escribió la IA (contenido generado).
"""
from __future__ import annotations

import sys
from pathlib import Path

import altair as alt
import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
import cliente_api as api  # noqa: E402
from cliente_api import ErrorAPI  # noqa: E402

st.set_page_config(page_title="Tienda de Cuentos IA · Panel", page_icon="📚", layout="wide")

ETIQUETA_ESTADO = {
    "pendiente": "🟡 pendiente",
    "aprobado": "🔵 aprobado",
    "publicado": "🟢 publicado",
    "rechazado": "🔴 rechazado",
    "nuevo": "⚪ nuevo",
    "esperando_pago": "🟡 esperando pago",
    "comprobante_recibido": "🟠 comprobante recibido",
    "pagado": "🔵 pagado",
    "entregado": "🟢 entregado",
}


# ------------------------------------------------------------ utilidades
def llamar(funcion, *args, exito: str | None = None, **kwargs):
    """Ejecuta una llamada a la API y muestra el error traducido si falla."""
    try:
        resultado = funcion(*args, **kwargs)
    except ErrorAPI as exc:
        st.error(exc.mensaje)
        return None
    if exito:
        st.session_state["aviso"] = exito
    return resultado


def precio_texto(precio: float) -> str:
    return "Gratis" if not precio else f"${precio:,.0f}".replace(",", ".")


def encargado_por(p: dict) -> str | None:
    """'@usuario' si el cuento lo encargó un cliente por el bot; None si lo generó el panel."""
    if not p.get("solicitante_chat_id"):
        return None
    usuario = (p.get("solicitante_usuario") or "").strip()
    if not usuario:
        return "un cliente sin nombre de usuario"
    # El relay manda el @usuario de Telegram, o el nombre si la persona no tiene usuario
    return usuario if " " in usuario else "@" + usuario.lstrip("@")


def mostrar_validaciones(validaciones: list[dict]) -> None:
    if not validaciones:
        st.caption("Sin validaciones registradas.")
        return
    for v in validaciones:
        if v["ok"]:
            icono = "✅"
        elif v.get("bloqueante"):
            icono = "⛔"
        else:
            icono = "⚠️"
        st.markdown(f"{icono} **{v.get('regla', '')}** — {v.get('detalle', '')}")


def grafico(conteo: dict, etiqueta: str) -> None:
    """Barras horizontales con números enteros (con pocos datos, un gráfico vertical se ve gigante)."""
    df = pd.DataFrame({"estado": [ETIQUETA_ESTADO.get(k, k) for k in conteo], etiqueta: list(conteo.values())})
    base = alt.Chart(df).encode(
        x=alt.X(f"{etiqueta}:Q", axis=None, scale=alt.Scale(domain=[0, max(df[etiqueta]) * 1.15])),
        y=alt.Y("estado:N", title=None, sort="-x"),
        tooltip=["estado", f"{etiqueta}:Q"],
    )
    barras = base.mark_bar(cornerRadiusEnd=4, size=22)
    numeros = base.mark_text(align="left", dx=6, fontSize=14, fontWeight="bold").encode(text=f"{etiqueta}:Q")
    chart = (barras + numeros).properties(height=48 * len(df) + 10)
    st.altair_chart(chart, use_container_width=True)


def recargar(mensaje: str | None = None) -> None:
    if mensaje:
        st.session_state["aviso"] = mensaje
    st.rerun()


# ------------------------------------------------------------ encabezado
st.title("📚 Tienda de Cuentos IA")

try:
    salud = api.salud()
    col1, col2, col3 = st.columns(3)
    col1.success("API conectada")
    col2.info("IA: " + " → ".join(salud.get("proveedores_ia", [])))
    if salud.get("telegram_configurado"):
        col3.success("Telegram configurado")
    else:
        col3.warning("Telegram sin configurar (la entrega dará 503)")
except ErrorAPI as exc:
    st.error(exc.mensaje)
    st.info("Revisá que el contenedor de la API esté levantado: `docker compose ps` y `docker compose logs api`.")
    st.stop()

if aviso := st.session_state.pop("aviso", None):
    st.toast(aviso, icon="✅")

tabs = st.tabs(["📊 Resumen", "✨ Generar", "📝 Revisión", "📖 Catálogo", "💳 Pedidos y pagos", "💬 Consultas"])


# ============================================================ 1 · Resumen
with tabs[0]:
    est = llamar(api.estadisticas)
    if est:
        c = st.columns(4)
        c[0].metric("Pendientes de revisión", est["pendientes_revision"])
        c[1].metric("Aprobados sin publicar", est["aprobados_sin_publicar"])
        c[2].metric("Pagos por validar", est["pagos_por_validar"])
        c[3].metric("Entregados", est["entregados"])

        if est["hay_pendientes"]:
            st.warning("Hay trabajo humano pendiente: cuentos para revisar o pagos para validar.")
        else:
            st.success("No hay tareas pendientes.")

        izq, centro, der = st.columns(3)
        with izq:
            st.subheader("Cuentos por estado")
            if est["productos"]:
                grafico(est["productos"], "cuentos")
            else:
                st.caption("Todavía no hay cuentos.")
        with centro:
            st.subheader("Pedidos por estado")
            if est["pedidos"]:
                grafico(est["pedidos"], "pedidos")
            else:
                st.caption("Todavía no hay pedidos.")
        with der:
            st.subheader("Consultas: reglas vs IA")
            if est["consultas_por_origen"]:
                grafico(est["consultas_por_origen"], "consultas")
            else:
                st.caption("Todavía no hay consultas.")
    if st.button("🔄 Actualizar", key="refrescar_resumen"):
        st.rerun()


# ============================================================ 2 · Generar
with tabs[1]:
    st.subheader("Generar un cuento nuevo con IA")
    st.caption("La IA escribe el cuento y el texto promocional. Después las reglas lo validan y queda **pendiente** "
               "hasta que una persona lo apruebe en la pestaña Revisión.")
    with st.form("form_generar"):
        tema = st.text_input("Tema *", placeholder="un dragón que tenía miedo a la oscuridad")
        c1, c2, c3 = st.columns(3)
        edad = c1.number_input("Edad lectora *", min_value=3, max_value=12, value=5, step=1)
        personaje = c2.text_input("Personaje (opcional)", placeholder="Tomi")
        precio = c3.number_input("Precio en $ (0 = gratis)", min_value=0, max_value=100000, value=0, step=100)
        valores = st.text_input("Valores a transmitir (opcional)", placeholder="la valentía")
        enviado = st.form_submit_button("✨ Generar", type="primary")

    if enviado:
        datos = {"tema": tema, "edad": int(edad), "precio": float(precio)}
        if personaje.strip():
            datos["personaje"] = personaje
        if valores.strip():
            datos["valores"] = valores
        with st.spinner("La IA está escribiendo… puede tardar hasta un minuto."):
            nuevo = llamar(api.generar, datos)
        if nuevo:
            st.success(f"Cuento N° {nuevo['id']} generado por **{nuevo['proveedor_ia']}**. Quedó pendiente de revisión.")
            izq, der = st.columns(2)
            with izq:
                st.markdown("##### ⚙️ Validaciones por reglas (código)")
                mostrar_validaciones(nuevo["validaciones"])
            with der:
                st.markdown("##### 🤖 Contenido generado por IA")
                st.markdown(nuevo["contenido_md"])
                st.info(nuevo.get("promo") or "Sin texto promocional")


# ============================================================ 3 · Revisión
with tabs[2]:
    st.subheader("Supervisión humana")
    st.caption("Nada se publica sin esta aprobación. Si editás un cuento, se vuelve a validar y queda pendiente.")
    filtro = st.radio("Mostrar", ["pendiente", "rechazado"], horizontal=True, format_func=ETIQUETA_ESTADO.get)
    lista = llamar(api.productos, filtro) or []
    if not lista:
        st.info(f"No hay cuentos en estado '{filtro}'.")
    for p in lista:
        bloqueado = not p["aprobable"]
        solicitante = encargado_por(p)
        titulo = f"N° {p['id']} · {p['titulo']} · {p['edad']} años · {precio_texto(p['precio'])}"
        if solicitante:
            titulo += f" · 🙋 Encargado por {solicitante}"
        with st.expander(("⛔ " if bloqueado else "") + titulo, expanded=len(lista) == 1):
            if solicitante:
                st.info(f"🙋 **Encargado por {solicitante}** por el bot. Al aprobarlo o rechazarlo se le avisa "
                        "por Telegram, y cuando n8n lo publique recibe el link para pedirlo.")
            izq, der = st.columns(2)
            with izq:
                st.markdown("##### ⚙️ Validaciones por reglas (código)")
                mostrar_validaciones(p["validaciones"])
                st.caption(f"Proveedor de IA: {p.get('proveedor_ia') or '—'}")
                if p.get("nota_revision"):
                    st.caption(f"Nota anterior: {p['nota_revision']}")
            with der:
                st.markdown("##### 🤖 Contenido generado por IA")
                with st.container(height=320):
                    st.markdown(p["contenido_md"])
                st.info(p.get("promo") or "Sin texto promocional")

            nota = st.text_input("Nota de revisión", key=f"nota_{p['id']}")
            b1, b2 = st.columns(2)
            if b1.button("✅ Aprobar", key=f"aprobar_{p['id']}", disabled=bloqueado, type="primary",
                         help="Deshabilitado: hay reglas bloqueantes que fallan" if bloqueado else None):
                if llamar(api.revisar, p["id"], "aprobar", nota):
                    recargar(f"Cuento N° {p['id']} aprobado. n8n lo va a publicar en el canal.")
            if b2.button("❌ Rechazar", key=f"rechazar_{p['id']}"):
                if llamar(api.revisar, p["id"], "rechazar", nota):
                    recargar(f"Cuento N° {p['id']} rechazado.")

            with st.popover("✏️ Editar"):
                with st.form(f"editar_{p['id']}"):
                    contenido = st.text_area("Cuento (Markdown)", p["contenido_md"], height=300)
                    promo = st.text_area("Texto promocional", p.get("promo") or "", height=100)
                    nuevo_precio = st.number_input("Precio", min_value=0.0, max_value=100000.0,
                                                   value=float(p["precio"]), step=100.0)
                    if st.form_submit_button("Guardar y revalidar"):
                        cambios = {}
                        if contenido != p["contenido_md"]:
                            cambios["contenido_md"] = contenido
                        if promo != (p.get("promo") or ""):
                            cambios["promo"] = promo
                        if nuevo_precio != p["precio"]:
                            cambios["precio"] = nuevo_precio
                        if not cambios:
                            st.warning("No cambiaste nada.")
                        elif llamar(api.editar, p["id"], cambios):
                            recargar(f"Cuento N° {p['id']} editado y revalidado.")


# ============================================================ 4 · Catálogo
with tabs[3]:
    st.subheader("Catálogo")
    st.caption("**Aprobado**: esperando que n8n lo publique. **Publicado**: ya está en el canal y se puede pedir.")
    for estado in ("publicado", "aprobado"):
        lista = llamar(api.productos, estado) or []
        st.markdown(f"#### {ETIQUETA_ESTADO[estado]} ({len(lista)})")
        if not lista:
            st.caption("Ninguno.")
        for p in lista:
            with st.container(border=True):
                izq, der = st.columns([3, 1])
                with izq:
                    st.markdown(f"**N° {p['id']} · {p['titulo']}**  \n"
                                f"{p['edad']} años · {precio_texto(p['precio'])} · tema: {p['tema']}")
                    st.caption(p.get("promo") or "")
                    if solicitante := encargado_por(p):
                        st.markdown(f"🙋 Encargado por {solicitante}")
                    if p.get("link_pedido"):
                        st.markdown(f"🔗 Link de pedido: {p['link_pedido']}")
                with der:
                    contenido = llamar(api.archivo, p["id"])
                    if contenido:
                        st.download_button("⬇️ Descargar .md", contenido, file_name=p.get("archivo") or f"{p['id']}.md",
                                           mime="text/markdown", key=f"descargar_{p['id']}")


# ============================================================ 5 · Pedidos y pagos
with tabs[4]:
    st.subheader("Pedidos y pagos")
    st.caption("Un cuento pago solo se entrega cuando una persona valida el comprobante. "
               "Al validar, la API le avisa a n8n para que dispare la entrega.")
    todos = llamar(api.pedidos) or []
    if todos:
        tabla = pd.DataFrame(todos)[["id", "producto_titulo", "usuario", "precio", "estado", "estado_pago", "creado"]]
        tabla["estado"] = tabla["estado"].map(lambda e: ETIQUETA_ESTADO.get(e, e))
        st.dataframe(tabla, hide_index=True, use_container_width=True,
                     column_config={"id": "N°", "producto_titulo": "Cuento", "estado_pago": "Pago"})
    else:
        st.info("Todavía no hay pedidos.")

    por_validar = [p for p in todos if p["estado"] == "comprobante_recibido"]
    st.markdown(f"#### 🟠 Comprobantes por validar ({len(por_validar)})")
    for p in por_validar:
        with st.container(border=True):
            izq, der = st.columns([1, 2])
            with izq:
                try:
                    st.image(api.comprobante(p["id"]), caption="Comprobante enviado por el cliente")
                except ErrorAPI as exc:
                    st.warning(f"No se pudo mostrar la imagen. {exc.mensaje}")
                    st.caption(f"file_id: {p.get('comprobante_file')}")
            with der:
                st.markdown(f"**Pedido N° {p['id']}** · {p['producto_titulo']}  \n"
                            f"Cliente: {p.get('usuario') or p['chat_id']} · Monto: {precio_texto(p['precio'])}")
                nota = st.text_input("Nota", key=f"nota_pago_{p['id']}")
                b1, b2 = st.columns(2)
                if b1.button("✅ Validar pago", key=f"validar_{p['id']}", type="primary"):
                    r = llamar(api.validar_pago, p["id"], "validar", nota)
                    if r:
                        extra = "Entrega disparada en n8n." if r.get("entrega_disparada") else \
                            "n8n no respondió: entregalo desde la lista de abajo."
                        recargar(f"Pago del pedido N° {p['id']} validado. {extra}")
                if b2.button("❌ Rechazar pago", key=f"rechazar_pago_{p['id']}"):
                    if llamar(api.validar_pago, p["id"], "rechazar", nota):
                        recargar(f"Pago del pedido N° {p['id']} rechazado. Se le avisó al cliente.")

    listos = [p for p in todos if p["puede_entregar"] and p["estado"] != "entregado"]
    st.markdown(f"#### 📦 Listos para entregar ({len(listos)})")
    st.caption("Normalmente los entrega n8n solo. Este botón es el respaldo manual.")
    for p in listos:
        c1, c2 = st.columns([3, 1])
        c1.markdown(f"Pedido N° {p['id']} · {p['producto_titulo']} · {p.get('usuario') or p['chat_id']} · "
                    f"{precio_texto(p['precio'])}")
        if c2.button("📤 Entregar", key=f"entregar_{p['id']}"):
            if llamar(api.entregar, p["id"]):
                recargar(f"Pedido N° {p['id']} entregado por Telegram.")


# ============================================================ 6 · Consultas
with tabs[5]:
    st.subheader("Consultas del bot")
    st.caption("**regla**: respondió el código sin gastar IA (/start, /catalogo, 'quiero el N° 1'). "
               "**ia**: la IA interpretó el texto libre y el código validó su propuesta.")

    with st.form("probar_bot"):
        texto = st.text_input("Probar un mensaje como si fuera un cliente", placeholder="¿tienen algo para 8 años?")
        if st.form_submit_button("Enviar") and texto.strip():
            r = llamar(api.probar_consulta, texto)
            if r:
                st.markdown(f"**Intención:** {r['intencion']} · **Origen:** {r['origen']} · "
                            f"**Proveedor:** {r.get('proveedor_ia') or '—'}")
                st.info(r["respuesta"])
                if r.get("encargo"):
                    st.success("Es un encargo: la IA lo está escribiendo en segundo plano. En un minuto aparece "
                               "en la pestaña Revisión como «Encargado por @prueba-panel».")

    historial = llamar(api.consultas, 200) or []
    if historial:
        df = pd.DataFrame(historial)
        origen = st.multiselect("Filtrar por origen", sorted(df["origen"].unique()), default=sorted(df["origen"].unique()))
        df = df[df["origen"].isin(origen)]
        st.dataframe(df[["creado", "usuario", "texto", "intencion", "producto_id", "origen", "proveedor_ia", "respuesta"]],
                     hide_index=True, use_container_width=True)
    else:
        st.info("Todavía no hay consultas.")
