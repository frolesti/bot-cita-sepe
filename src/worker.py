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

def send_email(to_email, subject, body_html):
    sender_email = os.getenv('MAIL_USERNAME')
    sender_password = os.getenv('MAIL_PASSWORD')
    smtp_server = "smtp.gmail.com"
    smtp_port = 465

    if not sender_email or not sender_password:
        logger.warning("No s'han configurat les credencials de correu. No s'enviarà notificació.")
        return

    try:
        msg = MIMEMultipart('alternative')
        msg['From'] = sender_email
        msg['To'] = to_email
        msg['Subject'] = subject
        msg.attach(MIMEText(body_html, 'html', 'utf-8'))

        with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)

        logger.info(f"Correu enviat correctament a {to_email}")
    except Exception as e:
        logger.error(f"Error enviant correu: {e}")


def _build_email_html(dni, success_zip, type_name, types_str, scope_name, offices_info):
    """Genera un email HTML estilitzat similar a la pàgina de resultats del SEPE."""
    now_str = datetime.now().strftime('%d/%m/%Y %H:%M')
    sepe_url = 'https://sede.sepe.gob.es/portalSede/procedimientos-y-servicios/personas/proteccion-por-desempleo/cita-previa/cita-previa-solicitud.html'

    # Construir llista d'oficines
    offices_html = ''
    if offices_info:
        rows = []
        for i, office in enumerate(offices_info):
            if isinstance(office, dict):
                name = office.get('name', f'Oficina {i+1}')
                date = office.get('date', '')
            else:
                name = str(office)
                date = ''
            letter = chr(65 + i) if i < 26 else str(i + 1)  # A, B, C...
            date_html = f'<div style="background:#e8f5e9;border-left:3px solid #2e7d32;padding:6px 10px;margin-top:4px;font-size:13px;color:#1b5e20;border-radius:3px;">Primer buit disponible:<br><strong>{date}</strong></div>' if date else ''
            rows.append(f'''
            <div style="padding:12px 14px;border-bottom:1px solid #e0e0e0;">
                <div style="display:flex;align-items:flex-start;gap:10px;">
                    <div style="background:#00796b;color:white;width:28px;height:28px;border-radius:50%;display:inline-flex;align-items:center;justify-content:center;font-weight:bold;font-size:13px;flex-shrink:0;">{letter}</div>
                    <div style="flex:1;">
                        <div style="font-weight:600;color:#263238;font-size:14px;">{name}</div>
                        {date_html}
                    </div>
                </div>
            </div>''')
        offices_html = f'''
        <div style="margin-top:20px;">
            <div style="background:#00796b;color:white;padding:10px 14px;font-weight:600;font-size:14px;border-radius:6px 6px 0 0;">Oficines disponibles</div>
            <div style="border:1px solid #e0e0e0;border-top:none;border-radius:0 0 6px 6px;background:white;">
                {''.join(rows)}
            </div>
        </div>'''

    return f'''
<!DOCTYPE html>
<html>
<head><meta charset="utf-8"></head>
<body style="margin:0;padding:0;background:#f5f5f5;font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,sans-serif;">
<div style="max-width:560px;margin:20px auto;background:white;border-radius:8px;overflow:hidden;box-shadow:0 2px 8px rgba(0,0,0,0.1);">

    <!-- Header -->
    <div style="background:#00796b;padding:24px 20px;text-align:center;">
        <div style="font-size:28px;margin-bottom:6px;">&#9989;</div>
        <div style="color:white;font-size:22px;font-weight:700;letter-spacing:0.5px;">Cita Disponible!</div>
        <div style="color:#b2dfdb;font-size:13px;margin-top:4px;">{now_str}</div>
    </div>

    <!-- Info -->
    <div style="padding:20px;">
        <table style="width:100%;border-collapse:collapse;font-size:14px;color:#37474f;">
            <tr>
                <td style="padding:8px 0;color:#78909c;width:130px;">DNI</td>
                <td style="padding:8px 0;font-weight:600;">{dni}</td>
            </tr>
            <tr>
                <td style="padding:8px 0;color:#78909c;">Codi Postal</td>
                <td style="padding:8px 0;font-weight:600;">{success_zip}</td>
            </tr>
            <tr>
                <td style="padding:8px 0;color:#78909c;">Tipus trobat</td>
                <td style="padding:8px 0;"><span style="background:#e8f5e9;color:#2e7d32;padding:2px 10px;border-radius:12px;font-weight:600;font-size:13px;">{type_name}</span></td>
            </tr>
            <tr>
                <td style="padding:8px 0;color:#78909c;">Zona</td>
                <td style="padding:8px 0;">{scope_name}</td>
            </tr>
        </table>

        {offices_html}

        <!-- CTA Button -->
        <div style="text-align:center;margin-top:24px;">
            <a href="{sepe_url}" style="display:inline-block;background:#d32f2f;color:white;text-decoration:none;padding:14px 32px;border-radius:6px;font-weight:700;font-size:15px;letter-spacing:0.3px;">Reservar cita ara &rarr;</a>
        </div>
        <p style="text-align:center;color:#90a4ae;font-size:12px;margin-top:12px;">El bot <strong>no</strong> reserva automàticament. Ves a la web del SEPE per completar la reserva.</p>
    </div>

    <!-- Footer -->
    <div style="background:#fafafa;padding:14px 20px;text-align:center;border-top:1px solid #e0e0e0;">
        <span style="color:#b0bec5;font-size:12px;">Bot Cita SEPE &mdash; <a href="https://frolesti.aixeta.cat/ca" style="color:#00796b;text-decoration:none;">frolesti.aixeta.cat</a></span>
    </div>
</div>
</body>
</html>'''

def check_single_zip(dni, data, zip_code):
    """Comprova un sol codi postal."""
    try:
        logger.info(f"--> [Thread] Comprovant DNI {dni} a CP {zip_code}")
        # En el worker, SEMPRE headless=True excepte debug explícit
        bot = SepeBot(headless=True) 
        
        # Recuperem tràmit ID si el tenim guardat (per defecte "158" si no hi és)
        tramite_id = data.get('tramite_id', '158')
        
        # Suport multi-tipus: appt_types (llista) o fallback a type (string)
        appt_types = data.get('appt_types', [data.get('type', 'person')])
        
        results = bot.check_appointment(
            zip_code=zip_code, 
            dni=dni, 
            appt_types=appt_types,
            tramite_id=tramite_id
        )
        
        bot.close()
        
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
        try:
            bot.close()
        except:
            pass
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
                        data['status_message'] = f"Cercant a {batch_zips[0]}... ({len(batch_zips)} CPs en paral·lel)"
                        active_searches[dni] = data # Important actualitzar l'objecte pare
                        updates_made = True 
                        
                        for zip_to_check in batch_zips:
                            future = executor.submit(check_single_zip, dni, data, zip_to_check)
                            futures[future] = (dni, zip_to_check)
                
                # Si hem fet actualitzacions d'estat (missatges "En pausa"), guardem abans de bloquejar en futures
                if updates_made:
                    save_state(active_searches)
                    updates_made = False # Reset

                # Processar resultats dels fils
                for future in futures:
                    dni, checked_zip = futures[future]
                    found, success_zip, found_type, offices_info = future.result()
                    
                    # Recarreguem estat per si ha canviat mentrestant
                    data = active_searches.get(dni)
                    if not data: continue # Potser s'ha esborrat

                    if found:
                        # !!! ÈXIT !!!
                        type_name = 'Presencial' if found_type == 'person' else 'Telefònica'
                        data['active'] = False
                        data['finished_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
                        data['status_message'] = f"ÈXIT! Cita {type_name} a {success_zip}"
                        data['last_result_message'] = f"CITA {type_name} DISPONIBLE DETECTADA EL {datetime.now().strftime('%d/%m %H:%M')}"
                        data['last_cycle_time'] = time.time() # Marquem com acabat
                        
                        # Determinar tipus de cita per al correu
                        appt_types = data.get('appt_types', [data.get('type', 'person')])
                        types_str = ' i '.join(['Presencial' if t == 'person' else 'Telefònica' for t in appt_types])
                        
                        # Enviar Email HTML estilitzat
                        email_html = _build_email_html(
                            dni, success_zip, type_name, types_str,
                            data.get('scope_name', ''), offices_info
                        )
                        send_email(data.get('email'), f"\U00002705 CITA SEPE TROBADA! ({type_name} a {success_zip})", email_html)
                        updates_made = True
                        
                    else:
                        # No trobat, avancem índex
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
