"""
Client HTTP per a l'API de Cita Prèvia del SEPE.

Substitueix Selenium/Chrome amb peticions HTTP directes als endpoints
AJAX del SEPE.  El flux reprodueix la cadena que fa el JavaScript del
navegador:

    GET pàgina → existeCP → nivel 1 → cargarComboGrupos… →
    compruebaMascaraDNI → antifraude → loadMensajes →
    showPantallaMapa → cargaOficinasMapa(canal)

Cada crida manté la sessió (JSESSIONID) que el servidor utilitza per
rastrejar l'estat de la conversa.
"""

import logging
import re
import requests

logger = logging.getLogger(__name__)

BASE = "https://citaprevia-sede.sepe.gob.es/citapreviasepe"

# Timeout per a cada petició HTTP (segons)
REQUEST_TIMEOUT = 20

# Mapa de nivel‑2 IDs (els que l'usuari tria al UI) → subtràmit ID
# (el que SEPE necessita com a ``idGrupoServicio``).
# Obtingut de l'HTML retornat per ``cargarComboGruposTramitesByNivel``.
NIVEL2_TO_SUBTRAMITE = {
    "158": "8",    # He finalizado un trabajo → acceso o reanudación
    "159": "41",   # Otros accesos subsidio → Información general (safe fallback)
    "160": "26",   # Declaración anual de Rentas
    "161": "29",   # Cobros indebidos / sanciones
    "162": "20",   # Estoy cobrando y ha cambiado → Baja IT/maternidad
    "163": "631",  # Tránsito a IMV
    "164": "41",   # Información general
}
DEFAULT_SUBTRAMITE = "8"

# Canal IDs (constants del SEPE)
CHANNEL_PRESENCIAL = "1"
CHANNEL_TELEFONICA = "3"


# ─────────────────────────────────────────────────────────────────────
# Funció principal
# ─────────────────────────────────────────────────────────────────────

def check_zip(zip_code: str, dni: str, appt_types: list | None = None,
              tramite_id: str = "158") -> dict:
    """Comprova disponibilitat de cita per a *zip_code* / *dni*.

    Parameters
    ----------
    zip_code : str  – Codi postal (5 dígits).
    dni      : str  – Document d'identitat.
    appt_types : list[str]  – ``['person']``, ``['phone']`` o ambdós.
    tramite_id : str  – ID de nivel 2 (per defecte ``"158"``).

    Returns
    -------
    dict  – ``{<appt_type>: bool, 'offices': [{'name': …, 'date': …}, …]}``
    """
    if appt_types is None:
        appt_types = ["person"]

    results: dict = {t: False for t in appt_types}

    subtramite = NIVEL2_TO_SUBTRAMITE.get(str(tramite_id), DEFAULT_SUBTRAMITE)

    try:
        session = _build_session(zip_code, dni, tramite_id)
    except Exception as exc:
        logger.error("Error construint la sessió SEPE per CP %s: %s", zip_code, exc)
        return results

    # Consultar oficines per cada canal sol·licitat
    all_offices: list[dict] = []
    for appt_type in appt_types:
        channel_id = CHANNEL_PRESENCIAL if appt_type == "person" else CHANNEL_TELEFONICA
        try:
            offices = _fetch_offices(session, zip_code, subtramite, channel_id)
        except Exception as exc:
            logger.warning("Error obtenint oficines (%s) CP %s: %s",
                           appt_type, zip_code, exc)
            offices = []

        # Mirem si alguna oficina té primerHuecoDisponible no buit
        has_appointment = any(o.get("date") for o in offices)
        results[appt_type] = has_appointment

        if has_appointment:
            type_name = "Presencial" if appt_type == "person" else "Telefònica"
            logger.info("CITA %s TROBADA al CP %s (%d oficines amb hueco)",
                        type_name, zip_code, sum(1 for o in offices if o.get("date")))
            all_offices.extend(offices)

    if all_offices:
        results["offices"] = all_offices

    return results


# ─────────────────────────────────────────────────────────────────────
# Construcció de sessió (cadena d'estat)
# ─────────────────────────────────────────────────────────────────────

def _build_session(zip_code: str, dni: str, tramite_id: str) -> requests.Session:
    """Executa tota la cadena d'AJAX per establir l'estat de sessió."""
    s = requests.Session()
    s.headers["User-Agent"] = (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/125.0.0.0 Safari/537.36"
    )

    # 1. Pàgina principal → obtenim JSESSIONID
    s.get(f"{BASE}/?origen=sepe&codidioma=es", timeout=REQUEST_TIMEOUT)
    s.headers.update({
        "X-Requested-With": "XMLHttpRequest",
        "Referer": f"{BASE}/?origen=sepe&codidioma=es",
    })

    # 2. Validar codi postal
    r = s.post(f"{BASE}/cita/existeCP", data={
        "idCliente": "39", "codigoPostal": zip_code, "usoBloqueoIframe": "false",
    }, timeout=REQUEST_TIMEOUT)
    if r.text.strip() != "true":
        raise ValueError(f"CP {zip_code} no vàlid segons SEPE (resp: {r.text[:60]})")

    # 3. Nivel 1 (PRESTACIONES)
    s.post(f"{BASE}/cita/cargaComboNivelesTramitesCPEntidad", data={
        "idCliente": "39", "codigoPostal": zip_code, "usoBloqueoIframe": "false",
        "nivel": "1", "idNivel": "0", "idsNiveles": "",
        "origen": "sepe", "usaOrdenManual": "false", "codigoEntidad": "",
    }, timeout=REQUEST_TIMEOUT)

    # 4. Carregar subtràmits (estableix estat servidor)
    s.post(f"{BASE}/cita/cargarComboGruposTramitesByNivel", data={
        "idCliente": "39", "codigoPostal": zip_code, "usoBloqueoIframe": "false",
        "nivel": "2", "idNivel": str(tramite_id), "idsNiveles": "",
        "esServicio": "true",
    }, timeout=REQUEST_TIMEOUT)

    # 5. Validar DNI
    s.post(f"{BASE}/cita/compruebaMascaraDNI", data={
        "documento": dni, "codIdioma": "es",
    }, timeout=REQUEST_TIMEOUT)

    # 6. Anti-frau
    s.post(f"{BASE}/cita/compruebaCitasDocumentoAntifraude", data={
        "documento": dni,
        "validacionControlFraude": "1",
        "idConfiguracionAntifraude": "2",
        "moduloGrupoLimitanteCita": "1",
        "codIdioma": "es",
    }, timeout=REQUEST_TIMEOUT)

    # 7. Carregar missatges
    s.post(f"{BASE}/cita/loadMensajes", data={
        "codigoEntidad": "", "tieneTramiteRelacionado": "false",
        "codigoEntidadTR": "", "codIdioma": "es",
    }, timeout=REQUEST_TIMEOUT)

    # 8. Mostrar pantalla mapa (step 2 del SEPE)
    r = s.post(f"{BASE}/cita/showPantallaMapa", data={
        "busquedaPorCP": "true", "codigoEntidad": "",
        "codIdioma": "es", "tieneTramiteRelacionado": "false",
    }, timeout=REQUEST_TIMEOUT)
    if len(r.text.strip()) < 100:
        logger.warning("showPantallaMapa ha retornat %d chars (esperat >100)", len(r.text))

    return s


# ─────────────────────────────────────────────────────────────────────
# Obtenció d'oficines
# ─────────────────────────────────────────────────────────────────────

def _fetch_offices(session: requests.Session, zip_code: str,
                   subtramite: str, channel_id: str) -> list[dict]:
    """Crida ``cargaOficinasMapa`` i retorna llista d'oficines."""
    r = session.post(f"{BASE}/cita/cargaOficinasMapa", data={
        "idCliente": "39",
        "codigoEntidad": "",
        "idGrupoServicio": subtramite,
        "idTipoAtencion": channel_id,
        "idTipoAtencionTR": "0",
        "codigoPostal": zip_code,
        "latOrigen": "0",        # Coords 0,0 → SEPE retorna totes igualment
        "lngOrigen": "0",
        "tieneTramiteRelacionado": "0",
        "idsJerarquiaTramites": "",
    }, timeout=REQUEST_TIMEOUT)

    data = r.json()

    if data.get("Error") == "ErrorCaptcha":
        logger.warning("SEPE ha retornat ErrorCaptcha per CP %s", zip_code)
        return []

    offices: list[dict] = []
    for ofi in data.get("listaOficina", []):
        name = ofi.get("oficina", "Oficina desconeguda")
        hueco = ofi.get("primerHuecoDisponible", "")
        # Netejar el nom: treure " - SEPE" del final si hi és
        clean_name = re.sub(r"\s*-\s*SEPE\s*$", "", name, flags=re.IGNORECASE).strip()
        offices.append({
            "name": clean_name,
            "date": hueco if hueco else "",
        })

    return offices
