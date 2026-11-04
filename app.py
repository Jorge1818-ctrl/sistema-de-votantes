
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
