
import streamlit as st
import pandas as pd
import os
import io
import re
import unicodedata
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import create_client
from reportlab.lib import colors
from reportlab.lib.pagesizes import landscape, letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle

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
    "PRI",
    "PAN",
    "PRD",
    "Morena",
    "Movimiento Naranja",
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
            "creado_en": fecha_actual(),
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


def generar_excel(df):
    """Crea un archivo Excel en memoria a partir de los registros."""
    salida = io.BytesIO()
    with pd.ExcelWriter(salida, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Votantes")
    salida.seek(0)
    return salida.getvalue()


def generar_pdf(df, titulo="Reporte de registros de votantes"):
    """Genera un PDF con los registros mostrados en pantalla."""
    salida = io.BytesIO()
    documento = SimpleDocTemplate(
        salida,
        pagesize=landscape(letter),
        rightMargin=24,
        leftMargin=24,
        topMargin=24,
        bottomMargin=24,
    )
    estilos = getSampleStyleSheet()
    elementos = [
        Paragraph(titulo, estilos["Title"]),
        Spacer(1, 8),
        Paragraph(f"Total de registros en el reporte: {len(df)}", estilos["Normal"]),
        Spacer(1, 10),
    ]

    if df.empty:
        elementos.append(Paragraph("No hay registros para mostrar.", estilos["Normal"]))
    else:
        # Evitar que el PDF tenga columnas excesivamente anchas.
        columnas = [str(c) for c in df.columns]
        filas = [columnas]
        for _, fila in df.iterrows():
            valores = []
            for valor in fila.tolist():
                if pd.isna(valor):
                    valores.append("")
                else:
                    texto = str(valor)
                    valores.append(texto[:100])
            filas.append(valores)

        ancho_util = landscape(letter)[0] - 48
        ancho_columna = ancho_util / max(1, len(columnas))
        tabla = Table(
            filas,
            repeatRows=1,
            colWidths=[ancho_columna] * len(columnas),
        )
        tabla.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#243B53")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 6),
            ("LEADING", (0, 0), (-1, -1), 7),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F2F5F8")]),
            ("LEFTPADDING", (0, 0), (-1, -1), 3),
            ("RIGHTPADDING", (0, 0), (-1, -1), 3),
            ("TOPPADDING", (0, 0), (-1, -1), 3),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ]))
        elementos.append(tabla)

    documento.build(elementos)
    salida.seek(0)
    return salida.getvalue()


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

        col1, col2, col3, col4 = st.columns(4)
        with col1:
            st.metric("Total de registros", len(df))
        with col2:
            st.metric("Tu rol", perfil.get("rol", "Sin rol"))
        with col3:
            secciones = df[COLUMNA_SECCION].nunique() if not df.empty and COLUMNA_SECCION in df.columns else 0
            st.metric("Secciones registradas", int(secciones))
        with col4:
            partidos = df[COLUMNA_PARTIDO].nunique() if not df.empty and COLUMNA_PARTIDO in df.columns else 0
            st.metric("Afiliaciones distintas", int(partidos))

        if not df.empty:
            st.subheader("Resumen y filtros")
            filtros1, filtros2 = st.columns(2)
            if COLUMNA_SECCION in df.columns:
                secciones_disponibles = sorted(
                    df[COLUMNA_SECCION].fillna("").astype(str).replace("", "Sin dato").unique().tolist()
                )
                with filtros1:
                    seccion_filtro = st.selectbox("Filtrar por sección", ["Todas"] + secciones_disponibles)
                if seccion_filtro != "Todas":
                    df = df[df[COLUMNA_SECCION].fillna("").astype(str).replace("", "Sin dato") == seccion_filtro]
            if COLUMNA_PARTIDO in df.columns:
                partidos_disponibles = sorted(
                    df[COLUMNA_PARTIDO].fillna("").astype(str).replace("", "Sin dato").unique().tolist()
                )
                with filtros2:
                    partido_filtro = st.selectbox("Filtrar por afiliación", ["Todas"] + partidos_disponibles)
                if partido_filtro != "Todas":
                    df = df[df[COLUMNA_PARTIDO].fillna("").astype(str).replace("", "Sin dato") == partido_filtro]

            st.caption(f"Registros que coinciden con los filtros: {len(df)}")
            if COLUMNA_PARTIDO in df.columns:
                st.subheader("Registros por afiliación partidista")
                st.bar_chart(df[COLUMNA_PARTIDO].fillna("Sin dato").replace("", "Sin dato").value_counts())
            if COLUMNA_SECCION in df.columns:
                st.subheader("Registros por sección municipal")
                st.bar_chart(df[COLUMNA_SECCION].fillna("Sin dato").replace("", "Sin dato").value_counts())

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

                existente = (
                    sb.table("votantes")
                    .select("id")
                    .eq("curp", datos["curp"])
                    .limit(1)
                    .execute()
                )
                if existente.data:
                    st.warning("Ya existe un registro con esa CURP. No se guardó el duplicado.")
                else:
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
                    registros_validos = []
                    curps_archivo = set()

                    barra = st.progress(0)
                    estado = st.empty()

                    try:
                        # Consultar CURP existentes una sola vez para evitar
                        # duplicados en Supabase y dentro del propio archivo.
                        respuesta_curps = sb.table("votantes").select("curp").execute()
                        curps_existentes = {
                            str(registro.get("curp", "")).strip().upper()
                            for registro in (respuesta_curps.data or [])
                            if registro.get("curp")
                        }

                        for indice, fila in df_archivo.iterrows():
                            try:
                                curp_valor = str(fila["curp"]).strip().upper()
                                if len(curp_valor) != 18:
                                    raise ValueError("La CURP no tiene 18 caracteres.")
                                if curp_valor in curps_existentes:
                                    raise ValueError("La CURP ya existe en la base de datos.")
                                if curp_valor in curps_archivo:
                                    raise ValueError("La CURP está repetida dentro del archivo.")

                                edad_valor = convertir_edad(fila.get("edad"))
                                datos = {
                                    "nombre": str(fila["nombre"]).strip(),
                                    "apellido_paterno": str(fila["apellido_paterno"]).strip(),
                                    "apellido_materno": str(fila.get("apellido_materno", "")).strip(),
                                    "curp": curp_valor,
                                    "domicilio": str(fila["domicilio"]).strip(),
                                    "seccion_municipal": str(fila["seccion_municipal"]).strip(),
                                    "afiliacion_partido": str(fila["afiliacion_partido"]).strip(),
                                    "creado_por": str(usuario.id),
                                }
                                if edad_valor is not None:
                                    datos["edad"] = edad_valor

                                registros_validos.append((int(indice) + 2, datos))
                                curps_archivo.add(curp_valor)

                            except Exception as error_fila:
                                total_omitidos += 1
                                if len(errores_importacion) < 10:
                                    errores_importacion.append({
                                        "fila_archivo": int(indice) + 2,
                                        "motivo": str(error_fila),
                                    })

                            procesadas = indice + 1
                            barra.progress(min(procesadas / len(df_archivo), 1.0))
                            estado.write(f"Validando {procesadas} de {len(df_archivo)} filas...")

                        # Insertar por lotes para reducir llamadas a Supabase.
                        tamano_lote = 200
                        for inicio in range(0, len(registros_validos), tamano_lote):
                            lote = registros_validos[inicio:inicio + tamano_lote]
                            try:
                                sb.table("votantes").insert(
                                    [registro for _, registro in lote]
                                ).execute()
                                total_importados += len(lote)
                            except Exception as error_lote:
                                # Si un lote falla, intentar guardar cada fila
                                # para identificar errores puntuales sin perder las demás.
                                for numero_fila, registro in lote:
                                    try:
                                        sb.table("votantes").insert(registro).execute()
                                        total_importados += 1
                                    except Exception as error_fila:
                                        total_omitidos += 1
                                        if len(errores_importacion) < 10:
                                            errores_importacion.append({
                                                "fila_archivo": numero_fila,
                                                "motivo": str(error_fila or error_lote),
                                            })

                        registrar_evento(
                            sb,
                            usuario.id,
                            f"IMPORTÓ ARCHIVO DE VOTANTES: {total_importados} registros",
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
            st.download_button(
                "Descargar Excel (.xlsx)",
                data=generar_excel(df),
                file_name="reporte_votantes.xlsx",
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )

            st.download_button(
                "Descargar PDF",
                data=generar_pdf(df),
                file_name="reporte_votantes.pdf",
                mime="application/pdf",
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

            export1, export2 = st.columns(2)
            with export1:
                st.download_button(
                    "Descargar reporte Excel",
                    data=generar_excel(df),
                    file_name="reporte_graficas_votantes.xlsx",
                    mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                )
            with export2:
                st.download_button(
                    "Descargar reporte PDF",
                    data=generar_pdf(df, "Reporte de gráficas y registros"),
                    file_name="reporte_graficas_votantes.pdf",
                    mime="application/pdf",
                )

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
    st.title("🗑️ Eliminar persona")
    st.write("Busca a la persona en la tabla y utiliza el botón de su fila para eliminarla.")

    st.warning(
        "La eliminación es permanente. Revisa bien el registro y confirma antes de borrarlo."
    )

    try:
        df = cargar_votantes(sb)

        if df.empty:
            st.info("No hay registros para eliminar.")
            st.session_state.pop("votante_pendiente_eliminar", None)

        else:
            # Buscador: permite localizar registros sin mostrar toda la CURP.
            busqueda_eliminar = st.text_input(
                "🔎 Buscar persona",
                placeholder="Nombre, apellido, CURP, sección, partido o ID...",
                key="buscar_persona_eliminar",
            )

            filtrados = df.copy()
            if busqueda_eliminar.strip():
                termino = busqueda_eliminar.strip().lower()
                columnas_busqueda = [
                    "id",
                    "nombre",
                    "apellido_paterno",
                    "apellido_materno",
                    "curp",
                    "seccion_municipal",
                    "afiliacion_partido",
                ]
                columnas_busqueda = [
                    columna for columna in columnas_busqueda
                    if columna in filtrados.columns
                ]

                coincidencias = pd.Series(False, index=filtrados.index)
                for columna in columnas_busqueda:
                    coincidencias |= (
                        filtrados[columna]
                        .fillna("")
                        .astype(str)
                        .str.lower()
                        .str.contains(termino, regex=False)
                    )
                filtrados = filtrados[coincidencias]

            st.caption(f"Personas encontradas: {len(filtrados)}")

            # Confirmación del registro elegido.
            id_pendiente = st.session_state.get("votante_pendiente_eliminar")
            if id_pendiente is not None:
                seleccionado_df = df[
                    df["id"].astype(str) == str(id_pendiente)
                ]

                if seleccionado_df.empty:
                    st.session_state.pop("votante_pendiente_eliminar", None)
                    st.info("Ese registro ya no está disponible. Actualiza la lista.")
                else:
                    persona = seleccionado_df.iloc[0]
                    nombre_persona = " ".join(
                        str(persona.get(columna) or "").strip()
                        for columna in (
                            "nombre",
                            "apellido_paterno",
                            "apellido_materno",
                        )
                    ).strip()

                    st.warning(
                        f"¿Seguro que deseas eliminar a **{nombre_persona}** "
                        f"(ID {id_pendiente})? Esta acción no se puede deshacer."
                    )

                    confirmar_col, cancelar_col = st.columns(2)

                    with confirmar_col:
                        if st.button(
                            "Sí, eliminar definitivamente",
                            type="primary",
                            key="confirmar_borrar_votante",
                            use_container_width=True,
                        ):
                            try:
                                resultado = (
                                    sb.table("votantes")
                                    .delete()
                                    .eq("id", id_pendiente)
                                    .execute()
                                )

                                # Se vuelve a consultar para verificar que ya no exista.
                                verificacion = (
                                    sb.table("votantes")
                                    .select("id")
                                    .eq("id", id_pendiente)
                                    .limit(1)
                                    .execute()
                                )

                                if not verificacion.data:
                                    registrar_evento(
                                        sb,
                                        usuario.id,
                                        f"ELIMINÓ UN REGISTRO (ID {id_pendiente})",
                                    )
                                    st.session_state.pop(
                                        "votante_pendiente_eliminar", None
                                    )
                                    st.success("Registro eliminado correctamente.")
                                    st.rerun()
                                else:
                                    st.error(
                                        "No se pudo confirmar la eliminación. "
                                        "Revisa los permisos de Supabase y vuelve a intentarlo."
                                    )
                            except Exception as error_eliminar:
                                mostrar_error(
                                    "No se pudo eliminar el registro.",
                                    error_eliminar,
                                )

                    with cancelar_col:
                        if st.button(
                            "Cancelar",
                            key="cancelar_borrar_votante",
                            use_container_width=True,
                        ):
                            st.session_state.pop(
                                "votante_pendiente_eliminar", None
                            )
                            st.rerun()

            st.divider()
            st.subheader("Registros")

            if filtrados.empty:
                st.info("No se encontraron personas con esa búsqueda.")
            else:
                # Tabla visual con una acción independiente por fila.
                encabezados = st.columns([0.7, 2.5, 1.2, 1.5, 1.2])
                encabezados[0].markdown("**ID**")
                encabezados[1].markdown("**Nombre completo**")
                encabezados[2].markdown("**Sección**")
                encabezados[3].markdown("**Afiliación**")
                encabezados[4].markdown("**Acción**")
                st.divider()

                for _, fila in filtrados.iterrows():
                    id_persona = fila.get("id")
                    nombre_completo = " ".join(
                        str(fila.get(columna) or "").strip()
                        for columna in (
                            "nombre",
                            "apellido_paterno",
                            "apellido_materno",
                        )
                    ).strip()
                    seccion = str(fila.get("seccion_municipal") or "Sin sección")
                    afiliacion = str(fila.get("afiliacion_partido") or "Sin especificar")

                    c_id, c_nombre, c_seccion, c_partido, c_accion = st.columns(
                        [0.7, 2.5, 1.2, 1.5, 1.2]
                    )
                    c_id.write(str(id_persona))
                    c_nombre.write(nombre_completo)
                    c_seccion.write(seccion)
                    c_partido.write(afiliacion)

                    if c_accion.button(
                        "🗑️ Eliminar",
                        key=f"seleccionar_borrar_votante_{id_persona}",
                        use_container_width=True,
                    ):
                        st.session_state["votante_pendiente_eliminar"] = id_persona
                        st.rerun()

    except Exception as e:
        mostrar_error(
            "No se pudo cargar o eliminar el registro.",
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
            .order("creado_en", desc=True)
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
