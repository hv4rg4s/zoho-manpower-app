import streamlit as st
import pandas as pd
import requests
import time
import io
from datetime import datetime

# ─────────────────────────────────────────────
#  CONFIGURACIÓN DE PÁGINA
# ─────────────────────────────────────────────
st.set_page_config(
    page_title="Zoho Recruit – Manpower",
    page_icon="🧑‍💼",
    layout="centered",
)

st.markdown("""
<style>
    .main { padding-top: 1.5rem; }
    .stButton > button {
        width: 100%;
        background-color: #1D9E75;
        color: white;
        border: none;
        border-radius: 8px;
        padding: 0.6rem 1rem;
        font-size: 16px;
        font-weight: 500;
    }
    .stButton > button:hover { background-color: #0F6E56; color: white; }
    .stButton > button:disabled { background-color: #9FE1CB; color: #fff; }
    .resultado-ok  { background:#E1F5EE; border-radius:8px; padding:1rem; margin-top:1rem; }
    .resultado-err { background:#FCEBEB; border-radius:8px; padding:1rem; margin-top:1rem; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────
#  CREDENCIALES (via st.secrets)
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
#  HELPERS ZOHO API
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

def zoho_headers(token):
    return {"Authorization": f"Zoho-oauthtoken {token}",
            "Content-Type": "application/json"}

def buscar_candidato_email(email, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/Candidates/search"
    r = requests.get(url, headers=zoho_headers(token),
                     params={"email": email})
    if r.status_code == 204:
        return None
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0] if data else None

def buscar_job_opening(codigo, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/JobOpenings/search"
    r = requests.get(url, headers=zoho_headers(token),
                     params={"criteria": f"(Codigo_Solicitud_de_Busqueda:equals:{codigo})"})
    if r.status_code == 204:
        return None
    r.raise_for_status()
    data = r.json().get("data", [])
    return data[0] if data else None

def asociar_candidato_job(candidato_id, job_id, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/Candidates/actions/associate"
    payload = {"data": [{"jobids": [job_id], "ids": [candidato_id], "comments": "Asociado via app Manpower"}]}
    r = requests.put(url, headers=zoho_headers(token), json=payload)
    r.raise_for_status()
    res = r.json().get("data", [{}])[0]
    code = res.get("code", "")
    return code in ("SUCCESS", "ALREADY_ASSOCIATED"), code

def cambiar_etapa_candidato(candidato_id, etapa, token, region):
    url = f"https://recruit.zoho.{region}/recruit/v2/Candidates/{candidato_id}"
    r = requests.put(url, headers=zoho_headers(token),
                     json={"data": [{"Candidate_Status": etapa}]})
    r.raise_for_status()
    return r.json().get("data", [{}])[0].get("code") == "SUCCESS"

def obtener_candidatos_job(job_id, token, region):
    """Obtiene candidatos de una Job Opening via associations endpoint."""
    url = f"https://recruit.zoho.{region}/recruit/v2/JobOpenings/{job_id}/Candidates"
    candidatos = []
    page = 1
    while True:
        r = requests.get(url, headers=zoho_headers(token),
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
#  OPERACIÓN 1: SINCRONIZAR CANDIDATOS
# ─────────────────────────────────────────────
CAMPO_MAP = {
    "nombre":              "First_Name",
    "apellido":            "Last_Name",
    "email":               "Email",
    "rut":                 "RUT",
    "telefono":            "Mobile",
    "fecha_nacimiento":    "Date_of_Birth",
    "direccion":           "Street",
    "ciudad":              "City",
    "region":              "State",
    "cargo":               "Current_Job_Title",
    "codigo_solicitud":    "Codigo_Solicitud_de_Busqueda",
}

def sincronizar_candidatos(df, token, region, dry_run, progress_bar, status_text):
    log = []
    total = len(df)
    for i, row in df.iterrows():
        pct = (i + 1) / total
        progress_bar.progress(pct)
        email = str(row.get("email", "")).strip()
        nombre = str(row.get("nombre", "")).strip()
        apellido = str(row.get("apellido", "")).strip()
        label = f"{nombre} {apellido}".strip() or email
        status_text.text(f"Procesando {i+1}/{total}: {label}")

        if not email:
            log.append({"fila": i+2, "nombre": label, "email": "-", "accion": "error", "detalle": "Sin email"})
            continue

        if dry_run:
            log.append({"fila": i+2, "nombre": label, "email": email, "accion": "simulado", "detalle": "Dry-run OK"})
            time.sleep(0.05)
            continue

        try:
            payload = {}
            for col_excel, col_zoho in CAMPO_MAP.items():
                if col_excel in row and pd.notna(row[col_excel]):
                    val = row[col_excel]
                    if col_excel == "fecha_nacimiento":
                        try:
                            val = pd.to_datetime(val).strftime("%d-%m-%Y")
                        except Exception:
                            pass
                    payload[col_zoho] = str(val).strip()

            candidato = buscar_candidato_email(email, token, region)
            if candidato:
                cid = candidato["id"]
                url = f"https://recruit.zoho.{region}/recruit/v2/Candidates/{cid}"
                requests.put(url, headers=zoho_headers(token), json={"data": [payload]}).raise_for_status()
                accion = "actualizado"
            else:
                url = f"https://recruit.zoho.{region}/recruit/v2/Candidates"
                r = requests.post(url, headers=zoho_headers(token), json={"data": [payload]})
                r.raise_for_status()
                cid = r.json()["data"][0].get("details", {}).get("id")
                accion = "creado"

            codigo = str(row.get("codigo_solicitud", "")).strip()
            if codigo and cid:
                job = buscar_job_opening(codigo, token, region)
                if job:
                    asociar_candidato_job(cid, job["id"], token, region)
                    accion += " + asociado"

            log.append({"fila": i+2, "nombre": label, "email": email, "accion": accion, "detalle": "OK"})
            time.sleep(0.4)
        except Exception as e:
            log.append({"fila": i+2, "nombre": label, "email": email, "accion": "error", "detalle": str(e)[:120]})

    return pd.DataFrame(log)


# ─────────────────────────────────────────────
#  OPERACIÓN 2: ASOCIAR A JOB OPENINGS
# ─────────────────────────────────────────────
def asociar_job_openings(df, token, region, dry_run, progress_bar, status_text):
    log = []
    total = len(df)
    for i, row in df.iterrows():
        pct = (i + 1) / total
        progress_bar.progress(pct)
        email  = str(row.get("email", "")).strip()
        codigo = str(row.get("codigo_solicitud", "")).strip()
        status_text.text(f"Procesando {i+1}/{total}: {email} → {codigo}")

        if not email or not codigo:
            log.append({"fila": i+2, "email": email, "codigo": codigo, "accion": "error", "detalle": "Faltan datos"})
            continue

        if dry_run:
            log.append({"fila": i+2, "email": email, "codigo": codigo, "accion": "simulado", "detalle": "Dry-run OK"})
            time.sleep(0.05)
            continue

        try:
            candidato = buscar_candidato_email(email, token, region)
            if not candidato:
                log.append({"fila": i+2, "email": email, "codigo": codigo, "accion": "no_encontrado", "detalle": "Candidato no existe en Zoho"})
                continue
            job = buscar_job_opening(codigo, token, region)
            if not job:
                log.append({"fila": i+2, "email": email, "codigo": codigo, "accion": "no_encontrado", "detalle": "Job Opening no existe"})
                continue
            ok, code = asociar_candidato_job(candidato["id"], job["id"], token, region)
            log.append({"fila": i+2, "email": email, "codigo": codigo,
                        "accion": "asociado" if ok else "error", "detalle": code})
            time.sleep(0.4)
        except Exception as e:
            log.append({"fila": i+2, "email": email, "codigo": codigo, "accion": "error", "detalle": str(e)[:120]})

    return pd.DataFrame(log)


# ─────────────────────────────────────────────
#  OPERACIÓN 3: CAMBIAR ETAPAS
# ─────────────────────────────────────────────
ETAPA_1 = "Preselección / Screening de Acercamiento"
ETAPA_2 = "Pre-Contrato"
DELAY_ETAPAS = 10  # segundos entre etapa 1 y 2

def cambiar_etapas(df, token, region, dry_run, progress_bar, status_text):
    col_codigo = "codigo_solicitud" if "codigo_solicitud" in df.columns else df.columns[0]
    codigos = df[col_codigo].dropna().astype(str).str.strip().unique().tolist()
    log = []
    total = len(codigos)

    for i, codigo in enumerate(codigos):
        pct = (i + 1) / total
        progress_bar.progress(pct * 0.5)
        status_text.text(f"[Etapa 1] Código {i+1}/{total}: {codigo}")

        if dry_run:
            log.append({"codigo": codigo, "candidatos": "—", "etapa": ETAPA_1, "accion": "simulado"})
            log.append({"codigo": codigo, "candidatos": "—", "etapa": ETAPA_2, "accion": "simulado"})
            time.sleep(0.05)
            continue

        try:
            job = buscar_job_opening(codigo, token, region)
            if not job:
                log.append({"codigo": codigo, "candidatos": "—", "etapa": "—", "accion": "no_encontrado"})
                continue
            candidatos = obtener_candidatos_job(job["id"], token, region)
            for c in candidatos:
                cid = c["id"]
                try:
                    cambiar_etapa_candidato(cid, ETAPA_1, token, region)
                    log.append({"codigo": codigo, "candidato_id": cid, "nombre": c.get("Full_Name",""), "etapa": ETAPA_1, "accion": "ok"})
                    time.sleep(0.3)
                except Exception as e:
                    log.append({"codigo": codigo, "candidato_id": cid, "nombre": c.get("Full_Name",""), "etapa": ETAPA_1, "accion": "error", "detalle": str(e)[:100]})
        except Exception as e:
            log.append({"codigo": codigo, "candidatos": "—", "etapa": "—", "accion": "error", "detalle": str(e)[:100]})

    if not dry_run:
        status_text.text(f"⏳ Esperando {DELAY_ETAPAS} segundos antes de Etapa 2…")
        time.sleep(DELAY_ETAPAS)

    for i, codigo in enumerate(codigos):
        pct = 0.5 + (i + 1) / total * 0.5
        progress_bar.progress(pct)
        status_text.text(f"[Etapa 2] Código {i+1}/{total}: {codigo}")

        if dry_run:
            continue

        try:
            job = buscar_job_opening(codigo, token, region)
            if not job:
                continue
            candidatos = obtener_candidatos_job(job["id"], token, region)
            for c in candidatos:
                cid = c["id"]
                try:
                    cambiar_etapa_candidato(cid, ETAPA_2, token, region)
                    log.append({"codigo": codigo, "candidato_id": cid, "nombre": c.get("Full_Name",""), "etapa": ETAPA_2, "accion": "ok"})
                    time.sleep(0.3)
                except Exception as e:
                    log.append({"codigo": codigo, "candidato_id": cid, "nombre": c.get("Full_Name",""), "etapa": ETAPA_2, "accion": "error", "detalle": str(e)[:100]})
        except Exception as e:
            log.append({"codigo": codigo, "etapa": ETAPA_2, "accion": "error", "detalle": str(e)[:100]})

    return pd.DataFrame(log)


# ─────────────────────────────────────────────
#  INTERFAZ PRINCIPAL
# ─────────────────────────────────────────────
st.image("https://upload.wikimedia.org/wikipedia/commons/thumb/8/8c/ManpowerGroup_logo.svg/320px-ManpowerGroup_logo.svg.png", width=180)
st.title("Zoho Recruit – Automatización")
st.markdown("Sube tu archivo Excel, elige la operación y haz clic en **Ejecutar**.")

st.divider()

# ── Selector de operación ──
operacion = st.selectbox(
    "¿Qué operación quieres realizar?",
    options=[
        "1 · Sincronizar candidatos (crear / actualizar)",
        "2 · Asociar candidatos a Job Openings",
        "3 · Cambiar etapas (Preselección → Pre-Contrato)",
    ],
    help="Selecciona la tarea que vas a ejecutar."
)

# ── Ayuda de columnas requeridas ──
with st.expander("📋 ¿Qué columnas necesita mi Excel?"):
    if "1 ·" in operacion:
        st.markdown("""
**Columnas requeridas:** `email`, `nombre`, `apellido`

**Columnas opcionales:** `rut`, `telefono`, `fecha_nacimiento`, `direccion`, `ciudad`, `region`, `cargo`, `codigo_solicitud`

La columna `codigo_solicitud` asocia al candidato a una Job Opening automáticamente.
""")
    elif "2 ·" in operacion:
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

El script buscará todos los candidatos de cada Job Opening y los moverá a **Preselección / Screening de Acercamiento** y luego a **Pre-Contrato**.
""")

# ── Subida de archivo ──
archivo = st.file_uploader(
    "Sube tu archivo Excel (.xlsx)",
    type=["xlsx"],
    help="El archivo se procesa y descarta. No se almacena permanentemente."
)

# ── Modo simulación ──
dry_run = st.toggle(
    "🔍 Modo simulación (no modifica Zoho, solo muestra qué haría)",
    value=True,
    help="Recomendado: actívalo la primera vez para verificar antes de ejecutar en real."
)

st.divider()

if dry_run:
    st.info("**Modo simulación activo.** No se realizarán cambios en Zoho Recruit.", icon="🔍")
else:
    st.warning("**Modo real activo.** Los cambios se aplicarán en Zoho Recruit.", icon="⚠️")

# ── Botón ejecutar ──
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
            st.error(f"Error al obtener token de Zoho: {e}")
            st.stop()
    else:
        token = "DRY_RUN"

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    sufijo = "_simulacion" if dry_run else ""

    with st.spinner("Procesando… esto puede tardar varios minutos."):
        try:
            if "1 ·" in operacion:
                log_df = sincronizar_candidatos(df, token, region, dry_run, progress_bar, status_text)
                nombre_log = f"sync_candidatos_{ts}{sufijo}.csv"
            elif "2 ·" in operacion:
                log_df = asociar_job_openings(df, token, region, dry_run, progress_bar, status_text)
                nombre_log = f"asociar_job_{ts}{sufijo}.csv"
            else:
                log_df = cambiar_etapas(df, token, region, dry_run, progress_bar, status_text)
                nombre_log = f"cambiar_etapas_{ts}{sufijo}.csv"
        except Exception as e:
            st.error(f"Error durante la ejecución: {e}")
            st.stop()

    progress_bar.progress(1.0)
    status_text.text("✅ Proceso completado.")

    # ── Resumen ──
    st.divider()
    st.subheader("Resumen")
    col1, col2, col3 = st.columns(3)
    ok_n  = len(log_df[log_df["accion"].isin(["ok","creado","actualizado","asociado","creado + asociado","actualizado + asociado","simulado"])])
    err_n = len(log_df[log_df["accion"] == "error"])
    nf_n  = len(log_df[log_df["accion"] == "no_encontrado"])
    col1.metric("✅ Exitosos", ok_n)
    col2.metric("❌ Errores",  err_n)
    col3.metric("⚠️ No encontrados", nf_n)

    # ── Tabla log ──
    st.dataframe(log_df, use_container_width=True)

    # ── Descarga CSV ──
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
