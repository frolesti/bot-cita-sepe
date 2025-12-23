from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_mail import Mail, Message
import threading
import time
from datetime import datetime, timedelta
import os
import random
import json
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv
from src.sepe_bot import SepeBot
from src.locations import LocationManager
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
# Estructura: 
# { 
#   'dni': { 
#       'zips': ['08001', '08002', ...], 
#       'current_zip_index': 0,
#       'email': '...', 
#       'type': '...', 
#       'active': True,
#       'scope_name': 'Barcelonès' 
#   } 
# }
active_searches = {}
STATE_FILE = os.path.join('data', 'state.json')

def save_state():
    """Guarda l'estat de les cerques actives a un fitxer JSON de manera atòmica."""
    try:
        # Write to a temporary file first to prevent corruption on crash
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(STATE_FILE), text=True)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(active_searches, f, ensure_ascii=False, indent=4)
        # Atomic replacement
        os.replace(tmp_path, STATE_FILE)
    except Exception as e:
        logger.error(f"Error guardant l'estat: {e}")
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass

def load_state():
    """Carrega l'estat de les cerques actives des d'un fitxer JSON."""
    global active_searches
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                active_searches = json.load(f)
            logger.info(f"Estat carregat: {len(active_searches)} cerques actives recuperades.")
        except Exception as e:
            logger.error(f"Error carregant l'estat: {e}")
            active_searches = {}

# Carreguem l'estat inicial en arrencar
load_state()

def check_single_zip(dni, data, zip_code):
    """Helper function to check a single zip code in a thread."""
    try:
        logger.info(f"--> [Thread] Comprovant DNI {dni} a CP {zip_code}")
        bot = SepeBot(headless=True) # Headless activat per defecte
        found = bot.check_appointment(zip_code, dni, data['type'])
        
        if found:
            logger.info(f"!!! CITA TROBADA per {dni} a {zip_code} !!!")
            # ATURAR LA CERCA PER AQUEST DNI
            data['active'] = False
            data['status_message'] = f"Èxit! Cita a {zip_code}"
            data['last_result_message'] = f"CITA TROBADA a {zip_code}!"
            logger.info(f"Aturant cerca automàtica per {dni} perquè l'usuari pugui gestionar la cita.")

            with app.app_context():
                try:
                    msg = Message('¡CITA DISPONIBLE AL SEPE!', 
                                sender=app.config['MAIL_USERNAME'], 
                                recipients=[data['email']])
                    
                    msg.body = f"""Hola!

El bot ha detectat una CITA DISPONIBLE al SEPE!

Dades de la troballa:
---------------------
DNI: {dni}
Tipus de cita: {data['type']}
Zona de cerca: {data['scope_name']}
Codi Postal amb disponibilitat: {zip_code}

Accedeix ràpidament a la web del SEPE per confirmar-la:
https://sede.sepe.gob.es/portalSede/procedimientos-y-servicios/personas/proteccion-por-desempleo/cita-previa/cita-previa-solicitud.html

Molta sort!
Bot Cita SEPE
"""
                    mail.send(msg)
                    logger.info(f"Correu enviat a {data['email']}")
                except Exception as e_mail:
                    logger.error(f"Error enviant mail: {e_mail}")
            
            # Si trobem cita, deixem el navegador obert (o el tanquem si volem, però millor deixar-lo si no fos headless)
            # Com que és headless, el tanquem, l'usuari haurà d'entrar manualment.
            bot.close()
            return True
        else:
            logger.info(f"No s'ha trobat cita per {dni} a {zip_code}.")
            bot.close()
            return False
    except Exception as e:
        logger.error(f"Error comprovant per {dni} a {zip_code}: {e}")
        try:
            bot.close()
        except:
            pass
        return False

def background_checker():
    """Funció que s'executa en segon pla per comprovar cites."""
    logger.info("Iniciant fil de comprovació en segon pla...")
    
    # ThreadPoolExecutor per paral·lelitzar
    try:
        MAX_WORKERS = int(os.getenv('MAX_WORKERS', 3))
    except ValueError:
        MAX_WORKERS = 3
    
    logger.info(f"Iniciant cerca paral·lela amb {MAX_WORKERS} fils (workers)...")
    
    while True:
        try:
            count = len(active_searches)
            if count > 0:
                # logger.info(f"Comprovant {count} cerques actives...")
                pass
            
            active_tasks = []
            tasks_launched = False
            
            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                for dni, data in list(active_searches.items()):
                    if not data['active'] or not data['zips']:
                        continue

                    # --- SCHEDULING LOGIC ---
                    freq_type = data.get('freq_type', 'once')
                    last_complete = data.get('last_cycle_time', 0)
                    
                    # Check if we are at the start of a cycle (waiting to start)
                    if data['current_zip_index'] == 0 and last_complete > 0:
                        now = time.time()
                        
                        if freq_type == 'once':
                            # Should have stopped already, but just in case
                            logger.info(f"Cerca {dni} finalitzada (mode 'Una sola vegada').")
                            data['active'] = False
                            data['status_message'] = "Sense èxit"
                            save_state()
                            continue
                            
                        elif freq_type == 'interval':
                            interval_hours = float(data.get('interval_hours', 1))
                            interval_seconds = interval_hours * 3600
                            elapsed = now - last_complete
                            
                            if elapsed < interval_seconds:
                                # Still waiting
                                remaining_sec = interval_seconds - elapsed
                                remaining_min = int(remaining_sec / 60)
                                next_run = datetime.fromtimestamp(last_complete + interval_seconds).strftime('%H:%M')
                                data['status_message'] = f"En pausa fins {next_run} ({remaining_min} min)"
                                continue
                            else:
                                # Time to run again
                                data['status_message'] = "Reactivant cerca..."
                                
                        elif freq_type == 'daily':
                            daily_time_str = data.get('daily_time', '09:00')
                            try:
                                target_time = datetime.strptime(daily_time_str, '%H:%M').time()
                                now_dt = datetime.now()
                                last_run_dt = datetime.fromtimestamp(last_complete)
                                
                                # If we already ran today (and finished), wait for tomorrow
                                if last_run_dt.date() == now_dt.date():
                                    # Wait for tomorrow
                                    data['status_message'] = f"En pausa fins demà a les {daily_time_str}"
                                    continue
                                
                                # If we haven't ran today, check if it's time
                                if now_dt.time() < target_time:
                                    data['status_message'] = f"En pausa fins les {daily_time_str}"
                                    continue
                                    
                                # It's time (or past time) and we haven't run today
                                data['status_message'] = "Reactivant cerca..."
                                
                            except ValueError:
                                logger.error(f"Invalid time format for {dni}: {daily_time_str}")
                                data['active'] = False
                                continue

                    # --- EXECUTION LOGIC ---
                    # If we are here, we should run checks
                    data['status_message'] = f"Cercant... (Zona {data['current_zip_index'] + 1}/{len(data['zips'])})"
                    
                    num_parallel_zips = MAX_WORKERS
                    cycle_completed_in_this_batch = False
                    
                    if data['current_zip_index'] == 0:
                        data['current_cycle_start'] = time.time()

                    for _ in range(num_parallel_zips):
                        current_zip = data['zips'][data['current_zip_index']]
                        
                        future = executor.submit(check_single_zip, dni, data, current_zip)
                        active_tasks.append(future)
                        tasks_launched = True
                        
                        data['current_zip_index'] = (data['current_zip_index'] + 1) % len(data['zips'])
                        
                        if data['current_zip_index'] == 0:
                            cycle_completed_in_this_batch = True
                            break
                    
                    if cycle_completed_in_this_batch:
                        now = time.time()
                        data['last_cycle_time'] = now
                        
                        start_time = data.get('current_cycle_start', now)
                        duration = now - start_time
                        data['last_duration'] = f"{int(duration)} segons"
                        
                        if freq_type == 'once':
                            logger.info(f"Cicle finalitzat per {dni} (Mode 'Una sola vegada'). Aturant.")
                            data['active'] = False
                            data['status_message'] = "Sense èxit"
                            data['last_result_message'] = f"Finalitzat sense èxit ({len(data['zips'])} CPs comprovats)"
                        elif freq_type == 'interval':
                            interval_hours = float(data.get('interval_hours', 1))
                            next_run = datetime.fromtimestamp(now + (interval_hours * 3600)).strftime('%H:%M')
                            data['status_message'] = f"En pausa fins {next_run}"
                            data['last_result_message'] = f"Última volta sense èxit ({len(data['zips'])} CPs comprovats)"
                        elif freq_type == 'daily':
                            daily_time_str = data.get('daily_time', '09:00')
                            data['status_message'] = f"En pausa fins demà a les {daily_time_str}"
                            data['last_result_message'] = f"Última volta sense èxit ({len(data['zips'])} CPs comprovats)"

                save_state()
                
                for future in active_tasks:
                    try:
                        future.result(timeout=120)
                    except Exception as e:
                        logger.error(f"Error o Timeout en una tasca del thread pool: {e}")

            if not tasks_launched:
                time.sleep(5)
            else:
                time.sleep(1) 
                
        except Exception as e:
            logger.error(f"Error general al background_checker: {e}")
            time.sleep(60)

# Iniciem el fil en segon pla
checker_thread = threading.Thread(target=background_checker, daemon=True)
checker_thread.start()

@app.route('/')
def index():
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
        save_state() # Guardem la nova cerca
        flash(f"Cerca iniciada per al DNI {dni}. Zona: {scope_name} ({len(zips_to_check)} codis postals)")
    
    return redirect(url_for('index'))

@app.route('/api/status')
def get_status():
    """Retorna l'estat actual de les cerques actives per actualitzar la UI dinàmicament."""
    status = {}
    for dni, data in active_searches.items():
        current_zip = "N/A"
        if data['zips'] and len(data['zips']) > 0:
            # Mostrem el rang de CPs que s'estan comprovant si n'hi ha més d'un en vol
            idx = data['current_zip_index']
            total = len(data['zips'])
            # Això és aproximat perquè l'índex ja ha avançat
            prev_idx = (idx - 1) % total
            current_zip = data['zips'][prev_idx]
        
        status[dni] = {
            'current_zip': current_zip,
            'total_zips': len(data['zips']),
            'current_index': data['current_zip_index'], # 0-based internally, but represents "next to check"
            'active': data['active'],
            'last_duration': data.get('last_duration', 'N/A'),
            'status_message': data.get('status_message', ''),
            'last_result_message': data.get('last_result_message', '')
        }
    return jsonify(status)

@app.route('/stop/<dni>')
def stop_search(dni):
    if dni in active_searches:
        del active_searches[dni]
        save_state() # Guardem l'eliminació
        flash(f"Cerca aturada per al DNI {dni}")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
