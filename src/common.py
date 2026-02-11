import os
import json
import logging
import tempfile

logger = logging.getLogger('state_manager')
STATE_FILE = os.path.join('data', 'state.json')

def load_state():
    """Carrega l'estat de les cerques actives des d'un fitxer JSON."""
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
            # logger.info(f"Estat carregat: {len(data)} registres.")
            return data
        except Exception as e:
            logger.error(f"Error carregant l'estat: {e}")
            return {}
    return {}

def save_state(current_state):
    """Guarda l'estat de les cerques actives a un fitxer JSON de manera atòmica."""
    try:
        # Assegurar que el directori data existeix
        os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
        
        # Write to a temporary file first to prevent corruption on crash
        fd, tmp_path = tempfile.mkstemp(dir=os.path.dirname(STATE_FILE), text=True)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(current_state, f, ensure_ascii=False, indent=4)
        # Atomic replacement
        os.replace(tmp_path, STATE_FILE)
    except Exception as e:
        logger.error(f"Error guardant l'estat: {e}")
        if 'tmp_path' in locals() and os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except:
                pass
