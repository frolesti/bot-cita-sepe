"""
Servei de gestió de cerques.
Conté tota la lògica de negoci: crear, aturar, reiniciar, eliminar cerques
i consultar el seu estat. És independent de Flask (no coneix request/session).
"""
import os
import time
import random
import logging
from datetime import datetime, timedelta

from src.state import load_state, save_state
from src.locations import LocationManager

# Límit màxim de recurrència (en hores). Si una cerca recurrent porta
# més d'aquest temps activa, s'atura automàticament perquè l'usuari
# no se n'oblidi.
MAX_RECURRENCE_HOURS = int(os.getenv('MAX_RECURRENCE_HOURS', 24))
MAX_RECURRENCE_HOURS_DAILY = int(os.getenv('MAX_RECURRENCE_HOURS_DAILY', 168))  # 1 setmana

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Creació de cerques
# ---------------------------------------------------------------------------

def resolve_zips(scope, value, extra_context=None):
    """Resol una selecció d'àmbit a una llista de codis postals.

    Returns:
        tuple: (zips_list, scope_name, error_message)
    """
    extra_context = extra_context or {}
    scope_name = "Desconegut"

    if scope == 'zip':
        if isinstance(value, str):
            value = [v.strip() for v in value.split(',') if v.strip()]
        scope_name = f"CPs: {', '.join(value)}"
    elif scope == 'municipi':
        scope_name = f"Municipis: {', '.join(value)}"
    elif scope == 'provincia':
        scope_name = f"Províncies: {', '.join(value)}"
    elif scope == 'comarca':
        scope_name = f"Comarques: {', '.join(value)}"
    elif scope in ('all_community', 'community'):
        scope = 'community'
        if not value or (len(value) == 1 and value[0] == ''):
            return [], None, "Has de seleccionar una Comunitat Autònoma."
        scope_name = f"Comunitats: {', '.join(value)}"

    zips = LocationManager.get_zips(scope, value, extra_context)
    if not zips:
        return [], scope_name, "No s'han trobat codis postals per a aquesta selecció."

    random.shuffle(zips)
    return zips, scope_name, None


def create_search(dni, email, appt_types, scope, value, extra_context,
                  tramite_id, freq_type, interval_hours, daily_time,
                  owner_id, max_concurrent=10):
    """Crea una nova cerca per un DNI.

    Returns:
        dict: {'ok': bool, 'message': str, 'zips_count': int}
    """
    all_searches = load_state()

    # Límit global
    total_active = sum(1 for d in all_searches.values() if d.get('active', False))
    if total_active >= max_concurrent:
        return {'ok': False, 'message': f"El servidor ha arribat al límit de {max_concurrent} cerques simultànies."}

    # DNI ja actiu?
    if dni in all_searches and all_searches[dni].get('active', False):
        if all_searches[dni].get('owner_id') == owner_id:
            return {'ok': False, 'message': f"Ja existeix una cerca activa per al DNI {dni}. Atura-la primer."}
        else:
            return {'ok': False, 'message': f"Ja existeix una cerca activa per al DNI {dni} (d'un altre dispositiu)."}

    # Netejar cerca anterior inactiva si és nostra
    if dni in all_searches and all_searches[dni].get('owner_id') == owner_id:
        del all_searches[dni]

    # Resoldre codis postals
    zips, scope_name, error = resolve_zips(scope, value, extra_context)
    if error:
        return {'ok': False, 'message': f"Error: {error}"}

    # Calcular freqüència interna
    frequency = -1
    if freq_type == 'interval':
        try:
            frequency = int(interval_hours) * 60
        except (ValueError, TypeError):
            frequency = 60
    elif freq_type == 'daily':
        frequency = -2

    all_searches[dni] = {
        'zips': zips,
        'current_zip_index': 0,
        'email': email,
        'appt_types': appt_types,
        'type': appt_types[0],
        'active': True,
        'scope_name': scope_name,
        'frequency': frequency,
        'freq_type': freq_type,
        'interval_hours': interval_hours,
        'daily_time': daily_time,
        'last_cycle_time': 0,
        'status_message': "Iniciant...",
        'last_result_message': "Pendent de primera execució",
        'tramite_id': tramite_id,
        'run_id': time.time(),
        'owner_id': owner_id,
        'created_at': time.time(),
    }
    save_state(all_searches)

    types_str = ' i '.join(['Presencial' if t == 'person' else 'Telefònica' for t in appt_types])
    return {
        'ok': True,
        'message': f"Cerca iniciada: {dni} | {scope_name} ({len(zips)} CPs) | {types_str}",
        'zips_count': len(zips),
        'scope_name': scope_name,
        'types_str': types_str,
    }


# ---------------------------------------------------------------------------
# Accions sobre cerques existents
# ---------------------------------------------------------------------------

def stop_search(dni, owner_id):
    """Atura una cerca. Retorna (ok, message)."""
    all_searches = load_state()
    search = all_searches.get(dni)
    if not search or search.get('owner_id') != owner_id:
        return False, "DNI no trobat"
    search['active'] = False
    search['status_message'] = "Aturat manualment"
    search['finished_at'] = datetime.now().strftime('%d/%m/%Y %H:%M')
    save_state(all_searches)
    return True, "Cerca aturada"


def restart_search(dni, owner_id):
    """Reinicia una cerca. Retorna (ok, message)."""
    all_searches = load_state()
    search = all_searches.get(dni)
    if not search or search.get('owner_id') != owner_id:
        return False, "DNI no trobat"
    search['active'] = True
    search['current_zip_index'] = 0
    search['cycle_start_time'] = None
    search['finished_at'] = None
    search['status_message'] = 'Reiniciant...'
    search['last_cycle_time'] = 0
    search['run_id'] = time.time()
    search['created_at'] = time.time()  # Reset rellotge de recurrència
    search['last_success'] = None
    save_state(all_searches)
    return True, "Cerca reiniciada"


def delete_search(dni, owner_id):
    """Elimina una cerca. Retorna (ok, message)."""
    all_searches = load_state()
    search = all_searches.get(dni)
    if not search or search.get('owner_id') != owner_id:
        return False, "DNI no trobat"
    del all_searches[dni]
    save_state(all_searches)
    return True, "Cerca eliminada"


# ---------------------------------------------------------------------------
# Consulta d'estat
# ---------------------------------------------------------------------------

def get_searches_for_owner(owner_id):
    """Retorna les cerques que pertanyen a un owner_id, amb migració automàtica."""
    all_searches = load_state()

    # Migració: cerques sense owner_id → adoptar
    adopted = False
    for data in all_searches.values():
        if 'owner_id' not in data:
            data['owner_id'] = owner_id
            adopted = True
    if adopted:
        save_state(all_searches)

    return {dni: data for dni, data in all_searches.items()
            if data.get('owner_id') == owner_id}


def get_status_for_owner(owner_id):
    """Retorna un dict d'estat per a la UI, filtrat per owner_id."""
    my_searches = get_searches_for_owner(owner_id)
    status = {}

    for dni, data in my_searches.items():
        zips = data.get('zips', [])
        idx = data.get('current_zip_index', 0)
        curr_zip = zips[idx] if zips and idx < len(zips) else "N/A"

        freq_type = data.get('freq_type', 'once')
        last_complete = data.get('last_cycle_time', 0)
        is_active = data.get('active', False)
        next_run_time = None

        if is_active and idx == 0 and freq_type != 'once':
            next_run_time = _calc_next_run(freq_type, last_complete, data)

        # Calcular si la cerca ha expirat
        created_at = data.get('created_at', 0)
        max_h = MAX_RECURRENCE_HOURS_DAILY if freq_type == 'daily' else MAX_RECURRENCE_HOURS
        is_expired = (not is_active and freq_type != 'once'
                      and created_at > 0
                      and (time.time() - created_at) > max_h * 3600)

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
            'cycle_start_time': data.get('cycle_start_time'),
            'finished_at': data.get('finished_at'),
            'created_at': created_at,
            'is_expired': is_expired,
            'last_success': data.get('last_success'),
            'max_recurrence_hours': max_h,
        }
    return status


def get_server_info():
    """Retorna informació global del servidor (sense dades privades)."""
    all_searches = load_state()
    active = [d for d in all_searches.values() if d.get('active', False)]
    total_active = len(active)

    # Cerques que estan realment executant-se (no en pausa)
    running = sum(1 for d in active
                  if 'En pausa' not in (d.get('status_message') or '')
                  and 'Cicle completat' not in (d.get('status_message') or '')
                  and 'Iniciant' not in (d.get('status_message') or ''))

    # Capacitat
    max_concurrent = int(os.getenv('MAX_CONCURRENT_SEARCHES', 10))
    load_pct = round((total_active / max_concurrent) * 100) if max_concurrent else 0

    # Nivell de càrrega
    if load_pct >= 90:
        level = 'critical'
    elif load_pct >= 70:
        level = 'high'
    elif load_pct >= 40:
        level = 'moderate'
    else:
        level = 'low'

    return {
        'active_searches': total_active,
        'running_now': running,
        'paused': total_active - running,
        'total_searches': len(all_searches),
        'max_concurrent': max_concurrent,
        'load_pct': min(load_pct, 100),
        'level': level,
    }


# ---------------------------------------------------------------------------
# Helpers interns
# ---------------------------------------------------------------------------

def _calc_next_run(freq_type, last_complete, data):
    """Calcula la pròxima execució per a la UI."""
    now = datetime.now()  # TZ=Europe/Madrid via Dockerfile ENV

    next_dt = None

    if freq_type == 'interval' and last_complete > 0:
        interval_hours = float(data.get('interval_hours', 1))
        next_ts = last_complete + (interval_hours * 3600)
        next_dt = datetime.fromtimestamp(next_ts)
    elif freq_type == 'daily':
        daily_time_str = data.get('daily_time', '09:00')
        try:
            target_time = datetime.strptime(daily_time_str, '%H:%M').time()
            today_target = datetime.combine(now.date(), target_time)
            next_dt = today_target + timedelta(days=1) if now > today_target else today_target
        except Exception:
            pass

    if next_dt:
        time_str = next_dt.strftime('%H:%M')
        if next_dt.date() == now.date():
            return f"Avui {time_str}"
        elif next_dt.date() == (now + timedelta(days=1)).date():
            return f"Demà {time_str}"
        else:
            return next_dt.strftime('%d/%m %H:%M')
    return None
