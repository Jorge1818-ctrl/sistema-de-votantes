import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client

# =========================================================
# CONFIGURACION
# La tabla public.votantes utiliza solamente:
#   numero (VARCHAR(4), PK)
#   estado (VARCHAR(20))
# =========================================================

st.set_page_config(
    page_title="Sistema de Pase de Lista",
    page_icon="🔢",
    layout="wide",
    initial_sidebar_state="expanded",
)

TZ = ZoneInfo("America/Mexico_City")
ESTADOS = ["Pendiente", "Ya votó", "No ha votado"]


def obtener_secreto(nombre, predeterminado=None):
    try:
        return st.secrets.get(nombre, predeterminado)
    except Exception:
        return os.environ.get(nombre, predeterminado)


SUPABASE_URL = obtener_secreto("SUPABASE_URL")
SUPABASE_ANON_KEY = obtener_secreto("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = obtener_secreto("SUPABASE_SERVICE_ROLE_KEY")


def nuevo_cliente():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_ANON_KEY en los Secrets de Streamlit.")
    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def cliente_administrador():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError("Falta SUPABASE_SERVICE_ROLE_KEY en los Secrets de Streamlit.")
    return create_client(SUPABASE_URL, SUPABASE_SERVICE_ROLE_KEY)


def fecha_actual():
    return datetime.now(TZ).isoformat()


def registrar_evento(cliente, usuario_id, evento, exitoso=True):
    try:
        cliente.table("registro_accesos").insert({
            "usuario_id": str(usuario_id),
            "evento": evento,
            "exitoso": exitoso,
            "creado_en": fecha_actual(),
        }).execute()
    except Exception as error:
        # El historial no debe impedir el funcionamiento del pase de lista.
        print(f"No se pudo registrar el evento: {error}")


def obtener_perfil(cliente, usuario_id):
    respuesta = (
        cliente.table("perfiles")
        .select("id, nombre, rol")
        .eq("id", str(usuario_id))
        .limit(1)
        .execute()
    )
    perfiles = respuesta.data or []
    return perfiles[0] if perfiles else None


def cargar_votantes(cliente):
    """Consulta todos los números en bloques de 1,000; solo solicita numero y estado."""
    todos = []
    inicio = 0
    limite = 1000

    while True:
        respuesta = (
            cliente.table("votantes")
            .select("numero, estado")
            .order("numero")
            .range(inicio, inicio + limite - 1)
            .execute()
        )

        datos = respuesta.data or []
        todos.extend(datos)

        if len(datos) < limite:
            break

        inicio += limite

    return pd.DataFrame(todos, columns=["numero", "estado"])


def mostrar_error(mensaje, error):
    st.error(mensaje)
    st.caption("Detalle técnico:")
    st.exception(error)


def normalizar_numero(valor):
    texto = str(valor or "").strip()
    if not texto.isdigit() or not 1 <= len(texto) <= 4:
        return None
    return texto.zfill(4)


def cerrar_sesion():
    cliente = st.session_state.get("cliente")
    usuario = st.session_state.get("usuario")
    if cliente and usuario:
        registrar_evento(cliente, usuario.id, "CIERRE DE SESIÓN")
        try:
            cliente.auth.sign_out()
        except Exception:
            pass
    for llave in ("cliente", "usuario", "perfil", "numero_encontrado"):
        st.session_state.pop(llave, None)
    st.rerun()


# =========================================================
# SESION E INICIO DE SESION
# =========================================================

if "cliente" not in st.session_state:
    st.session_state.cliente = None
if "usuario" not in st.session_state:
    st.session_state.usuario = None
if "perfil" not in st.session_state:
    st.session_state.perfil = None

if st.session_state.usuario is None:
    st.title("🔢 Sistema de Pase de Lista")
    st.write("Inicia sesión con una cuenta autorizada.")

    with st.form("formulario_login"):
        correo = st.text_input("Correo electrónico")
        password = st.text_input("Contraseña", type="password")
        ingresar = st.form_submit_button("Iniciar sesión", use_container_width=True)

    if ingresar:
        if not correo.strip() or not password:
            st.warning("Escribe tu correo y contraseña.")
        else:
            try:
                cliente = nuevo_cliente()
                respuesta = cliente.auth.sign_in_with_password({
                    "email": correo.strip(),
                    "password": password,
                })
                usuario = respuesta.user
                if not usuario:
                    raise RuntimeError("Supabase no devolvió el usuario.")

                perfil = obtener_perfil(cliente, usuario.id)
                if not perfil:
                    try:
                        cliente.auth.sign_out()
                    except Exception:
                        pass
                    raise RuntimeError("Tu cuenta no tiene un perfil en public.perfiles. Contacta al administrador.")

                if perfil.get("rol") not in ("admin", "consulta"):
                    raise RuntimeError("El rol de la cuenta debe ser admin o consulta.")

                st.session_state.cliente = cliente
                st.session_state.usuario = usuario
                st.session_state.perfil = perfil
                registrar_evento(cliente, usuario.id, "INICIO DE SESIÓN")
                st.rerun()
            except Exception as error:
                mostrar_error("No se pudo iniciar sesión.", error)
    st.stop()


# =========================================================
# USUARIO AUTENTICADO Y MENU
# =========================================================

sb = st.session_state.cliente
usuario = st.session_state.usuario

try:
    perfil = obtener_perfil(sb, usuario.id)
    if not perfil:
        st.error("Tu perfil ya no existe. Contacta al administrador.")
        cerrar_sesion()
    st.session_state.perfil = perfil
except Exception as error:
    mostrar_error("No se pudo verificar tu perfil.", error)
    st.stop()

admin = perfil.get("rol") == "admin"

st.sidebar.title("🔢 Pase de Lista")
st.sidebar.write(f"**Cuenta:** {perfil.get('nombre') or usuario.email}")
st.sidebar.write(f"**Rol:** {perfil.get('rol')}")

opciones = ["Inicio", "Pase de lista", "Gráficas"]
if admin:
    opciones += ["Administrar números", "Administrar perfiles", "Historial de accesos"]
opcion = st.sidebar.radio("Menú", opciones)
st.sidebar.button("Cerrar sesión", on_click=cerrar_sesion, use_container_width=True)


# =========================================================
# INICIO
# =========================================================

if opcion == "Inicio":
    st.title("Bienvenido al sistema")
    st.write("Utiliza el menú lateral para entrar a las secciones autorizadas.")
    try:
        df = cargar_votantes(sb)
        total = len(df)
        ya_votaron = int((df["estado"] == "Ya votó").sum()) if total else 0
        no_votaron = int((df["estado"] == "No ha votado").sum()) if total else 0
        pendientes = int((df["estado"] == "Pendiente").sum()) if total else 0
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total de números", total)
        c2.metric("Ya votaron", ya_votaron)
        c3.metric("No han votado", no_votaron)
        c4.metric("Pendientes", pendientes)
        st.subheader("Resumen del pase de lista")
        if df.empty:
            st.info("Todavía no hay números registrados.")
        else:
            vista = df.rename(columns={"numero": "Número", "estado": "Estado"})
            st.dataframe(vista, use_container_width=True, hide_index=True)
    except Exception as error:
        mostrar_error("No se pudieron consultar los números de pase de lista.", error)


# =========================================================
# PASE DE LISTA
# =========================================================

elif opcion == "Pase de lista":
    st.title("📝 Pase de lista por número")
    st.write("Busca utilizando únicamente el número de cuatro cifras.")
    try:
        df = cargar_votantes(sb)
        if df.empty:
            st.info("Todavía no hay números registrados. El administrador puede agregarlos desde el menú.")
        else:
            with st.form("buscar_numero"):
                entrada = st.text_input("Número de control", max_chars=4, placeholder="Ej. 0025")
                buscar = st.form_submit_button("Buscar número", use_container_width=True)

            if buscar:
                numero = normalizar_numero(entrada)
                if not numero:
                    st.warning("Escribe de 1 a 4 cifras numéricas.")
                else:
                    encontrado = df[df["numero"] == numero]
                    if encontrado.empty:
                        st.error("No se encontró ese número.")
                        st.session_state.pop("numero_encontrado", None)
                    else:
                        st.session_state.numero_encontrado = numero

            numero_actual = st.session_state.get("numero_encontrado")
            if numero_actual:
                registro = df[df["numero"] == numero_actual]
                if not registro.empty:
                    estado_actual = str(registro.iloc[0]["estado"] or "Pendiente")
                    st.success("Número encontrado.")
                    st.markdown(f"## Número {numero_actual}")
                    st.write(f"**Estado actual:** {estado_actual}")
                    with st.form(f"actualizar_estado_{numero_actual}"):
                        nuevo_estado = st.selectbox(
                            "Actualizar estado",
                            ESTADOS,
                            index=ESTADOS.index(estado_actual) if estado_actual in ESTADOS else 0,
                        )
                        guardar = st.form_submit_button("Guardar estado", use_container_width=True)
                    if guardar:
                        try:
                            sb.table("votantes").update({"estado": nuevo_estado}).eq("numero", numero_actual).execute()
                            registrar_evento(sb, usuario.id, f"ACTUALIZÓ ESTADO DEL NÚMERO {numero_actual}: {nuevo_estado}")
                            st.success("Estado actualizado correctamente.")
                            st.rerun()
                        except Exception as error:
                            mostrar_error("No se pudo actualizar el estado.", error)

            st.divider()
            st.subheader("Lista general")
            filtro = st.selectbox("Filtrar por estado", ["Todos"] + ESTADOS)
            vista = df.copy()
            if filtro != "Todos":
                vista = vista[vista["estado"] == filtro]
            vista = vista.rename(columns={"numero": "Número", "estado": "Estado"})
            st.dataframe(vista, use_container_width=True, hide_index=True)
            st.download_button(
                "Descargar lista CSV",
                data=vista.to_csv(index=False).encode("utf-8-sig"),
                file_name="pase_lista.csv",
                mime="text/csv",
                use_container_width=True,
            )
    except Exception as error:
        mostrar_error("No se pudo consultar el pase de lista.", error)


# =========================================================
# GRAFICAS
# =========================================================

elif opcion == "Gráficas":
    st.title("📊 Resumen del pase de lista")
    try:
        df = cargar_votantes(sb)
        if df.empty:
            st.info("Todavía no hay números registrados.")
        else:
            conteo = df["estado"].value_counts().reindex(ESTADOS, fill_value=0)
            a, b = st.columns(2)
            a.metric("Total", len(df))
            b.metric("Marcados como ya votó", int(conteo["Ya votó"]))
            st.bar_chart(conteo)
            st.dataframe(
                conteo.rename("Cantidad").rename_axis("Estado").reset_index(),
                use_container_width=True,
                hide_index=True,
            )
    except Exception as error:
        mostrar_error("No se pudieron generar las gráficas.", error)


# =========================================================
# ADMINISTRAR NUMEROS (SOLO ADMIN)
# =========================================================

elif opcion == "Administrar números" and admin:
    st.title("🔢 Administrar números")
    st.write("Agrega números de control. Supabase asignará automáticamente el siguiente número disponible.")

    cantidad = st.number_input("Cantidad de números que deseas agregar", min_value=1, max_value=100, value=1, step=1)
    if st.button("Crear números", type="primary", use_container_width=True):
        try:
            # La función/trigger de Supabase genera el campo numero.
            nuevos = [{"estado": "Pendiente"} for _ in range(int(cantidad))]
            respuesta = sb.table("votantes").insert(nuevos).execute()
            creados = respuesta.data or []
            registrar_evento(sb, usuario.id, f"CREÓ {len(creados)} NÚMEROS DE CONTROL")
            st.success(f"Se crearon {len(creados)} números.")
            if creados:
                st.dataframe(pd.DataFrame(creados)[["numero", "estado"]], use_container_width=True, hide_index=True)
            st.rerun()
        except Exception as error:
            mostrar_error("No se pudieron crear los números. Verifica que el trigger de numeración esté activo en Supabase.", error)

    st.divider()
    st.subheader("Eliminar un número")
    try:
        df = cargar_votantes(sb)
        if df.empty:
            st.info("No hay números para eliminar.")
        else:
            opciones_numero = df["numero"].astype(str).tolist()
            numero_eliminar = st.selectbox("Selecciona el número", opciones_numero)
            confirmar = st.checkbox("Confirmo que deseo eliminar este número permanentemente.")
            if st.button("Eliminar número", disabled=not confirmar, type="secondary", use_container_width=True):
                sb.table("votantes").delete().eq("numero", numero_eliminar).execute()
                registrar_evento(sb, usuario.id, f"ELIMINÓ EL NÚMERO {numero_eliminar}")
                st.success(f"Se eliminó el número {numero_eliminar}.")
                st.rerun()
    except Exception as error:
        mostrar_error("No se pudieron administrar los números.", error)


# =========================================================
# ADMINISTRAR PERFILES (SOLO ADMIN)
# =========================================================

elif opcion == "Administrar perfiles" and admin:
    st.title("Administrar perfiles")
    st.write("Las cuentas de acceso se administran por separado de la tabla de números.")

    with st.form("crear_usuario"):
        nombre_nuevo = st.text_input("Nombre de la cuenta")
        correo_nuevo = st.text_input("Correo electrónico")
        password_nuevo = st.text_input("Contraseña inicial (mínimo 8 caracteres)", type="password")
        rol_nuevo = st.selectbox("Rol", ["consulta", "admin"])
        crear = st.form_submit_button("Crear cuenta", use_container_width=True)

    if crear:
        if not nombre_nuevo.strip():
            st.error("Escribe el nombre de la cuenta.")
        elif "@" not in correo_nuevo.strip():
            st.error("Escribe un correo válido.")
        elif len(password_nuevo) < 8:
            st.error("La contraseña debe tener al menos 8 caracteres.")
        else:
            cliente_privado = None
            usuario_nuevo = None
            cuenta_creada = False
            try:
                cliente_privado = cliente_administrador()
                respuesta = cliente_privado.auth.admin.create_user({
                    "email": correo_nuevo.strip(),
                    "password": password_nuevo,
                    "email_confirm": True,
                    "user_metadata": {"nombre": nombre_nuevo.strip()},
                })
                usuario_nuevo = respuesta.user
                if not usuario_nuevo:
                    raise RuntimeError("Supabase no devolvió el usuario creado.")
                cliente_privado.table("perfiles").insert({
                    "id": str(usuario_nuevo.id),
                    "nombre": nombre_nuevo.strip(),
                    "rol": rol_nuevo,
                }).execute()
                cuenta_creada = True
            except Exception as error:
                if usuario_nuevo and cliente_privado and not cuenta_creada:
                    try:
                        cliente_privado.auth.admin.delete_user(str(usuario_nuevo.id))
                    except Exception:
                        pass
                mostrar_error("No se pudo crear la cuenta.", error)
            if cuenta_creada:
                registrar_evento(sb, usuario.id, f"CREÓ CUENTA CON ROL {rol_nuevo}")
                st.success("Cuenta creada correctamente.")
                st.rerun()

    st.divider()
    st.subheader("Cuentas registradas")
    try:
        respuesta = sb.table("perfiles").select("id, nombre, rol").order("nombre").execute()
        perfiles_df = pd.DataFrame(respuesta.data or [])
        if perfiles_df.empty:
            st.info("No hay perfiles registrados.")
        else:
            st.dataframe(perfiles_df, use_container_width=True, hide_index=True)
    except Exception as error:
        mostrar_error("No se pudieron consultar los perfiles.", error)


# =========================================================
# HISTORIAL DE ACCESOS (SOLO ADMIN)
# =========================================================

elif opcion == "Historial de accesos" and admin:
    st.title("Historial de accesos")
    try:
        respuesta = sb.table("registro_accesos").select("*").order("creado_en", desc=True).execute()
        historial = pd.DataFrame(respuesta.data or [])
        if historial.empty:
            st.info("Todavía no hay eventos registrados.")
        else:
            st.dataframe(historial, use_container_width=True, hide_index=True)
    except Exception as error:
        mostrar_error("No se pudo consultar el historial de accesos.", error)
