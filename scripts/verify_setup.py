import sys
import os
import time
import logging

# Ensure src is in path
sys.path.append(os.path.join(os.path.dirname(__file__), '..'))

from src.sepe_bot import SepeBot

# Configurar logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def verify_setup():
    print("\n" + "="*60)
    print(" VERIFICACIÓ VISUAL DEL BOT SEPE")
    print("="*60)
    print("Aquest script executarà el bot en mode VISUAL (amb navegador).")
    print("Podràs veure com navega, omple les dades i arriba al resultat.")
    print("Si el resultat és 'No hi ha cites', ho veuràs a la pantalla.")
    print("="*60 + "\n")

    cp = input("Introdueix un Codi Postal per provar (ex: 08001): ") or "08001"
    dni = input("Introdueix un DNI fictici o real per provar (ex: 12345678X): ") or "12345678X"
    
    print(f"\nIniciant navegació per CP: {cp}, DNI: {dni} ...")
    print("NO TOCS EL RATOLLI NI EL TECLAT mentre el bot treballa.")
    
    # Force headless=False for visual verification
    bot = SepeBot(headless=False)
    
    try:
        # We assume specific values for a test run
        result = bot.check_appointment(
            zip_code=cp,
            dni=dni,
            appt_type='person' # Default to person
        )
        
        print("\n" + "-"*60)
        if result:
            print("✅ El bot ha detectat CITES DISPONIBLES!")
        else:
            print("❌ El bot ha detectat que NO hi ha cites (o error).")
        print("-"*60)
        
    except Exception as e:
        print(f"\n⚠️ ERROR durant l'execució: {e}")
        
    print("\nEl navegador es tancarà en 30 segons perquè puguis revisar la pantalla final...")
    print("Pots tancar aquesta finestra si ja has vist el resultat.")
    time.sleep(30)
    bot.close()

if __name__ == "__main__":
    verify_setup()
