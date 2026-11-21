import os
from datetime import datetime
from zoneinfo import ZoneInfo

import pandas as pd
import streamlit as st
from supabase import create_client

st.set_page_config(page_title="Sistema de Pase de Lista", page_icon="🔢", layout="wide", initial_sidebar_state="expanded")

TZ = ZoneInfo("America/Mexico_City")
ESTADOS = ["Pendiente", "Ya votó", "No ha votado"]
COLUMNAS = ["numero", "seccion", "nombre", "apellidos", "curp", "domicilio", "partido", "estado"]


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
        cliente.table("registro_accesos").insert({"usuario_id": str(usuario_id), "evento": evento, "exitoso": exitoso, "creado_en": fecha_actual()}).execute()
    except Exception as error:
        print(f"No se pudo registrar el evento: {error}")


def obtener_perfil(cliente, usuario_id):
    r = cliente.table("perfiles").select("id,nombre,rol").eq("id", str(usuario_id)).limit(1).execute()
    return (r.data or [None])[0]


def cargar_votantes(cliente):
    filas, inicio, limite = [], 0, 1000
    while True:
        r = cliente.table("votantes").select(",".join(COLUMNAS)).order("numero").range(inicio, inicio + limite - 1).execute()
        datos = r.data or []
        filas.extend(datos)
        if len(datos) < limite:
            break
        inicio += limite
    return pd.DataFrame(filas, columns=COLUMNAS)


def mostrar_error(mensaje, error):
    st.error(mensaje)
    st.caption("Detalle técnico:")
    st.exception(error)


def normalizar_numero(valor, seccion):
    digitos = str(valor or "").strip()
    if not digitos.isdigit() or not 1 <= len(digitos) <= 4:
        return None
    return digitos.zfill(4) + seccion


def cerrar_sesion():
    cliente, usuario = st.session_state.get("cliente"), st.session_state.get("usuario")
    if cliente and usuario:
        registrar_evento(cliente, usuario.id, "CIERRE DE SESIÓN")
        try:
            cliente.auth.sign_out()
        except Exception:
            pass
    for llave in ("cliente", "usuario", "perfil", "registro_encontrado"):
        st.session_state.pop(llave, None)
    st.rerun()


def etiqueta_numero(numero):
    return str(numero or "")


# ------------------------- ACCESO -------------------------
for llave, valor in (("cliente", None), ("usuario", None), ("perfil", None)):
    if llave not in st.session_state:
        st.session_state[llave] = valor

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
                respuesta = cliente.auth.sign_in_with_password({"email": correo.strip(), "password": password})
                usuario = respuesta.user
                if not usuario:
                    raise RuntimeError("Supabase no devolvió el usuario.")
                perfil = obtener_perfil(cliente, usuario.id)
                if not perfil:
                    cliente.auth.sign_out()
                    raise RuntimeError("Tu cuenta no tiene perfil en public.perfiles.")
                if perfil.get("rol") not in ("admin", "consulta"):
                    cliente.auth.sign_out()
                    raise RuntimeError("El rol debe ser admin o consulta.")
                st.session_state.cliente, st.session_state.usuario, st.session_state.perfil = cliente, usuario, perfil
                registrar_evento(cliente, usuario.id, "INICIO DE SESIÓN")
                st.rerun()
            except Exception as error:
                mostrar_error("No se pudo iniciar sesión.", error)
    st.stop()

sb, usuario = st.session_state.cliente, st.session_state.usuario
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
    opciones += ["Administrar registros", "Administrar perfiles", "Historial de accesos"]
opcion = st.sidebar.radio("Menú", opciones)
st.sidebar.button("Cerrar sesión", on_click=cerrar_sesion, use_container_width=True)

# ------------------------- INICIO -------------------------
if opcion == "Inicio":
    st.title("Bienvenido al sistema")
    st.write("Resumen general de los registros y del pase de lista.")
    try:
        df = cargar_votantes(sb)
        conteo = df.estado.value_counts() if not df.empty else pd.Series(dtype=int)
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total de registros", len(df))
        c2.metric("Ya votó", int(conteo.get("Ya votó", 0)))
        c3.metric("No ha votado", int(conteo.get("No ha votado", 0)))
        c4.metric("Pendientes", int(conteo.get("Pendiente", 0)))
        st.subheader("Resumen por sección")
        if df.empty:
            st.info("No hay registros.")
        else:
            resumen = df.groupby(["seccion", "estado"]).size().unstack(fill_value=0).reindex(columns=ESTADOS, fill_value=0)
            st.dataframe(resumen, use_container_width=True)
            st.dataframe(df, use_container_width=True, hide_index=True)
    except Exception as error:
        mostrar_error("No se pudieron consultar los registros.", error)

# ------------------------- PASE DE LISTA -------------------------
elif opcion == "Pase de lista":
    st.title("📝 Pase de lista")
    st.write("Busca por número y sección. Ejemplo: 0025 y C1 = 0025C1.")
    try:
        df = cargar_votantes(sb)
        with st.form("buscar_registro"):
            col1, col2 = st.columns(2)
            entrada = col1.text_input("Número (1 a 4 cifras)", max_chars=4, placeholder="0025")
            seccion = col2.selectbox("Sección", ["B", "C1", "C2"])
            buscar = st.form_submit_button("Buscar registro", use_container_width=True)
        if buscar:
            clave = normalizar_numero(entrada, seccion)
            if not clave:
                st.warning("Escribe de 1 a 4 cifras numéricas.")
                st.session_state.pop("registro_encontrado", None)
            elif clave not in set(df.numero.astype(str)):
                st.error(f"No se encontró el registro {clave}.")
                st.session_state.pop("registro_encontrado", None)
            else:
                st.session_state.registro_encontrado = clave
        clave_actual = st.session_state.get("registro_encontrado")
        if clave_actual:
            fila = df[df.numero.astype(str) == clave_actual]
            if not fila.empty:
                reg = fila.iloc[0].to_dict()
                st.success("Registro encontrado.")
                st.subheader(f"Número {reg['numero']} · Sección {reg['seccion']}")
                st.write(f"**Nombre:** {reg.get('nombre') or ''} {reg.get('apellidos') or ''}")
                st.write(f"**Partido:** {reg.get('partido') or 'No especificado'}")
                st.write(f"**Estado actual:** {reg.get('estado') or 'Pendiente'}")
                with st.form("actualizar_estado"):
                    estado_actual = reg.get("estado") or "Pendiente"
                    nuevo_estado = st.selectbox("Actualizar estado", ESTADOS, index=ESTADOS.index(estado_actual) if estado_actual in ESTADOS else 0)
                    guardar = st.form_submit_button("Guardar estado", use_container_width=True)
                if guardar:
                    try:
                        sb.table("votantes").update({"estado": nuevo_estado}).eq("numero", clave_actual).execute()
                        registrar_evento(sb, usuario.id, f"ACTUALIZÓ ESTADO {clave_actual}: {nuevo_estado}")
                        st.success("Estado actualizado.")
                        st.rerun()
                    except Exception as error:
                        mostrar_error("No se pudo actualizar el estado.", error)
        st.divider()
        st.subheader("Lista general")
        a, b = st.columns(2)
        filtro_seccion = a.selectbox("Filtrar por sección", ["Todas", "B", "C1", "C2"])
        filtro_estado = b.selectbox("Filtrar por estado", ["Todos"] + ESTADOS)
        vista = df.copy()
        if filtro_seccion != "Todas":
            vista = vista[vista.seccion == filtro_seccion]
        if filtro_estado != "Todos":
            vista = vista[vista.estado == filtro_estado]
        st.dataframe(vista, use_container_width=True, hide_index=True)
        st.download_button("Descargar CSV", vista.to_csv(index=False).encode("utf-8-sig"), "pase_lista.csv", "text/csv", use_container_width=True)
    except Exception as error:
        mostrar_error("No se pudo consultar el pase de lista.", error)

# ------------------------- GRÁFICAS -------------------------
elif opcion == "Gráficas":
    st.title("📊 Gráficas del pase de lista")
    try:
        df = cargar_votantes(sb)
        if df.empty:
            st.info("No hay registros.")
        else:
            st.subheader("Estados por sección")
            tabla = df.groupby(["seccion", "estado"]).size().unstack(fill_value=0).reindex(columns=ESTADOS, fill_value=0)
            st.bar_chart(tabla)
            st.dataframe(tabla, use_container_width=True)
            st.subheader("Totales por sección")
            st.bar_chart(df.groupby("seccion").size())
    except Exception as error:
        mostrar_error("No se pudieron generar las gráficas.", error)

# ------------------------- ADMINISTRAR REGISTROS -------------------------
elif opcion == "Administrar registros" and admin:
    st.title("🛠️ Administrar registros")
    st.caption("Solo el administrador puede crear, editar o eliminar datos personales.")
    with st.expander("Agregar registro", expanded=True):
        with st.form("crear_registro"):
            c1, c2 = st.columns(2)
            num = c1.text_input("Número (1 a 4 cifras)", max_chars=4)
            sec = c2.selectbox("Sección", ["B", "C1", "C2"], key="crear_seccion")
            nombre = st.text_input("Nombre")
            apellidos = st.text_input("Apellidos")
            curp = st.text_input("CURP")
            domicilio = st.text_input("Domicilio")
            partido = st.text_input("Partido (si corresponde)")
            estado = st.selectbox("Estado inicial", ESTADOS)
            crear = st.form_submit_button("Crear registro", use_container_width=True)
        if crear:
            clave = normalizar_numero(num, sec)
            if not clave:
                st.error("Número inválido.")
            else:
                try:
                    sb.table("votantes").insert({"numero": clave, "seccion": sec, "nombre": nombre.strip(), "apellidos": apellidos.strip(), "curp": curp.strip().upper(), "domicilio": domicilio.strip(), "partido": partido.strip(), "estado": estado}).execute()
                    registrar_evento(sb, usuario.id, f"CREÓ REGISTRO {clave}")
                    st.success(f"Registro {clave} creado.")
                    st.rerun()
                except Exception as error:
                    mostrar_error("No se pudo crear el registro. Verifica que el número no exista.", error)
    st.divider()
    try:
        df = cargar_votantes(sb)
        if df.empty:
            st.info("No hay registros.")
        else:
            st.subheader("Editar registro")
            claves = df.numero.astype(str).tolist()
            seleccionado = st.selectbox("Selecciona el número", claves)
            actual = df[df.numero.astype(str) == seleccionado].iloc[0].to_dict()
            with st.form("editar_registro"):
                nombre_e = st.text_input("Nombre", value=actual.get("nombre") or "")
                apellidos_e = st.text_input("Apellidos", value=actual.get("apellidos") or "")
                curp_e = st.text_input("CURP", value=actual.get("curp") or "")
                domicilio_e = st.text_input("Domicilio", value=actual.get("domicilio") or "")
                partido_e = st.text_input("Partido", value=actual.get("partido") or "")
                estado_e = st.selectbox("Estado", ESTADOS, index=ESTADOS.index(actual.get("estado")) if actual.get("estado") in ESTADOS else 0)
                guardar_e = st.form_submit_button("Guardar cambios", use_container_width=True)
            if guardar_e:
                try:
                    sb.table("votantes").update({"nombre": nombre_e.strip(), "apellidos": apellidos_e.strip(), "curp": curp_e.strip().upper(), "domicilio": domicilio_e.strip(), "partido": partido_e.strip(), "estado": estado_e}).eq("numero", seleccionado).execute()
                    registrar_evento(sb, usuario.id, f"EDITÓ REGISTRO {seleccionado}")
                    st.success("Cambios guardados.")
                    st.rerun()
                except Exception as error:
                    mostrar_error("No se pudieron guardar los cambios.", error)
            st.subheader("Importar desde Excel o CSV")
            archivo = st.file_uploader("Selecciona un archivo .xlsx o .csv", type=["xlsx", "csv"])
            if archivo is not None and st.button("Importar registros", use_container_width=True):
                try:
                    importado = pd.read_csv(archivo, dtype=str) if archivo.name.lower().endswith(".csv") else pd.read_excel(archivo, dtype=str)
                    requeridas = {"numero", "seccion"}
                    if not requeridas.issubset(set(importado.columns.str.lower())):
                        raise ValueError("El archivo debe incluir columnas numero y seccion. Las demás columnas son: nombre, apellidos, curp, domicilio, partido y estado.")
                    importado.columns = [str(c).strip().lower() for c in importado.columns]
                    filas = []
                    for _, r in importado.iterrows():
                        sec_i = str(r.get("seccion", "")).strip().upper()
                        clave_i = normalizar_numero(r.get("numero", ""), sec_i)
                        if sec_i not in ("B", "C1", "C2") or not clave_i:
                            continue
                        filas.append({"numero": clave_i, "seccion": sec_i, "nombre": str(r.get("nombre", "") or ""), "apellidos": str(r.get("apellidos", "") or ""), "curp": str(r.get("curp", "") or "").upper(), "domicilio": str(r.get("domicilio", "") or ""), "partido": str(r.get("partido", "") or ""), "estado": str(r.get("estado", "Pendiente") or "Pendiente")})
                    if not filas:
                        raise ValueError("No se encontraron filas válidas.")
                    for inicio in range(0, len(filas), 200):
                        sb.table("votantes").upsert(filas[inicio:inicio + 200], on_conflict="numero").execute()
                    registrar_evento(sb, usuario.id, f"IMPORTÓ {len(filas)} REGISTROS")
                    st.success(f"Se procesaron {len(filas)} registros.")
                    st.rerun()
                except Exception as error:
                    mostrar_error("No se pudo importar el archivo.", error)
            st.subheader("Eliminar registro")
            confirmar = st.checkbox(f"Confirmo eliminar permanentemente {seleccionado}.")
            if st.button("Eliminar seleccionado", disabled=not confirmar, type="secondary", use_container_width=True):
                try:
                    sb.table("votantes").delete().eq("numero", seleccionado).execute()
                    registrar_evento(sb, usuario.id, f"ELIMINÓ REGISTRO {seleccionado}")
                    st.success(f"Se eliminó {seleccionado}.")
                    st.rerun()
                except Exception as error:
                    mostrar_error("No se pudo eliminar el registro.", error)
    except Exception as error:
        mostrar_error("No se pudieron administrar los registros.", error)

# ------------------------- ADMINISTRAR PERFILES -------------------------
elif opcion == "Administrar perfiles" and admin:
    st.title("Administrar perfiles")
    with st.form("crear_usuario"):
        nombre_nuevo = st.text_input("Nombre de la cuenta")
        correo_nuevo = st.text_input("Correo electrónico")
        password_nuevo = st.text_input("Contraseña inicial (mínimo 8 caracteres)", type="password")
        rol_nuevo = st.selectbox("Rol", ["consulta", "admin"])
        crear = st.form_submit_button("Crear cuenta", use_container_width=True)
    if crear:
        if not nombre_nuevo.strip() or "@" not in correo_nuevo.strip() or len(password_nuevo) < 8:
            st.error("Revisa el nombre, correo y contraseña (mínimo 8 caracteres).")
        else:
            privado, usuario_nuevo, cuenta_creada = None, None, False
            try:
                privado = cliente_administrador()
                respuesta = privado.auth.admin.create_user({"email": correo_nuevo.strip(), "password": password_nuevo, "email_confirm": True, "user_metadata": {"nombre": nombre_nuevo.strip()}})
                usuario_nuevo = respuesta.user
                if not usuario_nuevo:
                    raise RuntimeError("Supabase no devolvió el usuario creado.")
                privado.table("perfiles").insert({"id": str(usuario_nuevo.id), "nombre": nombre_nuevo.strip(), "rol": rol_nuevo}).execute()
                cuenta_creada = True
            except Exception as error:
                if usuario_nuevo and privado and not cuenta_creada:
                    try:
                        privado.auth.admin.delete_user(str(usuario_nuevo.id))
                    except Exception:
                        pass
                mostrar_error("No se pudo crear la cuenta.", error)
            if cuenta_creada:
                registrar_evento(sb, usuario.id, f"CREÓ CUENTA CON ROL {rol_nuevo}")
                st.success("Cuenta creada.")
                st.rerun()
    st.divider()
    try:
        r = sb.table("perfiles").select("id,nombre,rol").order("nombre").execute()
        st.dataframe(pd.DataFrame(r.data or []), use_container_width=True, hide_index=True)
    except Exception as error:
        mostrar_error("No se pudieron consultar los perfiles.", error)

# ------------------------- HISTORIAL -------------------------
elif opcion == "Historial de accesos" and admin:
    st.title("Historial de accesos")
    try:
        r = sb.table("registro_accesos").select("*").order("creado_en", desc=True).execute()
        historial = pd.DataFrame(r.data or [])
        if historial.empty:
            st.info("Todavía no hay eventos registrados.")
        else:
            st.dataframe(historial, use_container_width=True, hide_index=True)
            st.download_button("Descargar historial CSV", historial.to_csv(index=False).encode("utf-8-sig"), "historial_accesos.csv", "text/csv")
    except Exception as error:
        mostrar_error("No se pudo consultar el historial.", error)
