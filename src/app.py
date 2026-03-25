"""
Flask application — capa fina de routes HTTP.
Tota la lògica de negoci viu a search_service i email_service.
"""
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
import uuid
import os
import json
import sys
import logging
from datetime import timedelta
from dotenv import load_dotenv

from src.state import load_state
from src.locations import LocationManager
from src import search_service, email_service

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)


class StatusEndpointFilter(logging.Filter):
    def filter(self, record):
        return "/api/status" not in record.getMessage()

logging.getLogger("werkzeug").addFilter(StatusEndpointFilter())

# ---------------------------------------------------------------------------
# App
# ---------------------------------------------------------------------------
load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or os.urandom(32).hex()
app.permanent_session_lifetime = timedelta(days=30)

app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

MAX_CONCURRENT_SEARCHES = int(os.getenv('MAX_CONCURRENT_SEARCHES', 10))

# Carregar tràmits SEPE
TRAMITS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'tramits_sepe.json')
TRAMITS = {}
try:
    with open(TRAMITS_FILE, 'r', encoding='utf-8') as f:
        TRAMITS = json.load(f)
    logger.info(f"Carregats {len(TRAMITS)} tràmits SEPE")
except Exception as e:
    logger.warning(f"No s'han pogut carregar els tràmits SEPE: {e}")


# ---------------------------------------------------------------------------
# Session helper
# ---------------------------------------------------------------------------

def _get_user_id():
    """Retorna (o crea) un identificador únic per a la sessió actual."""
    if 'user_id' not in session:
        session.permanent = True
        session['user_id'] = str(uuid.uuid4())
    return session['user_id']


# ═══════════════════════════════════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════════════════════════════════

@app.route('/')
def index():
    uid = _get_user_id()
    active_searches = search_service.get_searches_for_owner(uid)
    communities = LocationManager.get_communities()

    return render_template('index.html',
                           searches=active_searches,
                           communities=communities,
                           tramits=TRAMITS,
                           last_dni=session.get('last_dni', ''),
                           last_email=session.get('last_email', ''),
                           last_community=session.get('last_community', []),
                           last_scope=session.get('last_scope', ''),
                           last_provinces=session.get('last_provinces', []),
                           last_comarques=session.get('last_comarques', []),
                           last_municipis=session.get('last_municipis', []),
                           last_zip_input=session.get('last_zip_input', ''),
                           last_appt_types=session.get('last_appt_types', ['person']),
                           last_freq_type=session.get('last_freq_type', 'once'),
                           last_interval=session.get('last_interval', 1),
                           last_daily_time=session.get('last_daily_time', '09:00'),
                           last_tramite_id=session.get('last_tramite_id', '158'))


# --- Desplegables dinàmics ---

@app.route('/api/provinces')
def get_provinces_query():
    communities = request.args.getlist('community')
    return jsonify(LocationManager.get_provinces(communities) if communities else [])

@app.route('/api/provinces/<community>')
def get_provinces(community):
    if community == 'all':
        return jsonify(LocationManager.get_provinces(None))
    return jsonify(LocationManager.get_provinces(community))

@app.route('/api/comarques')
def get_comarques_route():
    province = request.args.getlist('province') or request.args.get('province')
    return jsonify(LocationManager.get_comarques(province))

@app.route('/api/municipios')
def get_municipios_route():
    province = request.args.getlist('province') or request.args.get('province')
    community = request.args.getlist('community') or request.args.get('community')
    comarca = request.args.getlist('comarca') or request.args.get('comarca')
    return jsonify(LocationManager.get_municipios(province, community, comarca))


# --- Cerca CRUD ---

@app.route('/start', methods=['POST'])
def start_search():
    dni = request.form.get('dni', '').strip().upper()
    email = request.form.get('email', '').strip()
    appt_types = request.form.getlist('appt_type') or ['person']
    community = request.form.getlist('community')
    scope = request.form.get('scope')
    tramite_id = request.form.get('tramite_id', '158')

    # Guardar preferències d'UI a la sessió
    session['last_dni'] = dni
    session['last_email'] = email
    session['last_community'] = community
    session['last_scope'] = scope
    session['last_provinces'] = request.form.getlist('provincia_select')
    session['last_comarques'] = request.form.getlist('comarca_select')
    session['last_municipis'] = request.form.getlist('municipi_select')
    session['last_zip_input'] = request.form.get('zip_code_input')
    session['last_appt_types'] = appt_types
    session['last_freq_type'] = request.form.get('freq_type')
    session['last_interval'] = request.form.get('interval_hours')
    session['last_daily_time'] = request.form.get('daily_time')
    session['last_tramite_id'] = tramite_id

    # Preparar value + extra_context per al servei
    value = None
    extra_context = {'community': community}

    if scope == 'zip':
        raw = request.form.get('zip_code_input', '')
        value = [v.strip() for v in raw.split(',') if v.strip()]
    elif scope == 'municipi':
        value = request.form.getlist('municipi_select')
        prov = request.form.getlist('provincia_select')
        if prov:
            extra_context['province'] = prov
    elif scope == 'provincia':
        value = request.form.getlist('provincia_select')
    elif scope == 'comarca':
        value = request.form.getlist('comarca_select')
    elif scope == 'all_community':
        value = community
        scope = 'community'

    if not (dni and email and scope):
        flash("Error: Falten camps obligatoris.")
        return redirect(url_for('index'))

    result = search_service.create_search(
        dni=dni, email=email, appt_types=appt_types,
        scope=scope, value=value, extra_context=extra_context,
        tramite_id=tramite_id,
        freq_type=request.form.get('freq_type', 'once'),
        interval_hours=request.form.get('interval_hours', 1),
        daily_time=request.form.get('daily_time', '09:00'),
        owner_id=_get_user_id(),
        max_concurrent=MAX_CONCURRENT_SEARCHES,
    )

    if result['ok']:
        msg_html = f"""
            <strong>Cerca iniciada correctament</strong><br>
            <span class="text-muted">DNI:</span> <strong>{dni}</strong> &nbsp;|&nbsp;
            <span class="text-muted">Zona:</span> {result['scope_name']}
            <span class="badge bg-light text-dark border"> {result['zips_count']} CPs </span> &nbsp;|&nbsp;
            <span class="text-muted">Tipus:</span> {result['types_str']}
        """
        flash(msg_html)
    else:
        flash(f"Error: {result['message']}")

    return redirect(url_for('index'))


@app.route('/api/status')
def get_status():
    return jsonify(search_service.get_status_for_owner(_get_user_id()))

@app.route('/api/stop/<dni>', methods=['POST'])
def stop_search_api(dni):
    ok, msg = search_service.stop_search(dni, _get_user_id())
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), (200 if ok else 404)

@app.route('/api/restart/<dni>', methods=['POST'])
def restart_search_api(dni):
    ok, msg = search_service.restart_search(dni, _get_user_id())
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), (200 if ok else 404)

@app.route('/api/delete/<dni>', methods=['POST'])
def delete_search_api(dni):
    ok, msg = search_service.delete_search(dni, _get_user_id())
    return jsonify({'status': 'ok' if ok else 'error', 'message': msg}), (200 if ok else 404)


# --- Informació i diagnòstic ---

@app.route('/api/server-info')
def server_info():
    return jsonify(search_service.get_server_info())

@app.route('/api/logs')
def get_logs():
    lines = int(request.args.get('lines', 150))
    log_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'worker.log')
    if not os.path.exists(log_path):
        return jsonify({'logs': '(no log file yet)'}), 200
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        return jsonify({'logs': ''.join(all_lines[-lines:])}), 200
    except Exception as e:
        return jsonify({'logs': f'Error reading log: {e}'}), 500

@app.route('/api/debug-snapshots')
def list_debug_snapshots():
    import glob
    base = os.path.join(os.path.dirname(__file__), '..')
    htmls = sorted(glob.glob(os.path.join(base, 'debug_*.html')), key=os.path.getmtime, reverse=True)[:10]
    pngs = sorted(glob.glob(os.path.join(base, 'debug_screenshots', '*.png')), key=os.path.getmtime, reverse=True)[:10]
    return jsonify({
        'html_files': [os.path.basename(f) for f in htmls],
        'png_files': [os.path.basename(f) for f in pngs],
    })

@app.route('/api/test-email', methods=['POST'])
def test_email():
    to_email = request.json.get('email') if request.is_json else request.form.get('email')
    if not to_email:
        return jsonify({'status': 'error', 'message': 'Cal un email destinatari'}), 400
    try:
        email_service.send_test_email(to_email)
        return jsonify({'status': 'ok', 'message': f'Correu enviat a {to_email}'})
    except Exception as e:
        logger.error(f"Error enviant correu de prova: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
