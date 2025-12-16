from flask import Flask, render_template, request, redirect, url_for, flash
import threading
import time
from sepe_bot import SepeBot

app = Flask(__name__)
app.secret_key = 'supersecretkey'  # Canvia-ho per alguna cosa segura

# Emmagatzematge en memòria (no base de dades)
# Estructura: { 'dni': { 'zip_code': '...', 'email': '...', 'type': '...', 'active': True } }
active_searches = {}

def background_checker():
    """Funció que s'executa en segon pla per comprovar cites."""
    while True:
        print(f"Comprovant {len(active_searches)} cerques actives...")
        # Iterem sobre una còpia per evitar problemes de concurrència
        for dni, data in list(active_searches.items()):
            if data['active']:
                bot = SepeBot()
                try:
                    found = bot.check_appointment(data['zip_code'], data['dni'], data['type'])
                    if found:
                        print(f"Cita trobada per {dni}!")
                        # Aquí enviariem el mail
                        # send_email(data['email'], "Cita disponible!")
                        # data['active'] = False # Aturem la cerca si trobem
                except Exception as e:
                    print(f"Error comprovant per {dni}: {e}")
                finally:
                    bot.close()
        
        time.sleep(300) # Comprovar cada 5 minuts

# Iniciem el fil en segon pla
checker_thread = threading.Thread(target=background_checker, daemon=True)
checker_thread.start()

@app.route('/')
def index():
    return render_template('index.html', searches=active_searches)

@app.route('/start', methods=['POST'])
def start_search():
    dni = request.form.get('dni')
    zip_code = request.form.get('zip_code')
    email = request.form.get('email')
    appt_type = request.form.get('appt_type') # 'phone' o 'person'

    if dni and zip_code and email:
        active_searches[dni] = {
            'zip_code': zip_code,
            'email': email,
            'type': appt_type,
            'active': True
        }
        flash(f"Cerca iniciada per al DNI {dni}")
    
    return redirect(url_for('index'))

@app.route('/stop/<dni>')
def stop_search(dni):
    if dni in active_searches:
        del active_searches[dni]
        flash(f"Cerca aturada per al DNI {dni}")
    return redirect(url_for('index'))

if __name__ == '__main__':
    app.run(debug=True)
