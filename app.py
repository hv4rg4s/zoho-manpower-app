import streamlit as st
import pandas as pd
import requests
import time
from datetime import datetime

# ─────────────────────────────────────────────
#  CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Masivo Blue",
    page_icon="💙",
    layout="centered",
)

st.markdown("""
<style>
    /* Fondo rosado general */
    .stApp {
        background-color: #FFC5D3;
    }
    /* Fondo rosado en sidebar y contenedores internos */
    section[data-testid="stSidebar"],
    .block-container {
        background-color: #FFC5D3;
    }
    /* Tarjeta central con fondo blanco suave */
    .card {
        background: rgba(255,255,255,0.82);
        border-radius: 16px;
        padding: 2rem 2.5rem;
        margin-bottom: 1.5rem;
        box-shadow: 0 2px 16px rgba(180,60,100,0.07);
    }
    /* Botón principal */
    .stButton > button {
        width: 100%;
        background-color: #C2185B;
        color: white;
        border: none;
        border-radius: 10px;
        padding: 0.65rem 1rem;
        font-size: 16px;
        font-weight: 600;
        letter-spacing: 0.02em;
    }
    .stButton > button:hover { background-color: #880E4F; color: white; }
    .stButton > button:disabled { background-color: #F48FB1; color: #fff; }
    /* Inputs y selects */
    .stTextInput input, .stSelectbox select {
        border-radius: 8px !important;
        border: 1.5px solid #F48FB1 !important;
    }
    /* Expander */
    .streamlit-expanderHeader {
        background: rgba(255,255,255,0.6) !important;
        border-radius: 8px !important;
    }
    /* Resultados */
    .resultado-ok  { background:#E1F5EE; border-radius:10px; padding:1rem; margin-top:1rem; }
    .resultado-err { background:#FCEBEB; border-radius:10px; padding:1rem; margin-top:1rem; }
    /* Título principal */
    h1 { color: #880E4F !important; font-weight: 700 !important; }
    h2, h3 { color: #C2185B !important; }
    /* Ocultar menú hamburguesa y footer de Streamlit */
    #MainMenu { visibility: hidden; }
    footer { visibility: hidden; }
    header[data-testid="stHeader"] { background: transparent; }
</style>
""", unsafe_allow_html=True)



# ─────────────────────────────────────────────
#  CREDENCIALES
# ─────────────────────────────────────────────
def get_creds():
    try:
        return (
            st.secrets["CLIENT_ID"],
            st.secrets["CLIENT_SECRET"],
            st.secrets["REFRESH_TOKEN"],
            st.secrets.get("ZOHO_REGION", "com"),
        )
    except Exception:
        return None, None, None, "com"

# ─────────────────────────────────────────────
#  HELPERS API
# ─────────────────────────────────────────────
@st.cache_data(ttl=3300, show_spinner=False)
def get_access_token(client_id, client_secret, refresh_token, region):
    url = f"https://accounts.zoho.{region}/oauth/v2/token"
    r = requests.post(url, params={
        "refresh_token": refresh_token,
        "client_id":     client_id,
        "client_secret": client_secret,
        "grant_type":    "refresh_token",
    })
    r.raise_for_status()
    return r.json()["access_token"]

def api_headers(token):
    return {"Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json"}

def buscar_candidato_email(email, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/Candidates/search"
    r = requests.get(url, headers=api_headers(token), params={"email": email})
    if r.status_code == 204:
        return None
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0] if data else None

def buscar_job_opening(codigo, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/JobOpenings/search"
    r = requests.get(url, headers=api_headers(token),
                     params={"criteria": f"(Codigo_Solicitud_de_Busqueda:equals:{codigo})"})
    if r.status_code == 204:
        return None
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0] if data else None

def asociar_candidato_job(candidato_id, job_id, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/Candidates/actions/associate"
    payload = {"data": [{"jobids": [job_id], "ids": [candidato_id], "comments": "Asociado via Masivo Blue"}]}
    r = requests.put(url, headers=api_headers(token), json=payload)
    r.raise_for_status()
    res = r.json().get("data", [{}])[0]
    code = res.get("code", "")
    return code in ("SUCCESS", "ALREADY_ASSOCIATED"), code

def cambiar_etapa_candidato(candidato_id, etapa, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/Candidates/{candidato_id}"
    r = requests.put(url, headers=api_headers(token),
                     json={"data": [{"Candidate_Status": etapa}]})
    r.raise_for_status()
    return r.json().get("data", [{}])[0].get("code") == "SUCCESS"

def obtener_candidatos_job(job_id, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/JobOpenings/{job_id}/Candidates"
    candidatos, page = [], 1
    while True:
        r = requests.get(url, headers=api_headers(token),
                         params={"page": page, "per_page": 200})
        if r.status_code == 204:
            break
        r.raise_for_status()
        batch = r.json().get("data", [])
        candidatos.extend(batch)
        if len(batch) < 200:
            break
        page += 1
    return candidatos

# ─────────────────────────────────────────────
#  OPERACIÓN 1: ASOCIAR A JOB OPENINGS
# ─────────────────────────────────────────────
def asociar_job_openings(df, token, region, dry_run, progress_bar, status_text):
    log = []
    total = len(df)
    for i, row in df.iterrows():
        progress_bar.progress((i + 1) / total)
        email  = str(row.get("email", "")).strip()
        codigo = str(row.get("codigo_solicitud", "")).strip()
        status_text.text(f"Procesando {i+1}/{total}: {email} → {codigo}")

        if not email or not codigo:
            log.append({"fila": i+2, "email": email, "codigo": codigo,
                        "accion": "error", "detalle": "Faltan datos"})
            continue

        if dry_run:
            log.append({"fila": i+2, "email": email, "codigo": codigo,
                        "accion": "simulado", "detalle": "Dry-run OK"})
            time.sleep(0.05)
            continue

        try:
            candidato = buscar_candidato_email(email, token, region)
            if not candidato:
                log.append({"fila": i+2, "email": email, "codigo": codigo,
                            "accion": "no_encontrado", "detalle": "Candidato no existe"})
                continue
            job = buscar_job_opening(codigo, token, region)
            if not job:
                log.append({"fila": i+2, "email": email, "codigo": codigo,
                            "accion": "no_encontrado", "detalle": "Job Opening no existe"})
                continue
            ok, code = asociar_candidato_job(candidato["id"], job["id"], token, region)
            log.append({"fila": i+2, "email": email, "codigo": codigo,
                        "accion": "asociado" if ok else "error", "detalle": code})
            time.sleep(0.4)
        except Exception as e:
            log.append({"fila": i+2, "email": email, "codigo": codigo,
                        "accion": "error", "detalle": str(e)[:120]})
    return pd.DataFrame(log)

# ─────────────────────────────────────────────
#  OPERACIÓN 2: CAMBIAR ETAPAS
# ─────────────────────────────────────────────
ETAPA_1 = "Preselección / Screening de Acercamiento"
ETAPA_2 = "Pre-Contrato"
DELAY_ETAPAS = 10

def cambiar_etapas(df, token, region, dry_run, progress_bar, status_text):
    col_codigo = "codigo_solicitud" if "codigo_solicitud" in df.columns else df.columns[0]
    codigos = df[col_codigo].dropna().astype(str).str.strip().unique().tolist()
    log = []
    total = len(codigos)

    for i, codigo in enumerate(codigos):
        progress_bar.progress((i + 1) / total * 0.5)
        status_text.text(f"[Etapa 1] Código {i+1}/{total}: {codigo}")

        if dry_run:
            log.append({"codigo": codigo, "etapa": ETAPA_1, "accion": "simulado"})
            log.append({"codigo": codigo, "etapa": ETAPA_2, "accion": "simulado"})
            time.sleep(0.05)
            continue

        try:
            job = buscar_job_opening(codigo, token, region)
            if not job:
                log.append({"codigo": codigo, "etapa": "—", "accion": "no_encontrado"})
                continue
            for c in obtener_candidatos_job(job["id"], token, region):
                cid = c["id"]
                try:
                    cambiar_etapa_candidato(cid, ETAPA_1, token, region)
                    log.append({"codigo": codigo, "candidato_id": cid,
                                "nombre": c.get("Full_Name",""), "etapa": ETAPA_1, "accion": "ok"})
                    time.sleep(0.3)
                except Exception as e:
                    log.append({"codigo": codigo, "candidato_id": cid,
                                "nombre": c.get("Full_Name",""), "etapa": ETAPA_1,
                                "accion": "error", "detalle": str(e)[:100]})
        except Exception as e:
            log.append({"codigo": codigo, "etapa": "—", "accion": "error", "detalle": str(e)[:100]})

    if not dry_run:
        status_text.text(f"⏳ Esperando {DELAY_ETAPAS} s antes de Etapa 2…")
        time.sleep(DELAY_ETAPAS)

    for i, codigo in enumerate(codigos):
        progress_bar.progress(0.5 + (i + 1) / total * 0.5)
        status_text.text(f"[Etapa 2] Código {i+1}/{total}: {codigo}")
        if dry_run:
            continue
        try:
            job = buscar_job_opening(codigo, token, region)
            if not job:
                continue
            for c in obtener_candidatos_job(job["id"], token, region):
                cid = c["id"]
                try:
                    cambiar_etapa_candidato(cid, ETAPA_2, token, region)
                    log.append({"codigo": codigo, "candidato_id": cid,
                                "nombre": c.get("Full_Name",""), "etapa": ETAPA_2, "accion": "ok"})
                    time.sleep(0.3)
                except Exception as e:
                    log.append({"codigo": codigo, "candidato_id": cid,
                                "nombre": c.get("Full_Name",""), "etapa": ETAPA_2,
                                "accion": "error", "detalle": str(e)[:100]})
        except Exception as e:
            log.append({"codigo": codigo, "etapa": ETAPA_2, "accion": "error", "detalle": str(e)[:100]})

    return pd.DataFrame(log)

# ─────────────────────────────────────────────
#  INTERFAZ PRINCIPAL
# ─────────────────────────────────────────────
st.markdown("""
<div style="text-align:center;padding:1rem 0 0.5rem">
    <div style="font-size:2.8rem">💙</div>
    <h1 style="margin:0.2rem 0 0.1rem">Masivo Blue</h1>
    <p style="color:#C2185B;font-size:14px;margin:0">Sube tu archivo Excel, elige la operación y haz clic en <b>Ejecutar</b></p>
</div>
""", unsafe_allow_html=True)

st.divider()

# ── Selector de operación ──
operacion = st.selectbox(
    "¿Qué operación quieres realizar?",
    options=[
        "1 · Asociar candidatos a Job Openings",
        "2 · Cambiar etapas (Preselección → Pre-Contrato)",
    ],
    help="Selecciona la tarea que vas a ejecutar."
)

# ── Ayuda de columnas ──
with st.expander("📋 ¿Qué columnas necesita mi Excel?"):
    if "1 ·" in operacion:
        st.markdown("""
**Columnas requeridas:** `email`, `codigo_solicitud`

| email | codigo_solicitud |
|---|---|
| juan@gmail.com | S052021 |
| maria@gmail.com | S052021 |
""")
    else:
        st.markdown("""
**Columna requerida:** `codigo_solicitud`

| codigo_solicitud |
|---|
| S052021 |
| S052020 |

El proceso moverá a todos los candidatos de cada código a **Preselección** y luego a **Pre-Contrato**.
""")

# ── Subida de archivo ──
archivo = st.file_uploader(
    "Sube tu archivo Excel (.xlsx)",
    type=["xlsx"],
    help="El archivo se procesa en memoria y no se almacena."
)

# ── Modo simulación ──
dry_run = st.toggle(
    "🔍 Modo simulación (no realiza cambios, solo muestra qué haría)",
    value=True,
    help="Actívalo la primera vez para verificar antes de ejecutar en real."
)

st.divider()

if dry_run:
    st.info("**Modo simulación activo.** No se realizarán cambios.", icon="🔍")
else:
    st.warning("**Modo real activo.** Los cambios se aplicarán.", icon="⚠️")

ejecutar = st.button(
    "▶  Ejecutar" + (" (simulación)" if dry_run else ""),
    disabled=(archivo is None),
    type="primary",
)

if archivo is None:
    st.caption("Sube un archivo Excel para habilitar el botón.")

# ─────────────────────────────────────────────
#  EJECUCIÓN
# ─────────────────────────────────────────────
if ejecutar and archivo is not None:
    client_id, client_secret, refresh_token, region = get_creds()
    if not client_id:
        st.error("⚠️ Credenciales no configuradas. Contacta al administrador.")
        st.stop()

    try:
        df = pd.read_excel(archivo)
        df.columns = [c.strip().lower().replace(" ", "_") for c in df.columns]
    except Exception as e:
        st.error(f"No se pudo leer el Excel: {e}")
        st.stop()

    st.success(f"✅ Archivo cargado: **{len(df)} filas**, {len(df.columns)} columnas")
    st.dataframe(df.head(5), use_container_width=True)

    progress_bar = st.progress(0)
    status_text  = st.empty()

    if not dry_run:
        try:
            token = get_access_token(client_id, client_secret, refresh_token, region)
        except Exception as e:
            st.error(f"Error de autenticación: {e}")
            st.stop()
    else:
        token = "DRY_RUN"

    ts     = datetime.now().strftime("%Y%m%d_%H%M%S")
    sufijo = "_simulacion" if dry_run else ""

    with st.spinner("Procesando… esto puede tardar varios minutos."):
        try:
            if "1 ·" in operacion:
                log_df     = asociar_job_openings(df, token, region, dry_run, progress_bar, status_text)
                nombre_log = f"asociar_job_{ts}{sufijo}.csv"
            else:
                log_df     = cambiar_etapas(df, token, region, dry_run, progress_bar, status_text)
                nombre_log = f"cambiar_etapas_{ts}{sufijo}.csv"
        except Exception as e:
            st.error(f"Error durante la ejecución: {e}")
            st.stop()

    progress_bar.progress(1.0)
    status_text.text("✅ Proceso completado.")

    st.divider()
    st.subheader("Resumen")
    col1, col2, col3 = st.columns(3)
    ok_n  = len(log_df[log_df["accion"].isin(["ok","asociado","simulado"])])
    err_n = len(log_df[log_df["accion"] == "error"])
    nf_n  = len(log_df[log_df["accion"] == "no_encontrado"])
    col1.metric("✅ Exitosos",        ok_n)
    col2.metric("❌ Errores",         err_n)
    col3.metric("⚠️ No encontrados", nf_n)

    st.dataframe(log_df, use_container_width=True)

    csv_bytes = log_df.to_csv(index=False, encoding="utf-8-sig").encode("utf-8-sig")
    st.download_button(
        label="📥 Descargar log CSV",
        data=csv_bytes,
        file_name=nombre_log,
        mime="text/csv",
    )

    if err_n > 0:
        st.markdown('<div class="resultado-err">⚠️ Algunos registros tuvieron errores. Revisa la columna <b>detalle</b> en el log.</div>', unsafe_allow_html=True)
    else:
        st.markdown('<div class="resultado-ok">🎉 Todos los registros procesados correctamente.</div>', unsafe_allow_html=True)
