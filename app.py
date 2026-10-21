
import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import create_client
import os

# =========================================================
# CONFIGURACIÓN
# =========================================================

st.set_page_config(
    page_title="Sistema de Registro de Votantes",
    page_icon="📊",
    layout="wide",
)

TZ = ZoneInfo("America/Mexico_City")

PARTIDOS = [
    "Partido A",
    "Partido B",
    "Partido C",
    "Otro",
    "Ninguno",
]

# =========================================================
# CONEXIÓN CON SUPABASE
# =========================================================

def obtener_secreto(nombre, predeterminado=None):
    try:
        return st.secrets.get(nombre, predeterminado)
    except Exception:
        return os.environ.get(nombre, predeterminado)


SUPABASE_URL = obtener_secreto("SUPABASE_URL")
SUPABASE_ANON_KEY = obtener_secreto("SUPABASE_ANON_KEY")
SUPABASE_SERVICE_ROLE_KEY = obtener_secreto(
    "SUPABASE_SERVICE_ROLE_KEY"
)


def nuevo_cliente():
    if not SUPABASE_URL or not SUPABASE_ANON_KEY:
        raise RuntimeError(
            "Faltan SUPABASE_URL o SUPABASE_ANON_KEY "
            "en los secretos de Streamlit."
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_ANON_KEY,
    )


def cliente_administrador():
    if not SUPABASE_URL:
        raise RuntimeError(
            "No está configurado SUPABASE_URL."
        )

    if not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "Falta SUPABASE_SERVICE_ROLE_KEY en los secretos "
            "de Streamlit. Agrega la clave administrativa "
            "compatible con Supabase y reinicia la aplicación."
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_SERVICE_ROLE_KEY,
    )


# =========================================================
# UTILIDADES
# =========================================================

def fecha_actual():
    return datetime.now(TZ).isoformat()


def registrar_evento(cliente, usuario_id, evento, exitoso=True):
    try:
        cliente.table("registro_accesos").insert({
            "usuario_id": str(usuario_id),
            "evento": evento,
            "exitoso": exitoso,
            "fecha": fecha_actual(),
        }).execute()
    except Exception:
        # El historial no debe impedir el funcionamiento principal.
        pass


def obtener_perfil(cliente, usuario_id):
    respuesta = (
        cliente.table("perfiles")
        .select("*")
        .eq("id", str(usuario_id))
        .execute()
    )

    perfiles = respuesta.data or []

    if not perfiles:
        return None

    return perfiles[0]


def cargar_votantes(cliente):
    respuesta = (
        cliente.table("votantes")
        .select("*")
        .order("id", desc=True)
        .execute()
    )

    return pd.DataFrame(respuesta.data or [])


def mostrar_error(mensaje, error):
    st.error(mensaje)
    st.error("Detalles técnicos del error:")
    st.exception(error)


# =========================================================
# ESTADO DE SESIÓN
# =========================================================

if "cliente" not in st.session_state:
    st.session_state.cliente = None

if "usuario" not in st.session_state:
    st.session_state.usuario = None

if "perfil" not in st.session_state:
    st.session_state.perfil = None


# =========================================================
# INICIO DE SESIÓN
# =========================================================

def cerrar_sesion():
    cliente = st.session_state.get("cliente")
    usuario = st.session_state.get("usuario")

    if cliente and usuario:
        registrar_evento(
            cliente,
            usuario.id,
            "CIERRE DE SESIÓN",
        )

        try:
            cliente.auth.sign_out()
        except Exception:
            pass

    st.session_state.cliente = None
    st.session_state.usuario = None
    st.session_state.perfil = None
    st.rerun()


if st.session_state.usuario is None:
    st.title("📊 Sistema de Registro de Votantes")
    st.write("Inicia sesión con tu cuenta autorizada.")

    with st.form("formulario_login"):
        correo = st.text_input("Correo electrónico")
        password = st.text_input(
            "Contraseña",
            type="password",
        )
        ingresar = st.form_submit_button(
            "Iniciar sesión",
            use_container_width=True,
        )

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
                    raise RuntimeError(
                        "Supabase no devolvió el usuario."
                    )

                perfil = obtener_perfil(
                    cliente,
                    usuario.id,
                )

                if not perfil:
                    try:
                        cliente.auth.sign_out()
                    except Exception:
                        pass

                    raise RuntimeError(
                        "Tu cuenta no tiene un perfil en la tabla "
                        "public.perfiles. Un administrador debe "
                        "revisar tu cuenta."
                    )

                rol = perfil.get("rol")

                if rol not in ("admin", "consulta"):
                    raise RuntimeError(
                        "El rol debe ser admin o consulta."
                    )

                st.session_state.cliente = cliente
                st.session_state.usuario = usuario
                st.session_state.perfil = perfil

                registrar_evento(
                    cliente,
                    usuario.id,
                    "INICIO DE SESIÓN",
                )

                st.rerun()

            except Exception as e:
                mostrar_error(
                    "No se pudo iniciar sesión.",
                    e,
                )

    st.stop()


# =========================================================
# USUARIO AUTENTICADO
# =========================================================

sb = st.session_state.cliente
usuario = st.session_state.usuario
perfil = st.session_state.perfil

# Volver a comprobar el perfil por si fue modificado.
try:
    perfil_actual = obtener_perfil(sb, usuario.id)

    if not perfil_actual:
        st.error(
            "Tu perfil ya no existe. Contacta al administrador."
        )
        cerrar_sesion()

    perfil = perfil_actual
    st.session_state.perfil = perfil

except Exception as e:
    mostrar_error("No se pudo verificar tu perfil.", e)
    st.stop()


admin = perfil.get("rol") == "admin"

st.sidebar.title("📊 Sistema de Votantes")
st.sidebar.write(
    f"**Usuario:** {perfil.get('nombre') or usuario.email}"
)
st.sidebar.write(f"**Rol:** {perfil.get('rol')}")

if admin:
    opciones = [
        "Inicio",
        "Registrar persona",
        "Consultar registros",
        "Gráfica de registros",
        "Eliminar persona",
        "Administrar perfiles",
        "Historial de accesos",
    ]
else:
    opciones = [
        "Inicio",
        "Consultar registros",
        "Gráfica de registros",
    ]

opcion = st.sidebar.radio(
    "Selecciona una sección",
    opciones,
)

st.sidebar.button(
    "Cerrar sesión",
    on_click=cerrar_sesion,
    use_container_width=True,
)


# =========================================================
# INICIO
# =========================================================

if opcion == "Inicio":
    st.title("Bienvenido al sistema")

    st.write(
        "Utiliza el menú lateral para entrar a las secciones "
        "que tu cuenta tiene autorizadas."
    )

    try:
        df = cargar_votantes(sb)

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Registros disponibles",
                len(df),
            )

        with col2:
            st.metric(
                "Tu rol",
                perfil.get("rol", "Sin rol"),
            )

    except Exception as e:
        mostrar_error(
            "No se pudieron consultar los registros de votantes.",
            e,
        )


# =========================================================
# REGISTRAR PERSONA: SOLO ADMIN
# =========================================================

elif opcion == "Registrar persona" and admin:
    st.title("Registrar persona")

    with st.form("formulario_votante"):
        nombre = st.text_input("Nombre")
        apellido_paterno = st.text_input("Apellido paterno")
        apellido_materno = st.text_input("Apellido materno")
        edad = st.number_input(
            "Edad",
            min_value=18,
            max_value=120,
            value=18,
        )
        curp = st.text_input("CURP")
        domicilio = st.text_area("Domicilio")
        seccion = st.text_input("Sección electoral")
        partido = st.selectbox(
            "Afiliación partidista",
            PARTIDOS,
        )

        guardar = st.form_submit_button(
            "Guardar registro",
            use_container_width=True,
        )

    if guardar:
        if not all([
            nombre.strip(),
            apellido_paterno.strip(),
            curp.strip(),
            domicilio.strip(),
            seccion.strip(),
        ]):
            st.warning(
                "Completa los campos obligatorios."
            )
        else:
            try:
                
                 datos = {
                 "nombre": nombre.strip(),
                 "apellido_paterno": apellido_paterno.strip(),
                 "apellido_materno": apellido_materno.strip(),
                 "edad": int(edad),
                 "curp": curp.strip().upper(),
                 "domicilio": domicilio.strip(),
                 "seccion_municipal": seccion.strip(),
                 "afiliacion_partido": partido,
                 "creado_por": str(usuario.id),
                }

                sb.table("votantes").insert(datos).execute()

                registrar_evento(
                    sb,
                    usuario.id,
                    "REGISTRÓ UNA PERSONA",
                )

                st.success("Registro guardado correctamente.")

            except Exception as e:
                mostrar_error(
                    "No se pudo guardar el registro. "
                    "Comprueba los nombres de las columnas "
                    "y los permisos de Supabase.",
                    e,
                )


# =========================================================
# CONSULTAR REGISTROS
# =========================================================

elif opcion == "Consultar registros":
    st.title("Consultar registros")

    try:
        df = cargar_votantes(sb)

        if df.empty:
            st.info("Todavía no hay registros.")
        else:
            busqueda = st.text_input(
                "Buscar por nombre, CURP o sección"
            )

            if busqueda.strip():
                columnas = [
                    c for c in [
                        "nombre",
                        "apellido_paterno",
                        "apellido_materno",
                        "curp",
                        "seccion",
                    ]
                    if c in df.columns
                ]

                if columnas:
                    coincidencias = pd.Series(
                        False,
                        index=df.index,
                    )

                    for columna in columnas:
                        coincidencias |= (
                            df[columna]
                            .fillna("")
                            .astype(str)
                            .str.contains(
                                busqueda.strip(),
                                case=False,
                                regex=False,
                            )
                        )

                    df = df[coincidencias]

            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )

            # Esta exportación incluye las columnas visibles en df.
            csv = df.to_csv(index=False).encode("utf-8-sig")

            st.download_button(
                "Descargar CSV",
                data=csv,
                file_name="registros_votantes.csv",
                mime="text/csv",
            )

    except Exception as e:
        mostrar_error(
            "No se pudieron consultar los registros de votantes.",
            e,
        )


# =========================================================
# GRÁFICA DE REGISTROS
# =========================================================

elif opcion == "Gráfica de registros":
    st.title("Gráfica de registros")

    try:
        df = cargar_votantes(sb)

        if df.empty:
            st.info("No hay datos suficientes para generar la gráfica.")
        elif "partido" not in df.columns:
            st.error(
                "No se encontró la columna 'partido' en la tabla "
                "votantes. Revisa el nombre real en Supabase."
            )
        else:
            conteo = (
                df["partido"]
                .fillna("Sin dato")
                .value_counts()
            )

            st.subheader("Registros por afiliación partidista")
            st.bar_chart(conteo)

            st.subheader("Cantidad por categoría")
            st.dataframe(
                conteo.rename("Cantidad").reset_index(
                    names="Partido"
                ),
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        mostrar_error(
            "No se pudo generar la gráfica.",
            e,
        )


# =========================================================
# ELIMINAR PERSONA: SOLO ADMIN
# =========================================================

elif opcion == "Eliminar persona" and admin:
    st.title("Eliminar persona")

    st.warning(
        "La eliminación es permanente. Comprueba el registro "
        "antes de confirmar."
    )

    try:
        df = cargar_votantes(sb)

        if df.empty:
            st.info("No hay registros para eliminar.")
        elif "id" not in df.columns:
            st.error(
                "No se encontró la columna 'id' en la tabla votantes."
            )
        else:
            df["seleccion"] = (
                df["id"].astype(str)
                + " — "
                + df.get(
                    "nombre",
                    pd.Series("", index=df.index),
                ).fillna("").astype(str)
                + " "
                + df.get(
                    "apellido_paterno",
                    pd.Series("", index=df.index),
                ).fillna("").astype(str)
            )

            seleccionado = st.selectbox(
                "Selecciona el registro",
                df["seleccion"].tolist(),
            )

            confirmar = st.checkbox(
                "Confirmo que deseo eliminar este registro."
            )

            if st.button(
                "Eliminar registro",
                type="primary",
            ):
                if not confirmar:
                    st.warning(
                        "Marca la casilla de confirmación."
                    )
                else:
                    id_seleccionado = seleccionado.split(
                        " — ",
                        1,
                    )[0]

                    sb.table("votantes").delete().eq(
                        "id",
                        id_seleccionado,
                    ).execute()

                    registrar_evento(
                        sb,
                        usuario.id,
                        "ELIMINÓ UN REGISTRO",
                    )

                    st.success("Registro eliminado.")
                    st.rerun()

    except Exception as e:
        mostrar_error(
            "No se pudo eliminar el registro.",
            e,
        )


# =========================================================
# ADMINISTRAR PERFILES: SOLO ADMIN
# =========================================================

elif opcion == "Administrar perfiles" and admin:
    st.title("Administrar perfiles")

    st.write(
        "Crea cuentas para las personas autorizadas a usar el sistema."
    )

    with st.form("formulario_crear_usuario"):
        nombre_nuevo = st.text_input(
            "Nombre del usuario nuevo"
        )
        correo_nuevo = st.text_input(
            "Correo electrónico del usuario nuevo"
        )
        password_nuevo = st.text_input(
            "Contraseña inicial (mínimo 8 caracteres)",
            type="password",
        )
        rol_nuevo = st.selectbox(
            "Rol",
            ["consulta", "admin"],
            format_func=lambda x: (
                "Consulta (solo consultar y graficar)"
                if x == "consulta"
                else "Administrador"
            ),
        )

        crear = st.form_submit_button(
            "Crear cuenta",
            use_container_width=True,
        )

    if crear:
        if not nombre_nuevo.strip():
            st.error("Escribe el nombre del usuario.")

        elif not correo_nuevo.strip() or "@" not in correo_nuevo:
            st.error("Escribe un correo electrónico válido.")

        elif len(password_nuevo) < 8:
            st.error(
                "La contraseña debe tener al menos 8 caracteres."
            )

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
                    "user_metadata": {
                        "nombre": nombre_nuevo.strip(),
                    },
                })

                usuario_nuevo = respuesta.user

                if not usuario_nuevo:
                    raise RuntimeError(
                        "Supabase no devolvió el usuario creado."
                    )

                # Primero se crea el usuario en Authentication.
                # Después se crea su perfil en public.perfiles.
                cliente_privado.table("perfiles").insert({
                    "id": str(usuario_nuevo.id),
                    "nombre": nombre_nuevo.strip(),
                    "rol": rol_nuevo,
                }).execute()

                cuenta_creada = True

            except Exception as e:
                # Solo intentar eliminar la cuenta si la creación
                # del usuario quedó incompleta.
                if usuario_nuevo and cliente_privado and not cuenta_creada:
                    try:
                        cliente_privado.auth.admin.delete_user(
                            str(usuario_nuevo.id)
                        )
                    except Exception as error_borrado:
                        st.warning(
                            "No se pudo revertir automáticamente "
                            "la cuenta incompleta. Revisa "
                            "Authentication → Users y public.perfiles."
                        )
                        st.exception(error_borrado)

                st.error("No se pudo completar la creación de la cuenta.")
                st.error(
                    "El error técnico que aparece abajo indica "
                    "qué debemos corregir."
                )
                st.exception(e)

            if cuenta_creada:
                registrar_evento(
                    sb,
                    usuario.id,
                    f"ADMIN CREÓ CUENTA CON ROL {rol_nuevo}",
                )

                st.success(
                    f"Cuenta creada correctamente para "
                    f"{correo_nuevo.strip()}."
                )
                st.rerun()

    st.divider()
    st.subheader("Usuarios registrados")

    try:
        respuesta = (
            sb.table("perfiles")
            .select("id, nombre, rol, creado_en")
            .order("nombre")
            .execute()
        )

        perfiles_df = pd.DataFrame(respuesta.data or [])

        if perfiles_df.empty:
            st.info("No hay perfiles registrados.")
        else:
            st.dataframe(
                perfiles_df,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        mostrar_error(
            "No se pudieron consultar los perfiles. "
            "Comprueba las políticas y permisos de la tabla perfiles.",
            e,
        )


# =========================================================
# HISTORIAL DE ACCESOS: SOLO ADMIN
# =========================================================

elif opcion == "Historial de accesos" and admin:
    st.title("Historial de accesos")

    try:
        respuesta = (
            sb.table("registro_accesos")
            .select("*")
            .order("fecha", desc=True)
            .execute()
        )

        df_historial = pd.DataFrame(respuesta.data or [])

        if df_historial.empty:
            st.info("Todavía no hay eventos en el historial.")
        else:
            st.dataframe(
                df_historial,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        mostrar_error(
            "No se pudo consultar el historial de accesos.",
            e,
        )
