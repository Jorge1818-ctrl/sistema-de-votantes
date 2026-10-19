import streamlit as st
import pandas as pd
import os
import json
import uuid
import hmac
import hashlib
import secrets
from datetime import datetime
from zoneinfo import ZoneInfo

# ================= CONFIGURACIÓN =================

ARCHIVO_VOTANTES = "votantes.csv"
ARCHIVO_USUARIOS = "usuarios.json"
ARCHIVO_ACCESOS = "accesos.txt"
ZONA_HORARIA = ZoneInfo("America/Mexico_City")

COLUMNAS = [
    "ID", "Nombre", "Edad", "CURP", "Domicilio",
    "Seccion", "Partido", "Autorizacion"
]

PARTIDOS = [
    "Partido A", "Partido B", "Partido C",
    "Partido D", "Otro"
]

st.set_page_config(
    page_title="Sistema de Registro de Votantes",
    page_icon="📊",
    layout="wide"
)


def ahora():
    return datetime.now(ZONA_HORARIA).strftime("%Y-%m-%d %H:%M:%S")


# ================= ARCHIVOS DE USUARIOS =================

def cargar_usuarios():
    if not os.path.exists(ARCHIVO_USUARIOS):
        return {}

    try:
        with open(ARCHIVO_USUARIOS, "r", encoding="utf-8") as f:
            usuarios = json.load(f)
        return usuarios if isinstance(usuarios, dict) else {}
    except (json.JSONDecodeError, OSError):
        st.error("No se pudo leer usuarios.json. No se modificarán las cuentas.")
        st.stop()


def guardar_usuarios(usuarios):
    temporal = ARCHIVO_USUARIOS + ".tmp"
    with open(temporal, "w", encoding="utf-8") as f:
        json.dump(usuarios, f, ensure_ascii=False, indent=2)
    os.replace(temporal, ARCHIVO_USUARIOS)


def crear_hash(contrasena, sal=None):
    if sal is None:
        sal = secrets.token_hex(16)
    resultado = hashlib.pbkdf2_hmac(
        "sha256",
        contrasena.encode("utf-8"),
        bytes.fromhex(sal),
        300000
    )
    return sal, resultado.hex()


def verificar_contrasena(contrasena, usuario):
    _, hash_calculado = crear_hash(contrasena, usuario["sal"])
    return hmac.compare_digest(hash_calculado, usuario["hash"])


def crear_usuario(usuarios, nombre, contrasena, rol="usuario"):
    sal, hash_contrasena = crear_hash(contrasena)
    usuarios[nombre] = {
        "sal": sal,
        "hash": hash_contrasena,
        "rol": rol,
        "activo": True
    }
    guardar_usuarios(usuarios)


# ================= REGISTRO DE ACCESOS =================

def registrar_acceso(usuario, resultado="INICIO DE SESION EXITOSO"):
    # Nunca guardar contraseñas en este archivo.
    linea = f"{ahora()} | Usuario: {usuario} | Evento: {resultado}\n"
    with open(ARCHIVO_ACCESOS, "a", encoding="utf-8") as f:
        f.write(linea)


def leer_accesos():
    if not os.path.exists(ARCHIVO_ACCESOS):
        return "Todavía no hay accesos registrados."
    try:
        with open(ARCHIVO_ACCESOS, "r", encoding="utf-8") as f:
            return f.read()
    except OSError:
        return "No se pudo leer el historial de accesos."


# ================= REGISTRO DE VOTANTES =================

def cargar_datos():
    if not os.path.exists(ARCHIVO_VOTANTES):
        return pd.DataFrame(columns=COLUMNAS)

    try:
        datos = pd.read_csv(
            ARCHIVO_VOTANTES,
            dtype=str,
            encoding="utf-8-sig",
            keep_default_na=False
        )
        for columna in COLUMNAS:
            if columna not in datos.columns:
                datos[columna] = ""
        return datos[COLUMNAS]
    except pd.errors.EmptyDataError:
        return pd.DataFrame(columns=COLUMNAS)
    except (pd.errors.ParserError, OSError):
        st.error("No se pudo leer votantes.csv.")
        st.stop()


def guardar_datos(datos):
    datos.to_csv(
        ARCHIVO_VOTANTES,
        index=False,
        encoding="utf-8-sig"
    )


# ================= CONFIGURACIÓN DEL ADMIN INICIAL =================

if not os.path.exists(ARCHIVO_USUARIOS):
    st.title("🔐 Configuración inicial")
    st.write("Crea la cuenta del administrador.")

    with st.form("crear_admin"):
        admin = st.text_input("Nombre de administrador")
        clave = st.text_input("Contraseña (mínimo 12 caracteres)", type="password")
        repetir = st.text_input("Confirmar contraseña", type="password")
        crear = st.form_submit_button("Crear administrador")

    if crear:
        if not admin.strip():
            st.error("Escribe un nombre de usuario.")
        elif len(clave) < 12:
            st.error("La contraseña debe tener al menos 12 caracteres.")
        elif clave != repetir:
            st.error("Las contraseñas no coinciden.")
        else:
            crear_usuario({}, admin.strip(), clave, rol="admin")
            registrar_acceso(admin.strip(), "CUENTA ADMINISTRADORA CREADA")
            st.session_state["usuario"] = admin.strip()
            st.rerun()
    st.stop()


# ================= LOGIN =================

usuarios = cargar_usuarios()

if "usuario" not in st.session_state:
    st.session_state["usuario"] = None

if st.session_state["usuario"] is not None:
    cuenta_actual = usuarios.get(st.session_state["usuario"])
    if not cuenta_actual or not cuenta_actual.get("activo", False):
        st.session_state["usuario"] = None
        st.rerun()

if st.session_state["usuario"] is None:
    st.title("🔐 Inicio de sesión")
    st.write("Ingresa con una cuenta autorizada por el administrador.")

    with st.form("login"):
        nombre_usuario = st.text_input("Usuario")
        contrasena = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Iniciar sesión")

    if entrar:
        nombre_usuario = nombre_usuario.strip()
        cuenta = usuarios.get(nombre_usuario)

        if (
            cuenta
            and cuenta.get("activo", False)
            and verificar_contrasena(contrasena, cuenta)
        ):
            registrar_acceso(nombre_usuario)
            st.session_state["usuario"] = nombre_usuario
            st.rerun()
        else:
            # Se registra el intento fallido sin guardar la contraseña.
            registrar_acceso(
                nombre_usuario if nombre_usuario else "(usuario vacío)",
                "INTENTO FALLIDO"
            )
            st.error("Usuario o contraseña incorrectos, o cuenta desactivada.")
    st.stop()


# ================= APLICACIÓN =================

usuario_actual = st.session_state["usuario"]
usuarios = cargar_usuarios()
rol_actual = usuarios[usuario_actual]["rol"]

st.title("📊 Sistema de Registro de Votantes")
st.sidebar.success(f"Sesión: {usuario_actual}")
st.sidebar.caption(f"Rol: {rol_actual}")

if st.sidebar.button("Cerrar sesión"):
    st.session_state["usuario"] = None
    st.rerun()

opciones = [
    "Inicio",
    "Registrar persona",
    "Consultar registros",
    "Eliminar persona",
    "Gráfica de partidos"
]
if rol_actual == "admin":
    opciones += ["Administrar usuarios", "Historial de accesos"]

opcion = st.sidebar.radio("Menú", opciones)
datos = cargar_datos()


if opcion == "Inicio":
    st.subheader("Panel principal")
    col1, col2 = st.columns(2)
    col1.metric("Personas registradas", len(datos))
    col2.metric("Partidos registrados", datos["Partido"].nunique() if not datos.empty else 0)

    if not datos.empty:
        # No mostrar CURP ni domicilio en la vista general.
        st.dataframe(
            datos.drop(columns=["CURP", "Domicilio", "Autorizacion"]),
            use_container_width=True,
            hide_index=True
        )
    else:
        st.info("Todavía no hay registros.")


elif opcion == "Registrar persona":
    st.subheader("Registrar persona")
    with st.form("registro"):
        nombre = st.text_input("Nombre completo")
        edad = st.number_input("Edad", min_value=18, max_value=120, value=18)
        curp = st.text_input("CURP", max_chars=18).strip().upper()
        domicilio = st.text_input("Domicilio")
        seccion = st.text_input("Sección electoral")
        partido = st.selectbox("Partido asociado al registro", PARTIDOS)
        otro = st.text_input("Nombre del partido") if partido == "Otro" else ""
        autorizacion = st.checkbox("Tengo autorización para guardar estos datos.")
        guardar = st.form_submit_button("Guardar persona")

    if guardar:
        if not nombre.strip():
            st.error("Escribe el nombre.")
        elif not curp:
            st.error("Escribe la CURP.")
        elif not domicilio.strip():
            st.error("Escribe el domicilio.")
        elif not seccion.strip():
            st.error("Escribe la sección electoral.")
        elif partido == "Otro" and not otro.strip():
            st.error("Escribe el nombre del partido.")
        elif not autorizacion:
            st.error("Confirma que tienes autorización.")
        else:
            nuevo = {
                "ID": str(uuid.uuid4()),
                "Nombre": nombre.strip(),
                "Edad": str(int(edad)),
                "CURP": curp,
                "Domicilio": domicilio.strip(),
                "Seccion": seccion.strip(),
                "Partido": otro.strip() if partido == "Otro" else partido,
                "Autorizacion": "Sí"
            }
            datos = pd.concat([datos, pd.DataFrame([nuevo])], ignore_index=True)
            guardar_datos(datos)
            st.success("Persona registrada y guardada en votantes.csv.")
            st.rerun()


elif opcion == "Consultar registros":
    st.subheader("Consultar personas")
    if datos.empty:
        st.info("No hay registros.")
    else:
        busqueda = st.text_input("Buscar por nombre")
        filtrados = datos[
            datos["Nombre"].str.contains(busqueda, case=False, na=False, regex=False)
        ]
        st.dataframe(
            filtrados.drop(columns=["Autorizacion"]),
            use_container_width=True,
            hide_index=True
        )
        st.download_button(
            "Descargar registros CSV",
            data=filtrados.to_csv(index=False).encode("utf-8-sig"),
            file_name="registros_votantes.csv",
            mime="text/csv"
        )


elif opcion == "Eliminar persona":
    st.subheader("Eliminar registro")
    if datos.empty:
        st.info("No hay registros que eliminar.")
    else:
        opciones_registro = {
            f"{fila['Nombre']} | Sección {fila['Seccion']} | ID: {fila['ID']}": fila["ID"]
            for _, fila in datos.iterrows()
        }
        seleccionado = st.selectbox("Selecciona a la persona", list(opciones_registro.keys()))
        confirmar = st.checkbox("Confirmo que deseo eliminar el registro.")
        if st.button("Eliminar", type="primary"):
            if confirmar:
                id_eliminar = opciones_registro[seleccionado]
                datos = datos[datos["ID"] != id_eliminar].copy()
                guardar_datos(datos)
                st.success("Registro eliminado.")
                st.rerun()
            else:
                st.warning("Confirma la eliminación.")


elif opcion == "Gráfica de partidos":
    st.subheader("Cantidad de registros por partido")
    if datos.empty:
        st.info("Registra personas para generar la gráfica.")
    else:
        conteo = datos["Partido"].value_counts()
        st.bar_chart(conteo, x_label="Partido", y_label="Cantidad de registros")
        st.dataframe(
            conteo.rename("Cantidad").reset_index(),
            use_container_width=True,
            hide_index=True
        )
        st.caption("La gráfica muestra registros administrativos, no votos emitidos ni resultados oficiales.")


elif opcion == "Administrar usuarios" and rol_actual == "admin":
    st.subheader("Administrar acceso al sistema")

    with st.form("nuevo_usuario"):
        nuevo_nombre = st.text_input("Nombre del nuevo usuario")
        nueva_clave = st.text_input("Contraseña (mínimo 12 caracteres)", type="password")
        repetir_clave = st.text_input("Confirmar contraseña", type="password")
        crear = st.form_submit_button("Autorizar usuario")

    if crear:
        nuevo_nombre = nuevo_nombre.strip()
        if not nuevo_nombre:
            st.error("Escribe el nombre del usuario.")
        elif nuevo_nombre in usuarios:
            st.error("Ese usuario ya existe.")
        elif len(nueva_clave) < 12:
            st.error("La contraseña debe tener al menos 12 caracteres.")
        elif nueva_clave != repetir_clave:
            st.error("Las contraseñas no coinciden.")
        else:
            crear_usuario(usuarios, nuevo_nombre, nueva_clave, rol="usuario")
            st.success("Usuario autorizado.")
            st.rerun()

    st.markdown("### Usuarios existentes")
    for nombre, info in list(usuarios.items()):
        c1, c2, c3 = st.columns([3, 2, 2])
        c1.write(f"**{nombre}**")
        c2.write(f"{info['rol']} — {'Activo' if info['activo'] else 'Desactivado'}")
        if nombre != usuario_actual:
            if info["activo"]:
                if c3.button("Desactivar", key=f"off_{nombre}"):
                    usuarios[nombre]["activo"] = False
                    guardar_usuarios(usuarios)
                    st.rerun()
            else:
                if c3.button("Activar", key=f"on_{nombre}"):
                    usuarios[nombre]["activo"] = True
                    guardar_usuarios(usuarios)
                    st.rerun()
        else:
            c3.caption("Sesión actual")


elif opcion == "Historial de accesos" and rol_actual == "admin":
    st.subheader("Historial de inicios de sesión")
    contenido = leer_accesos()
    st.text_area("Eventos registrados (no se guardan contraseñas)", contenido, height=350)
    st.download_button(
        "Descargar accesos.txt",
        data=contenido,
        file_name="accesos.txt",
        mime="text/plain"
    )
    st.caption(
        "El historial puede incluir nombres de usuario e intentos fallidos. "
        "Limita su acceso a administradores."
    )


