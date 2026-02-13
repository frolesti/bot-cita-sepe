import time
import os
import logging
import sys
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor
from dotenv import load_dotenv

# Afegim el directori arrel al path per poder importar src
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.sepe_bot import SepeBot
from src.common import load_state, save_state

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [WORKER] - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler(sys.stdout)]
)
logger = logging.getLogger(__name__)

load_dotenv()

def send_email(to_email, subject, body):
    sender_email = os.getenv('MAIL_USERNAME')
    sender_password = os.getenv('MAIL_PASSWORD')
    smtp_server = "smtp.gmail.com"
    smtp_port = 465

    if not sender_email or not sender_password:
        logger.warning("No s'han configurat les credencials de correu. No s'enviarà notificació.")
        return

    try:
        msg = MIMEMultipart()
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body, 'plain'))

        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)
        
        logger.info(f"Correu enviat correctament a {to_email}")
    except Exception as e:
        logger.error(f"Error enviant correu: {e}")

def check_single_zip(dni, data, zip_code):
    """Comprova un sol codi postal."""
    try:
        logger.info(f"--> [Thread] Comprovant DNI {dni} a CP {zip_code}")
        # En el worker, SEMPRE headless=True excepte debug explícit
        bot = SepeBot(headless=True) 
        
        # Recuperem tràmit ID si el tenim guardat (per defecte "158" si no hi és)
        tramite_id = data.get('tramite_id', '158')
        
        found = bot.check_appointment(
            zip_code=zip_code, 
            dni=dni, 
            appt_type=data.get('type', 'person'),
            tramite_id=tramite_id
        )
        
        bot.close()
        
        if found:
            logger.info(f"!!! CITA TROBADA per {dni} a {zip_code} !!!")
            return True, zip_code
        else:
            return False, None
            
    except Exception as e:
        logger.error(f"Error comprovant per {dni} a {zip_code}: {e}")
        try:
            bot.close()
        except:
            pass
        return False, None

def run_worker():
    logger.info("Iniciant Worker del Bot SEPE...")
    
    try:
        MAX_WORKERS = int(os.getenv('MAX_WORKERS', 2)) # Més conservador en worker
    except ValueError:
        MAX_WORKERS = 2
        
    logger.info(f"Worker configurat amb {MAX_WORKERS} fils simultanis.")

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

                    # --- GESTIÓ DE FREQÜÈNCIA (Lògica Temporal) ---
                    freq_type = data.get('freq_type', 'once')
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
                                    data['status_message'] = f"En pausa (pròxima: {next_time})"
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
                    # Agafem el següent ZIP a comprovar
                    zips = data['zips']
                    idx = data.get('current_zip_index', 0)
                    
                    if idx < len(zips):
                        zip_to_check = zips[idx]
                        
                        # Actualitzem estat abans de llançar (perquè UI vegi que treballa)
                        data['status_message'] = f"Cercant a {zip_to_check}..."
                        active_searches[dni] = data # Important actualitzar l'objecte pare
                        updates_made = True 
                        
                        future = executor.submit(check_single_zip, dni, data, zip_to_check)
                        futures[future] = (dni, zip_to_check)
                
                # Si hem fet actualitzacions d'estat (missatges "En pausa"), guardem abans de bloquejar en futures
                if updates_made:
                    save_state(active_searches)
                    updates_made = False # Reset

                # Processar resultats dels fils
                for future in futures:
                    dni, checked_zip = futures[future]
                    found, success_zip = future.result()
                    
                    # Recarreguem estat per si ha canviat mentrestant (tot i que en single-thread worker loop és menys crític, 
                    # però la Web pot haver modificat alguna cosa)
                    # Per ara assumim que la Web només AFEGEIX o CANVIA 'active'.
                    # Treballem amb la còpia 'active_searches' que tenim i sobreescriurem al final del loop.
                    
                    data = active_searches.get(dni)
                    if not data: continue # Potser s'ha esborrat

                    if found:
                        # !!! ÈXIT !!!
                        data['active'] = False
                        data['status_message'] = f"ÈXIT! Cita a {success_zip}"
                        data['last_result_message'] = f"CITA DISPONIBLE DETECTADA EL {datetime.now().strftime('%d/%m %H:%M')}"
                        data['last_cycle_time'] = time.time() # Marquem com acabat
                        
                        # Enviar Email
                        email_body = f"""El bot ha trobat una cita!
                        
DNI: {dni}
Codi Postal: {success_zip}
Tipus: {data.get('type')}
Zona: {data.get('scope_name')}

Vés RÀPIDAMENT a la web del SEPE."""
                        send_email(data.get('email'), "¡CITA SEPE TROBADA!", email_body)
                        updates_made = True
                        
                    else:
                        # No trobat, avancem índex
                        data['current_zip_index'] += 1
                        updates_made = True
                        
                        # Comprovem si hem acabat la llista de ZIPs
                        if data['current_zip_index'] >= len(data['zips']):
                            data['current_zip_index'] = 0 # Reset índex
                            data['last_cycle_time'] = time.time() # Marquem fi de cicle
                            
                            # Si era 'once', marquem com acabadat
                            if data.get('freq_type') == 'once':
                                data['active'] = False
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
