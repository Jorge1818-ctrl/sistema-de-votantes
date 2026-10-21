
import streamlit as st
import pandas as pd
import os
import io
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import create_client

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

COLUMNA_SECCION = "seccion_municipal"
COLUMNA_PARTIDO = "afiliacion_partido"


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

    return create_client(SUPABASE_URL, SUPABASE_ANON_KEY)


def cliente_administrador():
    if not SUPABASE_URL or not SUPABASE_SERVICE_ROLE_KEY:
        raise RuntimeError(
            "Falta SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY "
            "en los secretos de Streamlit."
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


def registrar_evento(
    cliente,
    usuario_id,
    evento,
    exitoso=True,
):
    try:
        cliente.table("registro_accesos").insert({
            "usuario_id": str(usuario_id),
            "evento": evento,
            "exitoso": exitoso,
            "fecha": fecha_actual(),
        }).execute()
    except Exception as e:
        print(f"No se pudo registrar el evento: {e}")


def obtener_perfil(cliente, usuario_id):
    respuesta = (
        cliente.table("perfiles")
        .select("*")
        .eq("id", str(usuario_id))
        .execute()
    )

    perfiles = respuesta.data or []
    return perfiles[0] if perfiles else None


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
# LECTURA Y NORMALIZACIÓN DE ARCHIVOS
# =========================================================

def normalizar_texto(valor):
    texto = str(valor).strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(
        caracter for caracter in texto
        if not unicodedata.combining(caracter)
    )
    texto = re.sub(r"[^a-z0-9]+", "_", texto)
    return texto.strip("_")


# Los encabezados del archivo pueden tener distintos nombres.
ALIAS_COLUMNAS = {
    "nombre": [
        "nombre",
        "nombres",
        "name",
    ],
    "apellido_paterno": [
        "apellido_paterno",
        "apellidopaterno",
        "primer_apellido",
        "apellido1",
    ],
    "apellido_materno": [
        "apellido_materno",
        "apellidomaterno",
        "segundo_apellido",
        "apellido2",
    ],
    "edad": [
        "edad",
        "age",
    ],
    "curp": [
        "curp",
        "clave_unica_de_registro_de_poblacion",
    ],
    "domicilio": [
        "domicilio",
        "direccion",
        "dirección",
        "address",
    ],
    "seccion_municipal": [
        "seccion_municipal",
        "seccion",
        "seccion_electoral",
        "seccion_municipal_electoral",
    ],
    "afiliacion_partido": [
        "afiliacion_partido",
        "afiliacion_partidista",
        "partido",
        "afiliacion",
        "partido_politico",
    ],
}


def preparar_archivo(df_original):
    df = df_original.copy()

    # Normalizar encabezados para aceptar acentos y espacios.
    columnas_normalizadas = {
        columna: normalizar_texto(columna)
        for columna in df.columns
    }
    df = df.rename(columns=columnas_normalizadas)

    # Traducir encabezados alternativos a columnas de Supabase.
    renombrar = {}

    for columna_destino, alias in ALIAS_COLUMNAS.items():
        for nombre_alias in alias:
            nombre_normalizado = normalizar_texto(nombre_alias)

            if nombre_normalizado in df.columns:
                renombrar[nombre_normalizado] = columna_destino
                break

    df = df.rename(columns=renombrar)

    # Si hay encabezados repetidos después de normalizar,
    # se conserva solamente la primera columna.
    df = df.loc[:, ~df.columns.duplicated()]

    columnas_obligatorias = [
        "nombre",
        "apellido_paterno",
        "curp",
        "domicilio",
        "seccion_municipal",
        "afiliacion_partido",
    ]

    faltantes = [
        columna for columna in columnas_obligatorias
        if columna not in df.columns
    ]

    if faltantes:
        raise ValueError(
            "Faltan estas columnas obligatorias en el archivo: "
            + ", ".join(faltantes)
            + ". Revisa los encabezados del archivo."
        )

    if "apellido_materno" not in df.columns:
        df["apellido_materno"] = ""

    if "edad" not in df.columns:
        df["edad"] = None

    # Limpiar valores de texto y evitar valores NaN.
    columnas_texto = [
        "nombre",
        "apellido_paterno",
        "apellido_materno",
        "curp",
        "domicilio",
        "seccion_municipal",
        "afiliacion_partido",
    ]

    for columna in columnas_texto:
        df[columna] = (
            df[columna]
            .fillna("")
            .astype(str)
            .str.strip()
        )

    df["curp"] = df["curp"].str.upper()

    # Quitar filas completamente vacías en los campos principales.
    df = df[
        df[
            [
                "nombre",
                "apellido_paterno",
                "curp",
                "domicilio",
                "seccion_municipal",
                "afiliacion_partido",
            ]
        ].ne("").all(axis=1)
    ].copy()

    return df


def leer_archivo_votantes(archivo):
    contenido = archivo.getvalue()
    nombre_archivo = archivo.name.lower()

    if nombre_archivo.endswith(".csv"):
        errores_lectura = []

        for codificacion in ("utf-8-sig", "utf-8", "latin-1"):
            try:
                df = pd.read_csv(
                    io.BytesIO(contenido),
                    encoding=codificacion,
                    dtype=str,
                )
                return preparar_archivo(df)
            except UnicodeDecodeError as e:
                errores_lectura.append(str(e))

        raise ValueError(
            "No se pudo interpretar la codificación del CSV."
        )

    if nombre_archivo.endswith(".xlsx"):
        df = pd.read_excel(
            io.BytesIO(contenido),
            dtype=str,
        )
        return preparar_archivo(df)

    raise ValueError(
        "Formato no compatible. Sube un archivo CSV o XLSX."
    )


def convertir_edad(valor):
    if valor is None or pd.isna(valor) or str(valor).strip() == "":
        return None

    numero = pd.to_numeric(valor, errors="coerce")

    if pd.isna(numero):
        raise ValueError("La edad no es un número válido.")

    numero = int(numero)

    if numero < 18 or numero > 120:
        raise ValueError(
            "La edad debe estar entre 18 y 120 años."
        )

    return numero


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
# CERRAR SESIÓN
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


# =========================================================
# INICIO DE SESIÓN
# =========================================================

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

                perfil = obtener_perfil(cliente, usuario.id)

                if not perfil:
                    try:
                        cliente.auth.sign_out()
                    except Exception:
                        pass

                    raise RuntimeError(
                        "Tu cuenta no tiene un perfil en "
                        "public.perfiles. Contacta al administrador."
                    )

                if perfil.get("rol") not in ("admin", "consulta"):
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
                mostrar_error("No se pudo iniciar sesión.", e)

    st.stop()


# =========================================================
# USUARIO AUTENTICADO
# =========================================================

sb = st.session_state.cliente
usuario = st.session_state.usuario
perfil = st.session_state.perfil

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
        "Importar archivo de votantes",
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
            st.metric("Registros disponibles", len(df))

        with col2:
            st.metric("Tu rol", perfil.get("rol", "Sin rol"))

    except Exception as e:
        mostrar_error(
            "No se pudieron consultar los registros de votantes.",
            e,
        )


# =========================================================
# REGISTRAR PERSONA
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
            step=1,
        )

        curp = st.text_input("CURP")
        domicilio = st.text_area("Domicilio")
        seccion = st.text_input("Sección municipal")

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
            st.warning("Completa los campos obligatorios.")

        elif len(curp.strip()) != 18:
            st.warning("La CURP debe tener 18 caracteres.")

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
                    "No se pudo guardar el registro.",
                    e,
                )


# =========================================================
# IMPORTAR ARCHIVO DE VOTANTES
# =========================================================

elif opcion == "Importar archivo de votantes" and admin:
    st.title("📁 Importar archivo de votantes")

    st.write(
        "Carga un archivo CSV o Excel para incorporar sus "
        "registros a Supabase y utilizarlos en las gráficas."
    )

    st.info(
        "El archivo debe contener columnas equivalentes a: "
        "nombre, apellido paterno, CURP, domicilio, "
        "sección municipal y afiliación partidista. "
        "También puedes incluir apellido materno y edad."
    )

    archivo = st.file_uploader(
        "Selecciona el archivo CSV o Excel",
        type=["csv", "xlsx"],
        help="Formatos aceptados: .csv y .xlsx",
    )

    if archivo is not None:
        try:
            df_archivo = leer_archivo_votantes(archivo)

            if df_archivo.empty:
                st.warning(
                    "El archivo no contiene filas completas "
                    "para importar."
                )
            else:
                st.success(
                    f"Archivo leído correctamente: "
                    f"{len(df_archivo)} filas preparadas."
                )

                st.subheader("Vista previa")
                st.dataframe(
                    df_archivo.head(20),
                    use_container_width=True,
                    hide_index=True,
                )

                st.caption(
                    "La vista previa muestra hasta 20 filas. "
                    "Los registros no se guardan hasta pulsar "
                    "el botón de importación."
                )

                confirmar_importacion = st.checkbox(
                    "Confirmo que tengo autorización para importar "
                    "estos datos y que revisé el archivo."
                )

                if st.button(
                    "Importar registros a Supabase",
                    type="primary",
                    disabled=not confirmar_importacion,
                ):
                    total_importados = 0
                    total_omitidos = 0
                    errores_importacion = []

                    barra = st.progress(0)
                    estado = st.empty()

                    try:
                        # Importar fila por fila permite que un
                        # registro inválido no detenga los demás.
                        for indice, fila in df_archivo.iterrows():
                            try:
                                edad_valor = convertir_edad(
                                    fila.get("edad")
                                )

                                curp_valor = str(
                                    fila["curp"]
                                ).strip().upper()

                                if len(curp_valor) != 18:
                                    raise ValueError(
                                        "La CURP no tiene 18 caracteres."
                                    )

                                datos = {
                                    "nombre": str(
                                        fila["nombre"]
                                    ).strip(),
                                    "apellido_paterno": str(
                                        fila["apellido_paterno"]
                                    ).strip(),
                                    "apellido_materno": str(
                                        fila.get(
                                            "apellido_materno",
                                            "",
                                        )
                                    ).strip(),
                                    "curp": curp_valor,
                                    "domicilio": str(
                                        fila["domicilio"]
                                    ).strip(),
                                    "seccion_municipal": str(
                                        fila["seccion_municipal"]
                                    ).strip(),
                                    "afiliacion_partido": str(
                                        fila["afiliacion_partido"]
                                    ).strip(),
                                    "creado_por": str(usuario.id),
                                }

                                if edad_valor is not None:
                                    datos["edad"] = edad_valor

                                sb.table("votantes").insert(
                                    datos
                                ).execute()

                                total_importados += 1

                            except Exception as error_fila:
                                total_omitidos += 1

                                if len(errores_importacion) < 10:
                                    errores_importacion.append({
                                        "fila_archivo": int(indice) + 2,
                                        "motivo": str(error_fila),
                                    })

                            progreso = (
                                (total_importados + total_omitidos)
                                / len(df_archivo)
                            )

                            barra.progress(min(progreso, 1.0))
                            estado.write(
                                f"Procesadas "
                                f"{total_importados + total_omitidos} "
                                f"de {len(df_archivo)} filas..."
                            )

                        registrar_evento(
                            sb,
                            usuario.id,
                            (
                                "IMPORTÓ ARCHIVO DE VOTANTES: "
                                f"{total_importados} registros"
                            ),
                        )

                        st.subheader("Resultado de la importación")

                        col1, col2, col3 = st.columns(3)

                        col1.metric(
                            "Filas del archivo",
                            len(df_archivo),
                        )

                        col2.metric(
                            "Importadas",
                            total_importados,
                        )

                        col3.metric(
                            "Omitidas",
                            total_omitidos,
                        )

                        if total_importados:
                            st.success(
                                "Los registros importados ya están "
                                "guardados en Supabase y podrán "
                                "aparecer en las gráficas."
                            )

                        if errores_importacion:
                            st.warning(
                                "Algunas filas no se importaron. "
                                "Consulta los detalles siguientes."
                            )

                            st.dataframe(
                                pd.DataFrame(errores_importacion),
                                use_container_width=True,
                                hide_index=True,
                            )

                        if total_omitidos > 10:
                            st.caption(
                                "Se muestran como máximo 10 errores. "
                                "Los demás registros omitidos pueden "
                                "tener problemas similares."
                            )

                        if total_importados == 0:
                            st.error(
                                "No se importó ninguna fila. "
                                "Revisa los errores mostrados."
                            )

                    except Exception as e:
                        mostrar_error(
                            "Ocurrió un problema durante la importación.",
                            e,
                        )

        except Exception as e:
            mostrar_error(
                "No se pudo leer el archivo. Comprueba el formato "
                "y que contenga las columnas necesarias.",
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
                "Buscar por nombre, CURP, sección o afiliación"
            )

            if busqueda.strip():
                columnas = [
                    columna
                    for columna in [
                        "nombre",
                        "apellido_paterno",
                        "apellido_materno",
                        "curp",
                        "seccion_municipal",
                        "afiliacion_partido",
                    ]
                    if columna in df.columns
                ]

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

            csv = df.to_csv(
                index=False,
            ).encode("utf-8-sig")

            st.download_button(
                "Descargar CSV",
                data=csv,
                file_name="registros_votantes.csv",
                mime="text/csv",
            )

    except Exception as e:
        mostrar_error(
            "No se pudieron consultar los registros.",
            e,
        )


# =========================================================
# GRÁFICAS
# =========================================================

elif opcion == "Gráfica de registros":
    st.title("📊 Gráficas de registros")

    try:
        # Se consulta Supabase cada vez que se abre la sección.
        # Por eso incluye los registros importados.
        df = cargar_votantes(sb)

        if df.empty:
            st.info(
                "No hay registros. Agrega personas o importa "
                "un archivo desde el menú de administrador."
            )
        else:
            st.metric("Total de registros", len(df))

            if COLUMNA_PARTIDO in df.columns:
                conteo_partidos = (
                    df[COLUMNA_PARTIDO]
                    .fillna("Sin dato")
                    .replace("", "Sin dato")
                    .value_counts()
                )

                st.subheader(
                    "Registros por afiliación partidista"
                )
                st.bar_chart(conteo_partidos)

                st.dataframe(
                    conteo_partidos.rename(
                        "Cantidad"
                    ).rename_axis(
                        "Afiliación partidista"
                    ).reset_index(),
                    use_container_width=True,
                    hide_index=True,
                )

            if COLUMNA_SECCION in df.columns:
                conteo_secciones = (
                    df[COLUMNA_SECCION]
                    .fillna("Sin dato")
                    .replace("", "Sin dato")
                    .value_counts()
                )

                st.subheader(
                    "Registros por sección municipal"
                )
                st.bar_chart(conteo_secciones)

            if "edad" in df.columns:
                edades = pd.to_numeric(
                    df["edad"],
                    errors="coerce",
                ).dropna()

                if not edades.empty:
                    st.subheader("Distribución por edad")

                    intervalos = pd.cut(
                        edades,
                        bins=[17, 25, 35, 45, 60, 120],
                        labels=[
                            "18–25",
                            "26–35",
                            "36–45",
                            "46–60",
                            "61 o más",
                        ],
                    )

                    st.bar_chart(
                        intervalos.value_counts().sort_index()
                    )

    except Exception as e:
        mostrar_error(
            "No se pudieron generar las gráficas.",
            e,
        )


# =========================================================
# ELIMINAR PERSONA
# =========================================================

elif opcion == "Eliminar persona" and admin:
    st.title("Eliminar persona")

    st.warning(
        "La eliminación es permanente. "
        "Comprueba el registro antes de confirmar."
    )

    try:
        df = cargar_votantes(sb)

        if df.empty:
            st.info("No hay registros para eliminar.")

        else:
            nombres = (
                df["id"].astype(str)
                + " — "
                + df["nombre"].fillna("").astype(str)
                + " "
                + df["apellido_paterno"].fillna("").astype(str)
            )

            seleccionado = st.selectbox(
                "Selecciona el registro",
                nombres.tolist(),
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
                    id_seleccionado = int(
                        seleccionado.split(" — ", 1)[0]
                    )

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
# ADMINISTRAR PERFILES
# =========================================================

elif opcion == "Administrar perfiles" and admin:
    st.title("Administrar perfiles")

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

        elif (
            not correo_nuevo.strip()
            or "@" not in correo_nuevo
        ):
            st.error("Escribe un correo válido.")

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

                respuesta = (
                    cliente_privado.auth.admin.create_user({
                        "email": correo_nuevo.strip(),
                        "password": password_nuevo,
                        "email_confirm": True,
                        "user_metadata": {
                            "nombre": nombre_nuevo.strip(),
                        },
                    })
                )

                usuario_nuevo = respuesta.user

                if not usuario_nuevo:
                    raise RuntimeError(
                        "Supabase no devolvió el usuario creado."
                    )

                cliente_privado.table("perfiles").insert({
                    "id": str(usuario_nuevo.id),
                    "nombre": nombre_nuevo.strip(),
                    "rol": rol_nuevo,
                }).execute()

                cuenta_creada = True

            except Exception as e:
                if (
                    usuario_nuevo
                    and cliente_privado
                    and not cuenta_creada
                ):
                    try:
                        cliente_privado.auth.admin.delete_user(
                            str(usuario_nuevo.id)
                        )
                    except Exception as error_borrado:
                        st.warning(
                            "No se pudo revertir la cuenta incompleta. "
                            "Revisa Authentication → Users y perfiles."
                        )
                        st.exception(error_borrado)

                mostrar_error(
                    "No se pudo completar la creación de la cuenta.",
                    e,
                )

            if cuenta_creada:
                registrar_evento(
                    sb,
                    usuario.id,
                    f"ADMIN CREÓ CUENTA CON ROL {rol_nuevo}",
                )

                st.success(
                    f"Cuenta creada para {correo_nuevo.strip()}."
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

        perfiles_df = pd.DataFrame(
            respuesta.data or []
        )

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
            "No se pudieron consultar los perfiles.",
            e,
        )


# =========================================================
# HISTORIAL DE ACCESOS
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

        df_historial = pd.DataFrame(
            respuesta.data or []
        )

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
