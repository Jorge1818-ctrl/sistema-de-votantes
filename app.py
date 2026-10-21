import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import create_client


# =========================================================
# CONFIGURACIÓN GENERAL
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
    "Partido D",
    "Otro",
    "Sin especificar",
]


# =========================================================
# CONEXIÓN CON SUPABASE
# =========================================================

def obtener_secreto(*nombres):
    """Busca el primer secreto configurado."""
    for nombre in nombres:
        valor = st.secrets.get(nombre)
        if valor:
            return str(valor).strip()
    return ""


SUPABASE_URL = obtener_secreto("SUPABASE_URL")

# Acepta el nombre antiguo ANON_KEY o el nuevo PUBLISHABLE_KEY.
SUPABASE_PUBLIC_KEY = obtener_secreto(
    "SUPABASE_ANON_KEY",
    "SUPABASE_PUBLISHABLE_KEY",
)

# Esta clave es exclusivamente para operaciones administrativas.
SUPABASE_ADMIN_KEY = obtener_secreto(
    "SUPABASE_SERVICE_ROLE_KEY",
    "SUPABASE_SECRET_KEY",
)


def nuevo_cliente():
    """Crea un cliente normal de Supabase."""
    if not SUPABASE_URL or not SUPABASE_PUBLIC_KEY:
        raise RuntimeError(
            "Falta SUPABASE_URL o SUPABASE_ANON_KEY/"
            "SUPABASE_PUBLISHABLE_KEY en los Secrets."
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_PUBLIC_KEY,
    )


def cliente_administrador():
    """Crea el cliente privado para administrar usuarios."""
    if not SUPABASE_URL:
        raise RuntimeError("Falta SUPABASE_URL en los Secrets.")

    if not SUPABASE_ADMIN_KEY:
        raise RuntimeError(
            "Falta SUPABASE_SERVICE_ROLE_KEY o "
            "SUPABASE_SECRET_KEY en los Secrets. "
            "La clave Publishable no sirve para crear usuarios."
        )

    return create_client(
        SUPABASE_URL,
        SUPABASE_ADMIN_KEY,
    )


# =========================================================
# FUNCIONES AUXILIARES
# =========================================================

def hora_actual():
    return datetime.now(TZ).isoformat()


def registrar_evento(cliente, usuario_id, evento, exitoso=True):
    """Registra eventos sin detener la aplicación si falla el historial."""
    try:
        cliente.table("registro_accesos").insert({
            "usuario_id": str(usuario_id),
            "evento": str(evento),
            "exitoso": bool(exitoso),
        }).execute()
    except Exception:
        # El fallo del historial no debe bloquear el registro principal.
        pass


def obtener_perfil(cliente, usuario_id):
    respuesta = (
        cliente.table("perfiles")
        .select("id, nombre, rol")
        .eq("id", str(usuario_id))
        .limit(1)
        .execute()
    )

    if respuesta.data:
        return respuesta.data[0]

    return None


def cargar_votantes(cliente):
    """Consulta los registros de votantes."""
    respuesta = (
        cliente.table("votantes")
        .select("*")
        .order("id", desc=True)
        .execute()
    )

    return pd.DataFrame(respuesta.data or [])


def mostrar_error(mensaje, error=None):
    st.error(mensaje)
    if error is not None:
        with st.expander("Detalles técnicos del error"):
            st.exception(error)


# =========================================================
# INICIALIZACIÓN DE LA SESIÓN
# =========================================================

if "sb" not in st.session_state:
    st.session_state.sb = None

if "usuario" not in st.session_state:
    st.session_state.usuario = None

if "perfil" not in st.session_state:
    st.session_state.perfil = None


# =========================================================
# PANTALLA DE INICIO DE SESIÓN
# =========================================================

if st.session_state.sb is None or st.session_state.usuario is None:

    st.title("📊 Sistema de Registro de Votantes")
    st.write("Inicia sesión para acceder al sistema.")

    with st.form("formulario_login"):
        correo = st.text_input(
            "Correo electrónico",
            key="login_correo",
        )

        contrasena = st.text_input(
            "Contraseña",
            type="password",
            key="login_password",
        )

        iniciar = st.form_submit_button(
            "Iniciar sesión",
            use_container_width=True,
        )

    if iniciar:
        if not correo.strip() or not contrasena:
            st.warning("Escribe tu correo y contraseña.")
        else:
            try:
                cliente = nuevo_cliente()

                respuesta = cliente.auth.sign_in_with_password({
                    "email": correo.strip(),
                    "password": contrasena,
                })

                usuario = respuesta.user

                if not usuario:
                    raise RuntimeError(
                        "Supabase no devolvió los datos del usuario."
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

                    st.error(
                        "Tu cuenta no tiene un perfil asignado. "
                        "Solicita al administrador que la configure."
                    )
                    st.stop()

                if perfil.get("rol") not in ("admin", "consulta"):
                    st.error("Tu cuenta tiene un rol no válido.")
                    st.stop()

                st.session_state.sb = cliente
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
                    "No se pudo iniciar sesión. Revisa el correo, "
                    "la contraseña y la configuración de Supabase.",
                    e,
                )

    st.stop()


# =========================================================
# DATOS DEL USUARIO AUTENTICADO
# =========================================================

sb = st.session_state.sb
usuario = st.session_state.usuario
perfil = st.session_state.perfil

uid = str(usuario.id)
nombre_usuario = perfil.get("nombre") or usuario.email or "Usuario"
rol = perfil.get("rol", "consulta")
admin = rol == "admin"


# Actualiza el perfil por si cambió el rol en la base de datos.
try:
    perfil_actualizado = obtener_perfil(sb, uid)

    if perfil_actualizado:
        perfil = perfil_actualizado
        st.session_state.perfil = perfil
        rol = perfil.get("rol", "consulta")
        admin = rol == "admin"

except Exception:
    pass


# =========================================================
# MENÚ PRINCIPAL
# =========================================================

st.sidebar.title("📊 Sistema de Votantes")
st.sidebar.write(f"**Usuario:** {nombre_usuario}")
st.sidebar.write(f"**Rol:** {rol}")

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
    "Selecciona una opción",
    opciones,
)


if st.sidebar.button("Cerrar sesión", use_container_width=True):
    try:
        registrar_evento(
            sb,
            uid,
            "CIERRE DE SESIÓN",
        )
        sb.auth.sign_out()
    except Exception:
        pass

    st.session_state.sb = None
    st.session_state.usuario = None
    st.session_state.perfil = None

    st.rerun()


# =========================================================
# INICIO
# =========================================================

if opcion == "Inicio":

    st.title("Bienvenido al Sistema de Registro de Votantes")

    st.write(
        "Desde este sistema puedes consultar los registros "
        "y revisar las gráficas disponibles."
    )

    if admin:
        st.info(
            "Tu cuenta tiene permisos de administrador. "
            "Puedes registrar personas, eliminar registros "
            "y administrar perfiles."
        )
    else:
        st.info(
            "Tu cuenta tiene permisos de consulta. "
            "Las opciones de administración están restringidas."
        )

    try:
        df_inicio = cargar_votantes(sb)

        col1, col2 = st.columns(2)

        with col1:
            st.metric(
                "Total de registros",
                len(df_inicio),
            )

        with col2:
            if "partido" in df_inicio.columns:
                st.metric(
                    "Partidos o categorías",
                    df_inicio["partido"].nunique(),
                )
            else:
                st.metric("Partidos o categorías", "N/D")

    except Exception as e:
        mostrar_error(
            "No se pudieron consultar los registros.",
            e,
        )


# =========================================================
# REGISTRAR PERSONA — SOLO ADMINISTRADOR
# =========================================================

elif opcion == "Registrar persona" and admin:

    st.title("📝 Registrar persona")

    with st.form("formulario_votante"):

        col1, col2 = st.columns(2)

        with col1:
            nombre = st.text_input("Nombre(s)")
            apellido_paterno = st.text_input("Apellido paterno")
            apellido_materno = st.text_input("Apellido materno")
            edad = st.number_input(
                "Edad",
                min_value=18,
                max_value=120,
                value=18,
                step=1,
            )

        with col2:
            curp = st.text_input(
                "CURP",
                max_chars=18,
            )
            domicilio = st.text_area("Domicilio")
            seccion = st.text_input("Sección electoral")
            partido = st.selectbox(
                "Partido o categoría",
                PARTIDOS,
            )

        guardar = st.form_submit_button(
            "Guardar registro",
            use_container_width=True,
        )

    if guardar:

        if not nombre.strip():
            st.error("El nombre es obligatorio.")

        elif not apellido_paterno.strip():
            st.error("El apellido paterno es obligatorio.")

        elif not curp.strip():
            st.error("La CURP es obligatoria.")

        elif len(curp.strip()) != 18:
            st.error("La CURP debe tener 18 caracteres.")

        elif not domicilio.strip():
            st.error("El domicilio es obligatorio.")

        elif not seccion.strip():
            st.error("La sección electoral es obligatoria.")

        else:
            datos = {
                "nombre": nombre.strip(),
                "apellido_paterno": apellido_paterno.strip(),
                "apellido_materno": apellido_materno.strip(),
                "edad": int(edad),
                "curp": curp.strip().upper(),
                "domicilio": domicilio.strip(),
                "seccion": seccion.strip(),
                "partido": partido,
                "creado_por": uid,
            }

            try:
                sb.table("votantes").insert(datos).execute()

                registrar_evento(
                    sb,
                    uid,
                    "REGISTRO DE PERSONA",
                )

                st.success("La persona se registró correctamente.")
                st.rerun()

            except Exception as e:
                mostrar_error(
                    "No se pudo guardar el registro. "
                    "Comprueba los campos de la tabla votantes "
                    "y sus permisos en Supabase.",
                    e,
                )


# =========================================================
# CONSULTAR REGISTROS
# =========================================================

elif opcion == "Consultar registros":

    st.title("🔎 Consultar registros")

    try:
        df = cargar_votantes(sb)

        if df.empty:
            st.info("Todavía no hay personas registradas.")
        else:
            busqueda = st.text_input(
                "Buscar por nombre, apellidos o CURP"
            )

            if busqueda.strip():
                termino = busqueda.strip().lower()

                columnas_busqueda = [
                    columna
                    for columna in [
                        "nombre",
                        "apellido_paterno",
                        "apellido_materno",
                        "curp",
                    ]
                    if columna in df.columns
                ]

                if columnas_busqueda:
                    mascara = pd.Series(
                        False,
                        index=df.index,
                    )

                    for columna in columnas_busqueda:
                        mascara = mascara | (
                            df[columna]
                            .fillna("")
                            .astype(str)
                            .str.lower()
                            .str.contains(
                                termino,
                                regex=False,
                            )
                        )

                    df = df[mascara]

            st.write(f"Registros encontrados: **{len(df)}**")
            st.dataframe(
                df,
                use_container_width=True,
                hide_index=True,
            )

            csv = df.to_csv(index=False).encode("utf-8-sig")

            st.download_button(
                "Descargar resultados en CSV",
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

    st.title("📈 Gráfica de registros")

    try:
        df = cargar_votantes(sb)

        if df.empty:
            st.info("No hay datos suficientes para crear la gráfica.")

        elif "partido" not in df.columns:
            st.error(
                "No se encontró la columna 'partido' "
                "en la tabla votantes."
            )

        else:
            conteo = (
                df["partido"]
                .fillna("Sin especificar")
                .astype(str)
                .value_counts()
            )

            st.subheader("Registros por partido o categoría")
            st.bar_chart(conteo)

            st.subheader("Resumen")
            resumen = conteo.rename_axis("Partido").reset_index(
                name="Cantidad"
            )

            st.dataframe(
                resumen,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        mostrar_error(
            "No se pudo generar la gráfica.",
            e,
        )


# =========================================================
# ELIMINAR PERSONA — SOLO ADMINISTRADOR
# =========================================================

elif opcion == "Eliminar persona" and admin:

    st.title("🗑️ Eliminar persona")

    st.warning(
        "Esta acción elimina un registro de la base de datos "
        "y no se puede deshacer desde esta pantalla."
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
            opciones_ids = df["id"].tolist()

            def etiqueta_persona(id_persona):
                fila = df[df["id"] == id_persona].iloc[0]

                nombre_completo = " ".join(
                    str(fila.get(campo, "") or "")
                    for campo in [
                        "nombre",
                        "apellido_paterno",
                        "apellido_materno",
                    ]
                ).strip()

                return f"ID {id_persona} — {nombre_completo}"

            id_seleccionado = st.selectbox(
                "Selecciona el registro",
                opciones_ids,
                format_func=etiqueta_persona,
            )

            confirmar = st.checkbox(
                "Confirmo que deseo eliminar este registro."
            )

            if st.button(
                "Eliminar registro",
                type="primary",
            ):
                if not confirmar:
                    st.error(
                        "Marca la casilla de confirmación antes de eliminar."
                    )
                else:
                    sb.table("votantes").delete().eq(
                        "id",
                        id_seleccionado,
                    ).execute()

                    registrar_evento(
                        sb,
                        uid,
                        f"ELIMINÓ REGISTRO ID {id_seleccionado}",
                    )

                    st.success("Registro eliminado correctamente.")
                    st.rerun()

    except Exception as e:
        mostrar_error(
            "No se pudo eliminar el registro.",
            e,
        )


# =========================================================
# ADMINISTRAR PERFILES — SOLO ADMINISTRADOR
# =========================================================

elif opcion == "Administrar perfiles" and admin:

    st.title("👥 Administrar perfiles")
    st.write(
        "Desde aquí puedes crear cuentas y asignarles un rol."
    )

    st.subheader("Crear cuenta")

    with st.form("formulario_nuevo_usuario"):

        nombre_nuevo = st.text_input(
            "Nombre del usuario",
            key="nombre_nuevo",
        )

        correo_nuevo = st.text_input(
            "Correo electrónico",
            key="correo_nuevo",
        )

        password_nuevo = st.text_input(
            "Contraseña inicial",
            type="password",
            key="password_nuevo",
        )

        rol_nuevo = st.selectbox(
            "Rol de la cuenta",
            ["consulta", "admin"],
            format_func=lambda x: (
                "Consulta" if x == "consulta" else "Administrador"
            ),
            key="rol_nuevo",
        )

        crear = st.form_submit_button(
            "Crear cuenta",
            use_container_width=True,
        )

    # -----------------------------------------------------
    # VALIDACIÓN Y CREACIÓN DE LA CUENTA
    # -----------------------------------------------------

    if crear:

        if not nombre_nuevo.strip():
            st.error("Escribe el nombre del usuario.")

        elif (
            not correo_nuevo.strip()
            or "@" not in correo_nuevo
        ):
            st.error("Escribe un correo electrónico válido.")

        elif len(password_nuevo) < 8:
            st.error(
                "La contraseña debe tener al menos 8 caracteres."
            )

        else:
            usuario_nuevo = None
            cliente_privado = None
            creacion_exitosa = False

            try:
                # Se necesita una clave administrativa, no la Publishable.
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

                # Crear el perfil asociado al usuario de Auth.
                try:
                    cliente_privado.table("perfiles").insert({
                        "id": str(usuario_nuevo.id),
                        "nombre": nombre_nuevo.strip(),
                        "rol": rol_nuevo,
                    }).execute()

                except Exception:
                    # Si falla el perfil, intenta deshacer la cuenta
                    # recién creada para no dejar un usuario incompleto.
                    try:
                        cliente_privado.auth.admin.delete_user(
                            str(usuario_nuevo.id)
                        )
                    except Exception:
                        st.warning(
                            "No se pudo eliminar automáticamente "
                            "la cuenta incompleta. Revisa Authentication "
                            "→ Users y la tabla public.perfiles."
                        )

                    raise

                # El registro del historial no debe invalidar la cuenta.
                registrar_evento(
                    sb,
                    uid,
                    f"ADMIN CREÓ CUENTA CON ROL {rol_nuevo}",
                )

                creacion_exitosa = True

            except Exception as e:
                mostrar_error(
                    "No se pudo completar la creación de la cuenta. "
                    "Comprueba la clave administrativa, el correo "
                    "y las tablas de Supabase.",
                    e,
                )

            # El rerun se ejecuta FUERA del try/except para evitar
            # que una actualización de Streamlit se trate como error.
            if creacion_exitosa:
                st.success(
                    f"Cuenta creada correctamente para "
                    f"{correo_nuevo.strip()}."
                )
                st.rerun()

    # -----------------------------------------------------
    # LISTADO DE PERFILES
    # Esta sección queda fuera del if crear.
    # -----------------------------------------------------

    st.divider()
    st.subheader("Usuarios registrados")

    try:
        respuesta_perfiles = (
            sb.table("perfiles")
            .select("id, nombre, rol, creado_en")
            .order("nombre")
            .execute()
        )

        perfiles_df = pd.DataFrame(
            respuesta_perfiles.data or []
        )

        if perfiles_df.empty:
            st.info("No hay perfiles para mostrar.")
        else:
            st.dataframe(
                perfiles_df,
                use_container_width=True,
                hide_index=True,
            )

    except Exception as e:
        mostrar_error(
            "No se pudieron consultar los perfiles. "
            "Comprueba que la tabla perfiles tenga las columnas "
            "id, nombre, rol y creado_en.",
            e,
        )


# =========================================================
# HISTORIAL DE ACCESOS — SOLO ADMINISTRADOR
# =========================================================

elif opcion == "Historial de accesos" and admin:

    st.title("🕘 Historial de accesos")

    try:
        respuesta_historial = (
            sb.table("registro_accesos")
            .select("*")
            .order("id", desc=True)
            .limit(500)
            .execute()
        )

        historial_df = pd.DataFrame(
            respuesta_historial.data or []
        )

        if historial_df.empty:
            st.info("Todavía no hay eventos en el historial.")
        else:
            st.dataframe(
                historial_df,
                use_container_width=True,
                hide_index=True,
            )

            csv_historial = historial_df.to_csv(
                index=False
            ).encode("utf-8-sig")

            st.download_button(
                "Descargar historial CSV",
                data=csv_historial,
                file_name="historial_accesos.csv",
                mime="text/csv",
            )

    except Exception as e:
        mostrar_error(
            "No se pudo consultar el historial de accesos.",
            e,
        )


# =========================================================
# CONTROL DE OPCIONES NO AUTORIZADAS
# =========================================================

else:
    st.error(
        "No tienes permisos para acceder a esta sección."
    )
