# Zoho Recruit – App Manpower

Herramienta interna para automatizar operaciones en Zoho Recruit.
Desarrollada con Streamlit. Solo requiere un navegador web para usarse.

---

## Operaciones disponibles

1. **Sincronizar candidatos** — Crea o actualiza candidatos en Zoho desde un Excel
2. **Asociar a Job Openings** — Vincula candidatos (por email) a una Job Opening (por código)
3. **Cambiar etapas** — Mueve candidatos a Preselección → Pre-Contrato en batch

---

## Despliegue en Streamlit Cloud (paso a paso)

### 1. Subir el código a GitHub
1. Crea un repositorio **privado** en github.com (ej: `zoho-manpower-app`)
2. Sube estos archivos:
   - `app.py`
   - `requirements.txt`
   - `.gitignore`
   - `README.md`
3. **NO subas** `secrets.toml` ni archivos con credenciales

### 2. Crear la app en Streamlit Cloud
1. Ve a [share.streamlit.io](https://share.streamlit.io) e inicia sesión con GitHub
2. Clic en **"New app"**
3. Selecciona tu repositorio y la rama `main`
4. En **"Main file path"** escribe: `app.py`
5. Clic en **"Deploy!"**

### 3. Configurar las credenciales (Secrets)
1. En la app desplegada, ve a ⋮ → **Settings** → **Secrets**
2. Pega el siguiente contenido (con tus datos reales):

```toml
CLIENT_ID     = "TU_CLIENT_ID"
CLIENT_SECRET = "TU_CLIENT_SECRET"
REFRESH_TOKEN = "TU_REFRESH_TOKEN"
ZOHO_REGION   = "com"
```

3. Clic en **Save** — la app se reiniciará automáticamente

### 4. Compartir con la reclutadora
Copia la URL de la app (formato: `https://tu-app.streamlit.app`) y envíasela.
No necesita instalar nada. Solo abrir Chrome y usar.

---

## Formato de Excel por operación

### Operación 1 · Sincronizar candidatos
| email | nombre | apellido | rut | telefono | codigo_solicitud |
|---|---|---|---|---|---|
| ana@gmail.com | Ana | Pérez | 12345678-9 | 912345678 | S052021 |

Columnas opcionales: `fecha_nacimiento`, `direccion`, `ciudad`, `region`, `cargo`

### Operación 2 · Asociar a Job Openings
| email | codigo_solicitud |
|---|---|
| ana@gmail.com | S052021 |

### Operación 3 · Cambiar etapas
| codigo_solicitud |
|---|
| S052021 |
| S052020 |

---

## Modo simulación

Siempre activa el **modo simulación** la primera vez. No modifica nada en Zoho,
solo muestra lo que haría. Revisa el log descargado y si todo se ve bien,
repite con el modo real.

---

## Credenciales Zoho (cómo obtenerlas)

1. Ve a [api-console.zoho.com](https://api-console.zoho.com)
2. Crea un **Self Client**
3. Genera un refresh token con los scopes:
   ```
   ZohoRecruit.modules.ALL,ZohoRecruit.settings.ALL
   ```
4. Copia `CLIENT_ID`, `CLIENT_SECRET` y `REFRESH_TOKEN`
