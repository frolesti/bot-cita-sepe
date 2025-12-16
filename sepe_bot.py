from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import time

class SepeBot:
    def __init__(self):
        options = webdriver.ChromeOptions()
        # options.add_argument('--headless') # Descomenta per executar sense finestra
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        
        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.wait = WebDriverWait(self.driver, 10)

    def check_appointment(self, zip_code, dni, appt_type):
        """
        Retorna True si troba disponibilitat, False si no.
        """
        try:
            # URL d'exemple (aquesta URL canvia sovint, s'ha de verificar la del SEPE actual)
            # Aquesta és la URL general de cita prèvia
            self.driver.get("https://sede.sepe.gob.es/portalSede/procedimientos-y-servicios/personas/proteccion-por-desempleo/cita-previa")
            
            # NOTA: La navegació pel SEPE és complexa i té molts passos i iframes.
            # Aquest és un esquema de com seria la lògica:
            
            # 1. Clicar a "Iniciar sol·licitud"
            # start_btn = self.wait.until(EC.element_to_be_clickable((By.ID, "btn-iniciar")))
            # start_btn.click()

            # 2. Introduir CP i DNI
            # self.wait.until(EC.presence_of_element_located((By.ID, "txt-cp"))).send_keys(zip_code)
            # self.driver.find_element(By.ID, "txt-dni").send_keys(dni)

            # 3. Seleccionar tipus de tràmit (això depèn de si és presencial o telefònic)
            # ... lògica de selecció ...

            # 4. Comprovar si hi ha missatge de "No hi ha cites"
            # if "no hay citas" in self.driver.page_source.lower():
            #     return False
            
            # Si arribem aquí sense errors i sense missatge de "no cites", és que n'hi ha.
            print(f"Simulació: Comprovant SEPE per {dni} a {zip_code} ({appt_type})...")
            time.sleep(2) # Simulem temps de càrrega
            
            # Retornem False per defecte en aquesta plantilla
            return False 

        except Exception as e:
            print(f"Error en el bot: {e}")
            return False

    def close(self):
        self.driver.quit()
