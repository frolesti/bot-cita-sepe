from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_mail import Mail, Message
import threading # Mantingut per si alguna altra funció ho usa puntualment, però no pel worker
import time
from datetime import datetime, timedelta
import os
import random
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from src.locations import LocationManager
from src.common import load_state, save_state # Importem funcions compartides
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

# Apply filter to werkzeug logger
logging.getLogger("werkzeug").addFilter(StatusEndpointFilter())

load_dotenv() # Carregar variables d'entorn del fitxer .env

app = Flask(__name__)
app.secret_key = 'supersecretkey'

# Configuració del Correu (Gmail per defecte)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 465
app.config['MAIL_USERNAME'] = os.getenv('MAIL_USERNAME')
app.config['MAIL_PASSWORD'] = os.getenv('MAIL_PASSWORD')
app.config['MAIL_USE_TLS'] = False
app.config['MAIL_USE_SSL'] = True

mail = Mail(app)

import shutil
import tempfile

# Emmagatzematge en memòria
# Estructura: { 'dni': { ... } }
# Ara es carrega via load_state() des de src.common en iniciar
active_searches = load_state()

# Eliminem logica local de save_state/load_state ja que usem common.py

# check_single_zip i background_checker han sigut moguts a src/worker.py per millorar arquitectura

@app.route('/')
def index():
    # Recarreguem estat del disc per veure progrés del worker
    global active_searches
    active_searches = load_state()

    communities = LocationManager.get_communities()

    # Retrieve last used values from session
    last_dni = session.get('last_dni', '')
    last_email = session.get('last_email', '')
    
    # Retrieve extended last used values
    last_community = session.get('last_community', [])
    last_scope = session.get('last_scope', '')
    last_provinces = session.get('last_provinces', [])
    last_comarques = session.get('last_comarques', [])
    last_municipis = session.get('last_municipis', [])
    last_zip_input = session.get('last_zip_input', '')
    last_appt_type = session.get('last_appt_type', 'person')
    last_freq_type = session.get('last_freq_type', 'once')
    last_interval = session.get('last_interval', 1)
    last_daily_time = session.get('last_daily_time', '09:00')
    
    # Check if any search is active
    has_active_search = any(data['active'] for data in active_searches.values())
    
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
                           last_appt_type=last_appt_type,
                           last_freq_type=last_freq_type,
                           last_interval=last_interval,
                           last_daily_time=last_daily_time,
                           has_active_search=has_active_search)

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
    dni = request.form.get('dni')
    email = request.form.get('email')
    appt_type = request.form.get('appt_type')
    
    community = request.form.getlist('community') # Multiple
    scope = request.form.get('scope') # all_community, provincia, municipi, zip, comarca
    
    # Save to session for persistence
    session['last_dni'] = dni
    session['last_email'] = email
    session['last_community'] = community
    session['last_scope'] = scope
    session['last_provinces'] = request.form.getlist('provincia_select')
    session['last_comarques'] = request.form.getlist('comarca_select')
    session['last_municipis'] = request.form.getlist('municipi_select')
    session['last_zip_input'] = request.form.get('zip_code_input')
    session['last_appt_type'] = appt_type
    session['last_freq_type'] = request.form.get('freq_type')
    session['last_interval'] = request.form.get('interval_hours')
    session['last_daily_time'] = request.form.get('daily_time')
    
    # Determinar el valor segons l'scope
    value = None
    scope_name = "Desconegut"
    extra_context = {'community': community}
    
    if scope == 'zip':
        raw_value = request.form.get('zip_code_input')
        # Permetre llista separada per comes
        if raw_value:
            value = [v.strip() for v in raw_value.split(',') if v.strip()]
        else:
            value = []
        scope_name = f"CPs: {', '.join(value)}"
    elif scope == 'municipi':
        value = request.form.getlist('municipi_select')
        scope_name = f"Municipis: {', '.join(value)}"
        # Afegim la província al context si està seleccionada
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
        # Validació extra per si no s'ha seleccionat comunitat
        if not value or (len(value) == 1 and value[0] == ''):
            flash("Error: Has de seleccionar una Comunitat Autònoma.")
            return redirect(url_for('index'))
        scope = 'community'
        scope_name = f"Comunitats: {', '.join(value)}"

    if dni and email and scope:
        # Obtenir la llista de ZIPS
        zips_to_check = LocationManager.get_zips(scope, value, extra_context)
        
        if not zips_to_check:
            flash("Error: No s'han trobat codis postals per a aquesta selecció.")
            return redirect(url_for('index'))

        # Barregem els zips perquè si hi ha molts usuaris no comprovin tots el mateix ordre
        random.shuffle(zips_to_check)
        
        # Processar freqüència
        freq_type = request.form.get('freq_type', 'once')
        interval_hours = request.form.get('interval_hours', 1)
        daily_time = request.form.get('daily_time', '09:00')
        
        frequency = -1 # Default to once
        
        if freq_type == 'interval':
            try:
                frequency = int(interval_hours) * 60 # Convert hours to minutes
            except:
                frequency = 60
        elif freq_type == 'daily':
            frequency = -2 # Special code for daily
        elif freq_type == 'once':
            frequency = -1

        active_searches[dni] = {
            'zips': zips_to_check,
            'current_zip_index': 0,
            'email': email,
            'type': appt_type,
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
        save_state(active_searches) # Guardem la nova cerca
        flash(f"Cerca iniciada per al DNI {dni}. Zona: {scope_name} ({len(zips_to_check)} codis postals)")
    
    return redirect(url_for('index'))

@app.route('/api/status')
def get_status():
    """Retorna l'estat actual de les cerques actives per actualitzar la UI dinàmicament."""
    global active_searches
    active_searches = load_state() # Refresquem per veure canvis del worker
    status = {}
    for dni, data in active_searches.items():
        curr_zip = "N/A"
        if data.get('zips') and len(data['zips']) > 0:
            idx = data.get('current_zip_index', 0)
            total = len(data['zips'])
            prev_idx = (idx - 1) % total if total > 0 else 0
            curr_zip = data['zips'][prev_idx]
        
        status[dni] = {
            'current_zip': curr_zip,
            'total_zips': len(data['zips']),
            'current_index': data.get('current_zip_index', 0),
            'active': data.get('active', False),
            'last_duration': data.get('last_duration', 'N/A'),
            'status_message': data.get('status_message', ''),
            'last_result_message': data.get('last_result_message', '')
        }
    return jsonify(status)

@app.route('/stop/<dni>')
def stop_search_web(dni):
    global active_searches
    active_searches = load_state()
    if dni in active_searches:
        active_searches[dni]['active'] = False
        active_searches[dni]['status_message'] = "Aturat manualment"
        save_state(active_searches)
        flash(f"Cerca aturada per al DNI {dni}")
    return redirect(url_for('index'))

@app.route('/api/stop/<dni>', methods=['POST'])
def stop_search_api(dni):
    global active_searches
    active_searches = load_state()
    if dni in active_searches:
        active_searches[dni]['active'] = False
        active_searches[dni]['status_message'] = "Aturat manualment"
        save_state(active_searches)
        return jsonify({'status': 'ok', 'message': 'Cerca aturada'})
    return jsonify({'status': 'error', 'message': 'DNI no trobat'}), 404

@app.route('/api/delete/<dni>', methods=['POST'])
def delete_search_api(dni):
    global active_searches
    active_searches = load_state()
    if dni in active_searches:
        del active_searches[dni]
        save_state(active_searches)
        return jsonify({'status': 'ok', 'message': 'Cerca eliminada'})
    return jsonify({'status': 'error', 'message': 'DNI no trobat'}), 404

if __name__ == '__main__':
    app.run(debug=True)
