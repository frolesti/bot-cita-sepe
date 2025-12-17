from sepe_bot import SepeBot
import time
import logging

# Configure logging for standalone test
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def test_monitoring():
    print("Iniciant prova de monitoratge...")
    
    # Dades de prova
    TEST_ZIP = "08001"
    TEST_DNI = "12345678X" # DNI fictici
    TEST_TYPE = "person" # 'person' o 'phone'
    TEST_TRAMITE = "158" # He finalizado un trabajo...
    
    print(f"Provant amb: CP={TEST_ZIP}, DNI={TEST_DNI}, Tipus={TEST_TYPE}, Tràmit={TEST_TRAMITE}")
    
    bot = SepeBot()
    try:
        found = bot.check_appointment(TEST_ZIP, TEST_DNI, TEST_TYPE, tramite_id=TEST_TRAMITE)
        if found:
            print("RESULTAT: S'ha trobat disponibilitat (o s'ha arribat al final del procés sense error de 'no hi ha cites').")
        else:
            print("RESULTAT: No hi ha cites disponibles o hi ha hagut un error controlat.")
            
    except Exception as e:
        print(f"ERROR DURANT LA PROVA: {e}")
    finally:
        print("Tancant navegador en 5 segons...")
        time.sleep(5)
        bot.close()
        print("Prova finalitzada.")

if __name__ == "__main__":
    test_monitoring()
