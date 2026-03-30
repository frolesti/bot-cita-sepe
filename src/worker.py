import time
import os
import logging
import sys
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# Afegim el directori arrel al path per poder importar src
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.sepe_api import check_zip
from src.state import load_state, save_state
from src.email_service import send_email, build_appointment_email
from src.search_service import MAX_RECURRENCE_HOURS, MAX_RECURRENCE_HOURS_DAILY

# Configurar logging — stdout + fitxer rotatiu perquè /api/logs pugui llegir-lo
LOG_FILE = os.path.join(os.path.dirname(__file__), '..', 'data', 'worker.log')
os.makedirs(os.path.dirname(LOG_FILE), exist_ok=True)

from logging.handlers import RotatingFileHandler

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [WORKER] - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout),
        RotatingFileHandler(LOG_FILE, maxBytes=500_000, backupCount=1, encoding='utf-8'),
    ]
)
logger = logging.getLogger(__name__)

load_dotenv()


def check_single_zip(dni, data, zip_code):
    """Comprova un sol codi postal via HTTP API (sense Chrome)."""
    try:
        logger.info(f"--> [Thread] Comprovant DNI {dni} a CP {zip_code}")
        
        # Recuperem tràmit ID si el tenim guardat (per defecte "158" si no hi és)
        tramite_id = data.get('tramite_id', '158')
        
        # Suport multi-tipus: appt_types (llista) o fallback a type (string)
        appt_types = data.get('appt_types', [data.get('type', 'person')])
        
        results = check_zip(
            zip_code=zip_code, 
            dni=dni, 
            appt_types=appt_types,
            tramite_id=tramite_id
        )
        
        # Extreure info d'oficines (si n'hi ha)
        offices_info = results.get('offices', [])
        
        # Mirar si algun tipus ha trobat cita
        for appt_type, found in results.items():
            if appt_type == 'offices':
                continue  # Skip metadata key
            if found:
                type_name = 'Presencial' if appt_type == 'person' else 'Telefònica'
                logger.info(f"!!! CITA {type_name} TROBADA per {dni} a {zip_code} !!!")
                return True, zip_code, appt_type, offices_info
        
        return False, None, None, []
            
    except Exception as e:
        logger.error(f"Error comprovant per {dni} a {zip_code}: {e}")
        return False, None, None, []

def run_worker():
    logger.info("Iniciant Worker del Bot SEPE...")
    
    try:
        MAX_WORKERS = int(os.getenv('MAX_WORKERS', 3)) # Fils simultanis per verificar CPs en paral·lel
    except ValueError:
        MAX_WORKERS = 3
    
    try:
        BATCH_SIZE = int(os.getenv('BATCH_SIZE', 3)) # CPs a comprovar per DNI per iteració
    except ValueError:
        BATCH_SIZE = 3
        
    logger.info(f"Worker configurat amb {MAX_WORKERS} fils simultanis i BATCH_SIZE={BATCH_SIZE}.")

    while True:
        try:
            start_time = time.time()
            active_searches = load_state()
            
            if not active_searches:
                # Si no hi ha res a fer, dormim més
                time.sleep(10)
                continue

            # Itera sobre còpia per seguretat
            active_items = list(active_searches.items())
            updates_made = False

            with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
                futures = {}
                
                # Planifiquem tasques
                for dni, data in active_items:
                    if not data.get('active', False) or not data.get('zips'):
                        continue

                    # --- LÍMIT DE RECURRÈNCIA ---
                    freq_type = data.get('freq_type', 'once')
                    if freq_type != 'once':
                        created_at = data.get('created_at', 0)
                        max_h = MAX_RECURRENCE_HOURS_DAILY if freq_type == 'daily' else MAX_RECURRENCE_HOURS
                        if created_at and (time.time() - created_at) > max_h * 3600:
                            data['active'] = False
                            if freq_type == 'daily':
                                data['status_message'] = f"Expirada (màxim {max_h // 24} dies de recurrència)"
                            else:
                                data['status_message'] = f"Expirada (màxim {max_h}h de recurrència)"
                            data['finished_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                            updates_made = True
                            logger.info(f"Cerca {dni} expirada per límit de recurrència ({max_h}h)")
                            continue

                    # --- GESTIÓ DE FREQÜÈNCIA (Lògica Temporal) ---
                    last_complete = data.get('last_cycle_time', 0)
                    now = time.time()
                    
                    should_run = False
                    
                    # Si encara no hem acabat la volta actual (current_zip_index > 0), continuem
                    if data.get('current_zip_index', 0) > 0:
                        should_run = True
                    else:
                        # Estem a l'inici d'un cicle, comprovem si toca començar
                        if last_complete == 0:
                            should_run = True # Primera vegada
                        else:
                            # Ja hem acabat almenys una volta, mirem temporització
                            if freq_type == 'once':
                                # Ja s'hauria d'haver marcat com inactiu, però per si de cas
                                data['active'] = False
                                data['status_message'] = "Finalitzat (mode 'una vegada')"
                                updates_made = True
                                should_run = False
                                
                            elif freq_type == 'interval':
                                interval_hours = float(data.get('interval_hours', 1))
                                if (now - last_complete) >= (interval_hours * 3600):
                                    should_run = True
                                else:
                                    # Calculate next run time
                                    next_ts = last_complete + (interval_hours * 3600)
                                    next_time = datetime.fromtimestamp(next_ts).strftime('%H:%M')
                                    data['status_message'] = f"En pausa (propera: {next_time})"
                                    updates_made = True
                                    
                            elif freq_type == 'daily':
                                daily_time_str = data.get('daily_time', '09:00')
                                # Simplificació: si ja hem corregut avui, no correm més
                                last_dt = datetime.fromtimestamp(last_complete)
                                now_dt = datetime.now()
                                target_time = datetime.strptime(daily_time_str, '%H:%M').time()
                                
                                if last_dt.date() < now_dt.date() and now_dt.time() >= target_time:
                                    should_run = True
                                else:
                                    data['status_message'] = f"En pausa fins demà a les {daily_time_str}"
                                    updates_made = True

                    if not should_run:
                        continue

                    # --- EXECUCIÓ ---
                    # Registrem inici de cicle si toca
                    if data.get('current_zip_index', 0) == 0 and not data.get('cycle_start_time'):
                        data['cycle_start_time'] = time.time()

                    # Agafem un BATCH de ZIPs a comprovar en paral·lel
                    zips = data['zips']
                    idx = data.get('current_zip_index', 0)
                    
                    if idx < len(zips):
                        batch_end = min(idx + BATCH_SIZE, len(zips))
                        batch_zips = zips[idx:batch_end]
                        
                        # Actualitzem estat abans de llançar (perquè UI vegi que treballa)
                        data['status_message'] = f"Cercant a {batch_zips[0]}..."
                        active_searches[dni] = data # Important actualitzar l'objecte pare
                        updates_made = True 
                        
                        for zip_to_check in batch_zips:
                            run_id = data.get('run_id', 0)
                            future = executor.submit(check_single_zip, dni, data, zip_to_check)
                            futures[future] = (dni, zip_to_check, run_id)
                
                # Si hem fet actualitzacions d'estat (missatges "En pausa"), guardem abans de bloquejar en futures
                if updates_made:
                    save_state(active_searches)
                    updates_made = False # Reset

                # Recarreguem estat fresc del disc per capturar stop/restart/delete
                active_searches = load_state()

                # Processar resultats dels fils
                for future in futures:
                    dni, checked_zip, submitted_run_id = futures[future]
                    found, success_zip, found_type, offices_info = future.result()
                    
                    data = active_searches.get(dni)
                    if not data:
                        continue  # Esborrat durant el processament

                    # Si l'usuari ha aturat o reiniciat, ignorem resultats antics
                    if not data.get('active'):
                        continue
                    if data.get('run_id', 0) != submitted_run_id:
                        logger.info(f"Ignorant resultat antic de {checked_zip} per {dni} (cerca reiniciada)")
                        continue

                    if found:
                        # !!! ÈXIT !!!
                        type_name = 'Presencial' if found_type == 'person' else 'Telefònica'
                        now_str = datetime.now().strftime('%d/%m %H:%M')
                        data['status_message'] = f"ÈXIT! Cita {type_name} al CP {success_zip}"
                        data['last_result_message'] = f"CITA {type_name} DISPONIBLE DETECTADA EL {now_str}"
                        data['last_success'] = f"Cita {type_name} al CP {success_zip} ({now_str})"
                        data['last_cycle_time'] = time.time()
                        
                        # Determinar tipus de cita per al correu
                        appt_types = data.get('appt_types', [data.get('type', 'person')])
                        types_str = ' i '.join(['Presencial' if t == 'person' else 'Telefònica' for t in appt_types])
                        
                        # Enviar Email HTML estilitzat
                        email_html = build_appointment_email(
                            dni, success_zip, type_name, types_str,
                            data.get('scope_name', ''), offices_info,
                            freq_type=data.get('freq_type', 'once')
                        )
                        send_email(data.get('email'), f"\U00002705 CITA SEPE TROBADA! ({type_name} a {success_zip})", email_html)
                        
                        # Aturem la cerca (tant 'once' com recurrents)
                        data['active'] = False
                        data['finished_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                        freq_type = data.get('freq_type', 'once')
                        if freq_type != 'once':
                            data['status_message'] += f" (cerca aturada automàticament)"
                            logger.info(f"Cerca recurrent {dni}: èxit trobat, aturant automàticament")
                        updates_made = True
                        
                    else:
                        # No trobat, avancem índex
                        logger.info(f"    CP {checked_zip} — no trobat.")
                        data['current_zip_index'] += 1
                        updates_made = True
                        
                        # Comprovem si hem acabat la llista de ZIPs
                        if data['current_zip_index'] >= len(data['zips']):
                            data['current_zip_index'] = 0 # Reset índex
                            data['last_cycle_time'] = time.time() # Marquem fi de cicle
                            data['cycle_start_time'] = None  # Reset per al pròxim cicle
                            
                            # Si era 'once', marquem com acabadat
                            if data.get('freq_type') == 'once':
                                data['active'] = False
                                data['finished_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                                data['status_message'] = "Finalitzat sense èxit."
                            else:
                                data['status_message'] = "Cicle completat. Esperant següent interval."
            
            # Guardem canvis al final de la iteració del bucle principal
            if updates_made:
                save_state(active_searches)

            # Petita pausa per no saturar CPU en bucles molt ràpids
            time.sleep(2)

        except Exception as e:
            logger.error(f"Error al bucle principal del Worker: {e}")
            time.sleep(5)

if __name__ == "__main__":
    run_worker()
