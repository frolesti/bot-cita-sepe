from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_mail import Mail, Message
import time
import uuid
from datetime import datetime, timedelta
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from datetime import timezone
    class ZoneInfo:
       def __init__(self, key): pass
       def utcoffset(self, dt): return timedelta(hours=1)

import os
import random
import json
from dotenv import load_dotenv
from src.locations import LocationManager
from src.common import load_state, save_state
import sys
import logging

# Configure logging to stdout
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

# Filter out /api/status from werkzeug logs to reduce noise
class StatusEndpointFilter(logging.Filter):
    def filter(self, record):
        return "/api/status" not in record.getMessage()

logging.getLogger("werkzeug").addFilter(StatusEndpointFilter())

load_dotenv()

app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY') or os.urandom(32).hex()

# Sessió permanent de 30 dies (la cookie no caduca al tancar el navegador)
from datetime import timedelta as _td
app.permanent_session_lifetime = _td(days=30)

# Configuració del Correu (Gmail per defecte)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

mail = Mail(app)


# --- Aïllament per sessió: cada navegador rep un user_id únic ---
def _get_user_id():
    """Retorna (o crea) un identificador únic per a la sessió actual."""
    if 'user_id' not in session:
        session.permanent = True
        session['user_id'] = str(uuid.uuid4())
    return session['user_id']


def _get_my_searches(all_searches=None):
    """Retorna NOMÉS les cerques que pertanyen a la sessió actual."""
    if all_searches is None:
        all_searches = load_state()
    uid = _get_user_id()

    # Migració: cerques sense owner_id → adoptar a la sessió actual
    adopted = False
    for dni, data in all_searches.items():
        if 'owner_id' not in data:
            data['owner_id'] = uid
            adopted = True
    if adopted:
        save_state(all_searches)

    return {dni: data for dni, data in all_searches.items()
            if data.get('owner_id') == uid}


def _owns_search(dni, all_searches=None):
    """Comprova si la sessió actual és propietària d'una cerca."""
    if all_searches is None:
        all_searches = load_state()
    search = all_searches.get(dni)
    if not search:
        return False
    return search.get('owner_id') == _get_user_id()


# --- Límit de cerques simultànies per evitar sobrecàrrega ---
MAX_CONCURRENT_SEARCHES = int(os.getenv('MAX_CONCURRENT_SEARCHES', 10))

# --- Carregar tràmits SEPE ---
TRAMITS_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data', 'tramits_sepe.json')
TRAMITS = {}
try:
    with open(TRAMITS_FILE, 'r', encoding='utf-8') as f:
        TRAMITS = json.load(f)
    logger.info(f"Carregats {len(TRAMITS)} tràmits SEPE")
except Exception as e:
    logger.warning(f"No s'han pogut carregar els tràmits SEPE: {e}")


@app.route('/')
def index():
    # Assegurar que la sessió té un user_id
    _get_user_id()

    # Només les cerques d'AQUEST usuari
    active_searches = _get_my_searches()

    communities = LocationManager.get_communities()

    # Preferències d'UI des de la sessió del navegador
    last_dni = session.get('last_dni', '')
    last_email = session.get('last_email', '')
    last_community = session.get('last_community', [])
    last_scope = session.get('last_scope', '')
    last_provinces = session.get('last_provinces', [])
    last_comarques = session.get('last_comarques', [])
    last_municipis = session.get('last_municipis', [])
    last_zip_input = session.get('last_zip_input', '')
    last_appt_types = session.get('last_appt_types', ['person'])
    last_freq_type = session.get('last_freq_type', 'once')
    last_interval = session.get('last_interval', 1)
    last_daily_time = session.get('last_daily_time', '09:00')
    last_tramite_id = session.get('last_tramite_id', '158')

    return render_template('index.html',
                           searches=active_searches,
                           communities=communities,
                           tramits=TRAMITS,
                           last_dni=last_dni,
                           last_email=last_email,
                           last_community=last_community,
                           last_scope=last_scope,
                           last_provinces=last_provinces,
                           last_comarques=last_comarques,
                           last_municipis=last_municipis,
                           last_zip_input=last_zip_input,
                           last_appt_types=last_appt_types,
                           last_freq_type=last_freq_type,
                           last_interval=last_interval,
                           last_daily_time=last_daily_time,
                           last_tramite_id=last_tramite_id)

# API endpoints per als desplegables dinàmics
@app.route('/api/provinces')
def get_provinces_query():
    communities = request.args.getlist('community')
    if not communities:
        return jsonify([])
    return jsonify(LocationManager.get_provinces(communities))

@app.route('/api/provinces/<community>')
def get_provinces(community):
    if community == 'all':
        return jsonify(LocationManager.get_provinces(None))
    return jsonify(LocationManager.get_provinces(community))

@app.route('/api/comarques')
def get_comarques_route():
    province = request.args.getlist('province')
    if not province: province = request.args.get('province')
    return jsonify(LocationManager.get_comarques(province))

@app.route('/api/municipios')
def get_municipios_route():
    province = request.args.getlist('province') # Support multiple
    community = request.args.getlist('community') # Support multiple
    comarca = request.args.getlist('comarca') # Support multiple
    
    # If lists are empty, try single values (backward compatibility or if JS sends single)
    if not province: province = request.args.get('province')
    if not community: community = request.args.get('community')
    if not comarca: comarca = request.args.get('comarca')
    
    return jsonify(LocationManager.get_municipios(province, community, comarca))

@app.route('/start', methods=['POST'])
def start_search():
    dni = request.form.get('dni', '').strip().upper()
    email = request.form.get('email', '').strip()
    appt_types = request.form.getlist('appt_type')
    if not appt_types:
        appt_types = ['person']
    community = request.form.getlist('community')
    scope = request.form.get('scope')
    tramite_id = request.form.get('tramite_id', '158')

    # Guardar preferències d'UI a la sessió del navegador
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

    # Cerques actives des de state.json (compartit amb el worker)
    active_searches = load_state()

    # --- Protecció de sobrecàrrega (global, no per sessió) ---
    total_active = sum(1 for d in active_searches.values() if d.get('active', False))
    if total_active >= MAX_CONCURRENT_SEARCHES:
        flash(f"Error: El servidor ha arribat al límit de {MAX_CONCURRENT_SEARCHES} cerques simultànies. Espera que alguna finalitzi.")
        return redirect(url_for('index'))

    # Determinar el valor segons l'scope
    value = None
    scope_name = "Desconegut"
    extra_context = {'community': community}

    if scope == 'zip':
        raw_value = request.form.get('zip_code_input')
        if raw_value:
            value = [v.strip() for v in raw_value.split(',') if v.strip()]
        else:
            value = []
        scope_name = f"CPs: {', '.join(value)}"
    elif scope == 'municipi':
        value = request.form.getlist('municipi_select')
        scope_name = f"Municipis: {', '.join(value)}"
        prov = request.form.getlist('provincia_select')
        if prov: extra_context['province'] = prov
    elif scope == 'provincia':
        value = request.form.getlist('provincia_select')
        scope_name = f"Províncies: {', '.join(value)}"
    elif scope == 'comarca':
        value = request.form.getlist('comarca_select')
        scope_name = f"Comarques: {', '.join(value)}"
    elif scope == 'all_community':
        value = community
        if not value or (len(value) == 1 and value[0] == ''):
            flash("Error: Has de seleccionar una Comunitat Autònoma.")
            return redirect(url_for('index'))
        scope = 'community'
        scope_name = f"Comunitats: {', '.join(value)}"

    if dni and email and scope:
        if dni in active_searches and active_searches[dni].get('active', False):
            if _owns_search(dni, active_searches):
                flash(f"Error: Ja existeix una cerca activa per al DNI {dni}. Atura-la primer per crear-ne una de nova.")
            else:
                flash(f"Error: Ja existeix una cerca activa per al DNI {dni} (d'un altre dispositiu).")
            return redirect(url_for('index'))
        # Netejar la cerca anterior d'aquest DNI si existeix (inactiva) i és nostra
        if dni in active_searches and _owns_search(dni, active_searches):
            del active_searches[dni]

        zips_to_check = LocationManager.get_zips(scope, value, extra_context)
        if not zips_to_check:
            flash("Error: No s'han trobat codis postals per a aquesta selecció.")
            return redirect(url_for('index'))
        random.shuffle(zips_to_check)
        freq_type = request.form.get('freq_type', 'once')
        interval_hours = request.form.get('interval_hours', 1)
        daily_time = request.form.get('daily_time', '09:00')
        frequency = -1
        if freq_type == 'interval':
            try:
                frequency = int(interval_hours) * 60
            except:
                frequency = 60
        elif freq_type == 'daily':
            frequency = -2
        elif freq_type == 'once':
            frequency = -1

        active_searches[dni] = {
            'zips': zips_to_check,
            'current_zip_index': 0,
            'email': email,
            'appt_types': appt_types,
            'type': appt_types[0],  # Backward compat
            'active': True,
            'scope_name': scope_name,
            'frequency': frequency,
            'freq_type': freq_type,
            'interval_hours': interval_hours,
            'daily_time': daily_time,
            'last_cycle_time': 0,
            'status_message': "Iniciant...",
            'last_result_message': "Pendent de primera execució",
            'tramite_id': tramite_id,
            'run_id': time.time(),
            'owner_id': _get_user_id()
        }
        # Guardar a state.json perquè el worker ho vegi
        save_state(active_searches)

        types_str = ' i '.join(['Presencial' if t == 'person' else 'Telefònica' for t in appt_types])
        msg_html = f"""
            <strong>Cerca iniciada correctament</strong><br>
            <span class="text-muted">DNI:</span> <strong>{dni}</strong> &nbsp;|&nbsp; 
            <span class="text-muted">Zona:</span> {scope_name} <span class="badge bg-light text-dark border"> {len(zips_to_check)} CPs </span> &nbsp;|&nbsp;
            <span class="text-muted">Tipus:</span> {types_str}
        """
        flash(msg_html)

    return redirect(url_for('index'))

@app.route('/api/status')
def get_status():
    """Retorna l'estat de les cerques d'AQUEST usuari (filtrat per owner_id)."""
    active_searches = _get_my_searches()
    status = {}
    for dni, data in active_searches.items():
        curr_zip = "N/A"
        zips = data.get('zips', [])
        idx = data.get('current_zip_index', 0)
        if zips:
            safe_idx = idx if idx < len(zips) else 0
            curr_zip = zips[safe_idx]

        next_run_time = None
        freq_type = data.get('freq_type', 'once')
        last_complete = data.get('last_cycle_time', 0)
        is_active = data.get('active', False)

        if is_active and idx == 0 and (freq_type != 'once'):
            next_dt = None
            try:
                tz_madrid = ZoneInfo("Europe/Madrid")
                now = datetime.now(tz_madrid)
            except:
                now = datetime.utcnow() + timedelta(hours=1)

            if freq_type == 'interval' and last_complete > 0:
                interval_hours = float(data.get('interval_hours', 1))
                next_ts = last_complete + (interval_hours * 3600)
                next_dt = datetime.fromtimestamp(next_ts)
            elif freq_type == 'daily':
                daily_time_str = data.get('daily_time', '09:00')
                try:
                    target_time = datetime.strptime(daily_time_str, '%H:%M').time()
                    today_target = datetime.combine(now.date(), target_time)
                    if now.tzinfo:
                        today_target = today_target.replace(tzinfo=now.tzinfo)
                    if now > today_target:
                        next_dt = today_target + timedelta(days=1)
                    else:
                        next_dt = today_target
                except:
                    pass
            if next_dt:
                time_str = next_dt.strftime('%H:%M')
                if next_dt.date() == now.date():
                    next_run_time = f"Avui {time_str}"
                elif next_dt.date() == (now + timedelta(days=1)).date():
                    next_run_time = f"Demà {time_str}"
                else:
                    next_run_time = next_dt.strftime('%d/%m %H:%M')

        status[dni] = {
            'current_zip': curr_zip,
            'total_zips': len(zips),
            'current_index': idx,
            'active': is_active,
            'last_duration': data.get('last_duration', 'N/A'),
            'status_message': data.get('status_message', ''),
            'last_result_message': data.get('last_result_message', ''),
            'next_run_time': next_run_time,
            'freq_type': freq_type,
            'scope_name': data.get('scope_name', ''),
            'cycle_start_time': data.get('cycle_start_time'),
            'finished_at': data.get('finished_at'),
        }
    return jsonify(status)

@app.route('/api/stop/<dni>', methods=['POST'])
def stop_search_api(dni):
    """Atura una cerca activa (només si pertany a la sessió actual)."""
    active_searches = load_state()
    if dni in active_searches and _owns_search(dni, active_searches):
        active_searches[dni]['active'] = False
        active_searches[dni]['status_message'] = "Aturat manualment"
        active_searches[dni]['finished_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
        save_state(active_searches)
        return jsonify({'status': 'ok', 'message': 'Cerca aturada'})
    return jsonify({'status': 'error', 'message': 'DNI no trobat'}), 404

@app.route('/api/restart/<dni>', methods=['POST'])
def restart_search_api(dni):
    """Reinicia una cerca existent (només si pertany a la sessió actual)."""
    active_searches = load_state()
    if dni in active_searches and _owns_search(dni, active_searches):
        active_searches[dni]['active'] = True
        active_searches[dni]['current_zip_index'] = 0
        active_searches[dni]['cycle_start_time'] = None
        active_searches[dni]['finished_at'] = None
        active_searches[dni]['status_message'] = 'Reiniciant...'
        active_searches[dni]['last_cycle_time'] = 0
        active_searches[dni]['run_id'] = time.time()
        save_state(active_searches)
        return jsonify({'status': 'ok', 'message': 'Cerca reiniciada'})
    return jsonify({'status': 'error', 'message': 'DNI no trobat'}), 404

@app.route('/api/delete/<dni>', methods=['POST'])
def delete_search_api(dni):
    """Elimina una cerca (només si pertany a la sessió actual)."""
    active_searches = load_state()
    if dni in active_searches and _owns_search(dni, active_searches):
        del active_searches[dni]
        save_state(active_searches)
        return jsonify({'status': 'ok', 'message': 'Cerca eliminada'})
    return jsonify({'status': 'error', 'message': 'DNI no trobat'}), 404


@app.route('/api/server-info')
def server_info():
    """Retorna informació de càrrega del servidor per mostrar a la UI."""
    active_searches = load_state()
    total_active = sum(1 for d in active_searches.values() if d.get('active', False))
    total_searches = len(active_searches)
    return jsonify({
        'active_searches': total_active,
        'total_searches': total_searches,
    })


@app.route('/api/logs')
def get_logs():
    """Retorna les últimes línies del log del worker per diagnòstic remot."""
    lines = int(request.args.get('lines', 150))
    log_path = os.path.join(os.path.dirname(__file__), '..', 'data', 'worker.log')
    if not os.path.exists(log_path):
        return jsonify({'logs': '(no log file yet)'}), 200
    try:
        with open(log_path, 'r', encoding='utf-8', errors='replace') as f:
            all_lines = f.readlines()
        tail = all_lines[-lines:]
        return jsonify({'logs': ''.join(tail)}), 200
    except Exception as e:
        return jsonify({'logs': f'Error reading log: {e}'}), 500


@app.route('/api/debug-snapshots')
def list_debug_snapshots():
    """Llista els HTML/screenshots de debug guardats pel bot."""
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
    """Envia un correu de prova per verificar que la configuració funciona."""
    import smtplib
    from email.mime.text import MIMEText
    from email.mime.multipart import MIMEMultipart

    to_email = request.json.get('email') if request.is_json else request.form.get('email')
    if not to_email:
        return jsonify({'status': 'error', 'message': 'Cal un email destinatari'}), 400

    sender_email = os.getenv('MAIL_USERNAME')
    sender_password = os.getenv('MAIL_PASSWORD')

    if not sender_email or not sender_password:
        return jsonify({'status': 'error', 'message': 'Credencials de correu no configurades al servidor (.env)'}), 500

    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = '[BOT CITA SEPE] Correu de prova'
        body = """Hola!

Aquest és un correu de prova enviat des del Bot Cita SEPE.
Si reps aquest missatge, la configuració d'enviament de correus és correcta.

Quan el bot trobi una cita disponible, rebràs una notificació similar a aquesta.

— Bot Cita SEPE"""
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)

        logger.info(f"Correu de prova enviat correctament a {to_email}")
        return jsonify({'status': 'ok', 'message': f'Correu enviat a {to_email}'})
    except Exception as e:
        logger.error(f"Error enviant correu de prova: {e}")
        return jsonify({'status': 'error', 'message': str(e)}), 500


if __name__ == '__main__':
    app.run(debug=True)
