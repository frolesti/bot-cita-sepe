import threading
import sys
import os

from src.app import app


def start_worker():
    """Arranca el worker en un fil separat."""
    # Afegir directori arrel al path (el worker ho necessita)
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    from src.worker import run_worker
    run_worker()


if __name__ == "__main__":
    # Engegar el worker automàticament en un fil daemon
    worker_thread = threading.Thread(target=start_worker, daemon=True, name="sepe-worker")
    worker_thread.start()
    print("[run.py] Worker engegat en segon pla.")

    app.run(debug=True, use_reloader=False)
