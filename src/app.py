from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_mail import Mail, Message
import time
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
app.secret_key = os.getenv('SECRET_KEY', 'supersecretkey-canvia-en-produccio')

# Configuració del Correu (Gmail per defecte)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

mail = Mail(app)

# --- Límit de cerques simultànies per evitar sobrecàrrega ---
MAX_CONCURRENT_SEARCHES = int(os.getenv('MAX_CONCURRENT_SEARCHES', 10))


@app.route('/')
def index():
    # Cerques actives des de state.json (compartit amb el worker)
    active_searches = load_state()

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

    return render_template('index.html',
                           searches=active_searches,
                           communities=communities,
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
                           last_daily_time=last_daily_time)

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

    # Cerques actives des de state.json (compartit amb el worker)
    active_searches = load_state()

    # --- Protecció de sobrecàrrega ---
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
            flash(f"Error: Ja existeix una cerca activa per al DNI {dni}. Atura-la primer per crear-ne una de nova.")
            return redirect(url_for('index'))
        # Netejar la cerca anterior d'aquest DNI si existeix (inactiva)
        if dni in active_searches:
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
            'last_result_message': "Pendent de primera execució"
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
    """Retorna l'estat actual de totes les cerques actives (state.json) per actualitzar la UI."""
    active_searches = load_state()
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
        }
    return jsonify(status)

@app.route('/api/stop/<dni>', methods=['POST'])
def stop_search_api(dni):
    """Atura una cerca activa (escriu a state.json perquè el worker ho vegi)."""
    active_searches = load_state()
    if dni in active_searches:
        active_searches[dni]['active'] = False
        active_searches[dni]['status_message'] = "Aturat manualment"
        save_state(active_searches)
        return jsonify({'status': 'ok', 'message': 'Cerca aturada'})
    return jsonify({'status': 'error', 'message': 'DNI no trobat'}), 404

@app.route('/api/delete/<dni>', methods=['POST'])
def delete_search_api(dni):
    """Elimina una cerca (escriu a state.json perquè el worker ho vegi)."""
    active_searches = load_state()
    if dni in active_searches:
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


if __name__ == '__main__':
    app.run(debug=True)
