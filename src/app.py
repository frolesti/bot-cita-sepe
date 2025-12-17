from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_mail import Mail, Message
import threading
import time
import os
import random
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

def background_checker():
    """Funció que s'executa en segon pla per comprovar cites."""
    logger.info("Iniciant fil de comprovació en segon pla...")
    while True:
        try:
            count = len(active_searches)
            if count > 0:
                logger.info(f"Comprovant {count} cerques actives...")
            
            for dni, data in list(active_searches.items()):
                if data['active'] and data['zips']:
                    # ROTACIÓ DE CODIS POSTALS
                    # Seleccionem el següent codi postal de la llista per no saturar
                    current_zip = data['zips'][data['current_zip_index']]
                    
                    # Actualitzem l'índex per la propera vegada (rotació circular)
                    data['current_zip_index'] = (data['current_zip_index'] + 1) % len(data['zips'])
                    
                    logger.info(f"--> Comprovant DNI {dni} a CP {current_zip} (Zona: {data['scope_name']}) [{data['current_zip_index']}/{len(data['zips'])}]")
                    
                    bot = SepeBot()
                    try:
                        found = bot.check_appointment(current_zip, dni, data['type'])
                        if found:
                            logger.info(f"!!! CITA TROBADA per {dni} a {current_zip} !!!")
                            
                            # ATURAR LA CERCA PER AQUEST DNI
                            data['active'] = False
                            logger.info(f"Aturant cerca automàtica per {dni} perquè l'usuari pugui gestionar la cita.")

                            with app.app_context():
                                try:
                                    msg = Message('¡Cita SEPE Disponible!', 
                                                sender=app.config['MAIL_USERNAME'], 
                                                recipients=[data['email']])
                                    msg.body = f"Hola! El bot ha detectat disponibilitat de cita ({data['type']}) per al DNI {dni}.\n\nZona: {data['scope_name']}\nCodi Postal específic: {current_zip}\n\nConnecta't ràpidament al SEPE!"
                                    mail.send(msg)
                                    logger.info(f"Correu enviat a {data['email']}")
                                except Exception as e_mail:
                                    logger.error(f"Error enviant mail: {e_mail}")

                        else:
                            logger.info(f"No s'ha trobat cita per {dni} a {current_zip}.")
                            bot.close() # Només tanquem si NO hem trobat cita
                            
                    except Exception as e:
                        logger.error(f"Error comprovant per {dni}: {e}")
                        bot.close() # Tanquem en cas d'error
                    # finally:
                    #    bot.close() # ELIMINAT: Gestionem el tancament manualment
            
            # Sleep logic
            if count > 0:
                logger.info("Cicle de comprovació finalitzat. Esperant 10 segons...")
                time.sleep(10) # Reduït a 10s per ser més àgil

            else:
                time.sleep(10) # Espera curta si no hi ha feina
                
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
    return render_template('index.html', searches=active_searches, communities=communities, last_dni=last_dni, last_email=last_email)

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
    
    # Save to session for persistence
    session['last_dni'] = dni
    session['last_email'] = email
    
    community = request.form.getlist('community') # Multiple
    scope = request.form.get('scope') # all_community, provincia, municipi, zip, comarca
    
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

        active_searches[dni] = {
            'zips': zips_to_check,
            'current_zip_index': 0,
            'email': email,
            'type': appt_type,
            'active': True,
            'scope_name': scope_name
        }
        flash(f"Cerca iniciada per al DNI {dni}. Zona: {scope_name} ({len(zips_to_check)} codis postals)")
    
    return redirect(url_for('index'))

@app.route('/api/status')
def get_status():
    """Retorna l'estat actual de les cerques actives per actualitzar la UI dinàmicament."""
    status = {}
    for dni, data in active_searches.items():
        current_zip = "N/A"
        if data['zips'] and len(data['zips']) > 0:
            current_zip = data['zips'][data['current_zip_index']]
        
        status[dni] = {
            'current_zip': current_zip,
            'total_zips': len(data['zips']),
            'current_index': data['current_zip_index'] + 1, # 1-based for display
            'active': data['active']
        }
    return jsonify(status)

@app.route('/stop/<dni>')
def stop_search(dni):
    if dni in active_searches:
        del active_searches[dni]
        flash(f"Cerca aturada per al DNI {dni}")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
