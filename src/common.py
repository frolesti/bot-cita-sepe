import os
import json
import logging
import tempfile
import threading

logger = logging.getLogger('state_manager')
STATE_FILE = os.path.join('data', 'state.json')

# Lock per evitar race conditions entre Flask i el worker
_state_lock = threading.Lock()

def load_state():
    """Carrega l'estat de les cerques actives des d'un fitxer JSON."""
    with _state_lock:
        if os.path.exists(STATE_FILE):
            try:
                with open(STATE_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                return data
            except Exception as e:
                logger.error(f"Error carregant l'estat: {e}")
                return {}
        return {}

def save_state(current_state):
    """Guarda l'estat de les cerques actives a un fitxer JSON de manera atòmica."""
    with _state_lock:
        try:
            os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
            fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(STATE_FILE), text=True)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(current_state, f, ensure_ascii=False, indent=4)
            os.replace(tmp_path, STATE_FILE)
        except Exception as e:
            logger.error(f"Error guardant l'estat: {e}")
            if 'tmp_path' in locals() and os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except:
                    pass
