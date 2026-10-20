import streamlit as st
import pandas as pd
from datetime import datetime
from zoneinfo import ZoneInfo
from supabase import create_client

st.set_page_config(page_title="Sistema de Registro de Votantes", page_icon="📊", layout="wide")
TZ = ZoneInfo("America/Mexico_City")
PARTIDOS = ["Partido A", "Partido B", "Partido C", "Partido D", "Otro"]


def ahora():
    return datetime.now(TZ).isoformat()


def config():
    try:
        return st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_ANON_KEY"]
    except Exception:
        st.error("Configura SUPABASE_URL y SUPABASE_ANON_KEY en Streamlit → Settings → Secrets.")
        st.stop()


def nuevo_cliente():
    url, key = config()
    # Cliente nuevo por sesión/rerun para no compartir tokens entre usuarios.
    sb = create_client(url, key)
    access = st.session_state.get("access_token")
    refresh = st.session_state.get("refresh_token")
    if access and refresh:
        try:
            sb.auth.set_session(access, refresh)
            ses = sb.auth.get_session()
            if ses:
                st.session_state["access_token"] = ses.access_token
                st.session_state["refresh_token"] = ses.refresh_token
        except Exception:
            for k in ("access_token", "refresh_token", "usuario_id", "correo"):
                st.session_state.pop(k, None)
            st.rerun()
    return sb


def registrar_evento(sb, uid, evento, exitoso=True):
    try:
        sb.table("registro_accesos").insert({
            "usuario_id": uid, "evento": evento, "exitoso": exitoso, "creado_en": ahora()
        }).execute()
    except Exception:
        st.warning("No se pudo guardar el evento en el historial.")


def perfil_usuario(sb, uid):
    r = sb.table("perfiles").select("id,nombre,rol").eq("id", uid).limit(1).execute()
    return r.data[0] if r.data else None


def error_seguro(error, mensaje):
    st.error(mensaje + ". Revisa la configuración y las políticas de Supabase.")
    with st.expander("Detalles técnicos"):
        st.code(str(error)[:1000])


def cargar_votantes(sb):
    r = sb.table("votantes").select(
        "id,nombre,apellido_paterno,apellido_materno,edad,curp,domicilio,"
        "seccion_municipal,afiliacion_partido,creado_en"
    ).order("creado_en", desc=True).execute()
    return pd.DataFrame(r.data or [])


st.title("📊 Sistema de Registro de Votantes")

# Inicio de sesión con Supabase Auth: usa el correo creado en Authentication → Users.
if not st.session_state.get("access_token"):
    st.subheader("🔐 Inicio de sesión")
    st.info("Ingresa con el correo y contraseña creados en Supabase Authentication.")
    with st.form("login"):
        correo = st.text_input("Correo electrónico")
        password = st.text_input("Contraseña", type="password")
        entrar = st.form_submit_button("Iniciar sesión", type="primary")
    if entrar:
        if not correo.strip() or not password:
            st.error("Escribe el correo y la contraseña.")
        else:
            url, key = config()
            auth = create_client(url, key)
            try:
                resp = auth.auth.sign_in_with_password({"email": correo.strip(), "password": password})
                ses = resp.session
                user = resp.user
                if not ses or not user:
                    st.error("No se pudo iniciar sesión.")
                else:
                    st.session_state["access_token"] = ses.access_token
                    st.session_state["refresh_token"] = ses.refresh_token
                    st.session_state["usuario_id"] = user.id
                    st.session_state["correo"] = user.email or correo.strip()
                    sb = nuevo_cliente()
                    perfil = perfil_usuario(sb, user.id)
                    if not perfil:
                        st.session_state.clear()
                        st.error("La cuenta no tiene perfil. Agrega su UID en public.perfiles.")
                    else:
                        registrar_evento(sb, user.id, "INICIO DE SESIÓN EXITOSO")
                        st.rerun()
            except Exception as e:
                error_seguro(e, "No se pudo iniciar sesión")
    st.stop()

sb = nuevo_cliente()
uid = st.session_state.get("usuario_id")
correo = st.session_state.get("correo", "")
try:
    perfil = perfil_usuario(sb, uid)
except Exception as e:
    error_seguro(e, "No se pudo consultar el perfil")
    st.stop()

if not perfil:
    st.error("Tu cuenta no tiene un perfil autorizado.")
    if st.button("Cerrar sesión"):
        st.session_state.clear()
        st.rerun()
    st.stop()

rol = perfil.get("rol", "consulta")
admin = rol == "admin"
st.sidebar.success(f"Sesión: {perfil.get('nombre') or correo}")
st.sidebar.caption(f"Rol: {rol}")
if st.sidebar.button("Cerrar sesión"):
    registrar_evento(sb, uid, "CIERRE DE SESIÓN")
    st.session_state.clear()
    st.rerun()

menu = ["Inicio", "Registrar persona", "Consultar registros", "Gráfica de registros"]
if admin:
    menu += ["Eliminar persona", "Administrar perfiles", "Historial de accesos"]
opcion = st.sidebar.radio("Menú", menu)

try:
    datos = cargar_votantes(sb)
except Exception as e:
    error_seguro(e, "No se pudieron consultar los registros")
    st.stop()

if opcion == "Inicio":
    st.subheader("Panel principal")
    c1, c2 = st.columns(2)
    c1.metric("Personas registradas", len(datos))
    c2.metric("Categorías de partido", datos["afiliacion_partido"].nunique() if not datos.empty else 0)
    if not datos.empty:
        vista = datos.drop(columns=["curp", "domicilio"], errors="ignore").rename(columns={
            "id":"ID", "nombre":"Nombre", "apellido_paterno":"Apellido paterno",
            "apellido_materno":"Apellido materno", "edad":"Edad",
            "seccion_municipal":"Sección", "afiliacion_partido":"Partido asociado",
            "creado_en":"Fecha de registro"
        })
        st.dataframe(vista, use_container_width=True, hide_index=True)
    else:
        st.info("Todavía no hay registros.")

elif opcion == "Registrar persona":
    st.subheader("Registrar persona")
    st.warning("CURP, domicilio y afiliación política son datos personales delicados. Usa datos ficticios para probar.")
    with st.form("registro"):
        nombre = st.text_input("Nombre")
        paterno = st.text_input("Apellido paterno")
        materno = st.text_input("Apellido materno (opcional)")
        edad = st.number_input("Edad", min_value=18, max_value=120, value=18)
        curp = st.text_input("CURP", max_chars=18).strip().upper()
        domicilio = st.text_input("Domicilio")
        seccion = st.text_input("Sección electoral")
        partido = st.selectbox("Partido asociado al registro", PARTIDOS)
        otro = st.text_input("Nombre del partido") if partido == "Otro" else ""
        autorizacion = st.checkbox("Tengo autorización para guardar estos datos.")
        guardar = st.form_submit_button("Guardar persona", type="primary")
    if guardar:
        if not nombre.strip() or not paterno.strip():
            st.error("Escribe el nombre y el apellido paterno.")
        elif len(curp) != 18:
            st.error("La CURP debe tener 18 caracteres.")
        elif not seccion.strip():
            st.error("Escribe la sección electoral.")
        elif partido == "Otro" and not otro.strip():
            st.error("Escribe el nombre del partido.")
        elif not autorizacion:
            st.error("Confirma que tienes autorización.")
        else:
            fila = {
                "nombre": nombre.strip(), "apellido_paterno": paterno.strip(),
                "apellido_materno": materno.strip() or None, "edad": int(edad),
                "curp": curp, "domicilio": domicilio.strip() or None,
                "seccion_municipal": seccion.strip() or None,
                "afiliacion_partido": otro.strip() if partido == "Otro" else partido,
                "creado_por": uid
            }
            try:
                sb.table("votantes").insert(fila).execute()
                st.success("Persona guardada en Supabase.")
                st.rerun()
            except Exception as e:
                if "23505" in str(e) or "duplicate" in str(e).lower():
                    st.error("Ya existe un registro con esa CURP.")
                else:
                    error_seguro(e, "No se pudo guardar la persona")

elif opcion == "Consultar registros":
    st.subheader("Consultar personas")
    if datos.empty:
        st.info("No hay registros.")
    else:
        buscar = st.text_input("Buscar por nombre, apellido o sección")
        mascara = pd.Series(False, index=datos.index)
        for col in ["nombre", "apellido_paterno", "apellido_materno", "seccion_municipal"]:
            mascara |= datos[col].fillna("").astype(str).str.contains(buscar, case=False, regex=False)
        filtrados = datos[mascara] if buscar else datos
        vista = filtrados.rename(columns={
            "id":"ID", "nombre":"Nombre", "apellido_paterno":"Apellido paterno",
            "apellido_materno":"Apellido materno", "edad":"Edad", "curp":"CURP",
            "domicilio":"Domicilio", "seccion_municipal":"Sección",
            "afiliacion_partido":"Partido asociado", "creado_en":"Fecha de registro"
        })
        st.dataframe(vista, use_container_width=True, hide_index=True)
        st.download_button("Descargar resultados CSV", filtrados.to_csv(index=False).encode("utf-8-sig"),
                           "registros_votantes.csv", "text/csv")

elif opcion == "Gráfica de registros":
    st.subheader("Cantidad de registros por partido asociado")
    if datos.empty:
        st.info("Registra personas para generar la gráfica.")
    else:
        conteo = datos["afiliacion_partido"].fillna("Sin especificar").value_counts()
        st.bar_chart(conteo)
        st.dataframe(conteo.rename("Cantidad").reset_index(), use_container_width=True, hide_index=True)
        st.caption("La gráfica muestra registros administrativos, no votos emitidos ni resultados oficiales.")

elif opcion == "Eliminar persona" and admin:
    st.subheader("Eliminar registro (solo administrador)")
    if datos.empty:
        st.info("No hay registros que eliminar.")
    else:
        etiquetas = {}
        for _, f in datos.iterrows():
            nom = " ".join(str(f.get(c) or "") for c in ["nombre","apellido_paterno","apellido_materno"]).strip()
            etiquetas[f"{nom} | Sección {f.get('seccion_municipal') or ''} | ID {f['id']}"] = f["id"]
        elegido = st.selectbox("Selecciona el registro", list(etiquetas.keys()))
        confirmar = st.checkbox("Confirmo que deseo eliminar este registro.")
        if st.button("Eliminar registro", type="primary"):
            if not confirmar:
                st.warning("Confirma la eliminación.")
            else:
                try:
                    sb.table("votantes").delete().eq("id", etiquetas[elegido]).execute()
                    st.success("Registro eliminado.")
                    st.rerun()
                except Exception as e:
                    error_seguro(e, "No se pudo eliminar el registro")

elif opcion == "Administrar perfiles" and admin:
    st.subheader("Perfiles autorizados")
    st.info("Crea usuarios en Supabase → Authentication → Users y después agrega su UID en public.perfiles.")
    try:
        perfiles = sb.table("perfiles").select("id,nombre,rol,creado_en").order("creado_en", desc=True).execute().data or []
        st.dataframe(pd.DataFrame(perfiles), use_container_width=True, hide_index=True)
    except Exception as e:
        error_seguro(e, "No se pudieron consultar los perfiles")

elif opcion == "Historial de accesos" and admin:
    st.subheader("Historial de accesos (solo administrador)")
    try:
        eventos = sb.table("registro_accesos").select(
            "id,usuario_id,evento,exitoso,creado_en"
        ).order("creado_en", desc=True).limit(500).execute().data or []
        if eventos:
            df = pd.DataFrame(eventos)
            st.dataframe(df, use_container_width=True, hide_index=True)
            st.download_button("Descargar historial CSV", df.to_csv(index=False).encode("utf-8-sig"),
                               "historial_accesos.csv", "text/csv")
        else:
            st.info("Todavía no hay eventos registrados.")
    except Exception as e:
        error_seguro(e, "No se pudo consultar el historial")
