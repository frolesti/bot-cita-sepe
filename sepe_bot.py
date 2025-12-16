from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import Select
import time
import logging

# Configurem el logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class SepeBot:
    def __init__(self):
        options = webdriver.ChromeOptions()
        # options.add_argument('--headless') # El mode headless pot donar problemes amb els captchas del SEPE
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled') # Per evitar detecció bàsica
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")

        self.driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
        self.wait = WebDriverWait(self.driver, 20)

    def check_appointment(self, zip_code, dni, appt_type):
        """
        Retorna True si troba disponibilitat, False si no.
        appt_type: 'person' (Presencial) o 'phone' (Telefònica)
        """
        try:
            logging.info(f"Iniciant comprovació per DNI: {dni}, CP: {zip_code}")
            
            # 1. Accedir a la pàgina d'inici de la cita prèvia
            url = "https://sede.sepe.gob.es/portalSede/procedimientos-y-servicios/personas/proteccion-por-desempleo/cita-previa/cita-previa-solicitud.html"
            self.driver.get(url)
            
            # 2. Clicar "Iniciar solicitud"
            # A vegades està dins d'un iframe o canvia. Busquem per text o ID.
            try:
                start_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Iniciar solicitud') or contains(@href, 'cita_previa')]")))
                start_btn.click()
            except:
                logging.warning("No s'ha trobat el botó d'inici directament, buscant alternatives...")
                # A vegades la URL redirigeix directament al formulari
            
            # 3. Introduir Dades (CP i DNI)
            # Esperem que carregui el formulari
            self.wait.until(EC.presence_of_element_located((By.ID, "codigoPostal"))) # ID probable
            
            # Introduir CP
            cp_input = self.driver.find_element(By.ID, "codigoPostal") # O cerca per name="codigoPostal"
            cp_input.clear()
            cp_input.send_keys(zip_code)
            
            # Introduir DNI
            dni_input = self.driver.find_element(By.XPATH, "//input[contains(@id, 'nif') or contains(@name, 'nif')]")
            dni_input.clear()
            dni_input.send_keys(dni)
            
            # 4. Seleccionar Tràmit
            # Normalment "Solicitud de prestaciones" és l'opció estàndard per l'atur
            try:
                tramite_select = Select(self.driver.find_element(By.XPATH, "//select[contains(@id, 'tramite') or contains(@name, 'tramite')]"))
                # Seleccionem per valor o text. Sovint el valor per prestacions és genèric.
                # Intentem seleccionar la segona opció (la primera sol ser "Seleccione...")
                tramite_select.select_by_index(1) 
            except Exception as e:
                logging.warning(f"No s'ha pogut seleccionar el tràmit automàticament: {e}")

            # 5. GESTIÓ DEL CAPTCHA
            # Aquest és el punt crític. El SEPE té un captcha visual.
            # Per a una automatització real 100%, caldria un servei de resolució de captchas (com 2captcha).
            # Com que no en tenim, aquí fem una pausa si estem en mode visual, o fallem si és headless.
            
            logging.info("⚠️  ATENCIÓ: Resol el CAPTCHA manualment al navegador o configura un servei OCR.")
            
            # Comprovem si hi ha captcha
            if len(self.driver.find_elements(By.ID, "captcha")) > 0 or len(self.driver.find_elements(By.XPATH, "//img[contains(@src, 'captcha')]")) > 0:
                # Si estem executant en local amb interfície gràfica:
                # Esperem fins que l'usuari canviï de pàgina (signe que ha passat el captcha)
                current_url = self.driver.current_url
                # Esperem 60 segons màxim perquè l'usuari resolgui el captcha i cliqui "Aceptar"
                WebDriverWait(self.driver, 60).until(EC.url_changes(current_url))
            
            # 6. Comprovar disponibilitat
            # Un cop passat el captcha, mirem si hi ha missatge d'error o si ens deixa triar cita.
            
            time.sleep(2) # Esperem càrrega
            page_source = self.driver.page_source.lower()
            
            if "no hay citas" in page_source or "no existe disponibilidad" in page_source:
                logging.info("Resultat: No hi ha cites disponibles.")
                return False
            
            # Si arribem a la pantalla de selecció de dia/hora o tipus de cita (Presencial/Telefònica)
            # Aquí és on aplicariem el filtre appt_type
            
            if appt_type == 'phone':
                if "telefónica" in page_source or "telefonica" in page_source:
                    logging.info("Cita telefònica disponible!")
                    return True
            else: # person
                if "presencial" in page_source:
                    logging.info("Cita presencial disponible!")
                    return True
            
            # Si no trobem text específic però no hi ha error, assumim que hi ha disponibilitat general
            # i retornem True perquè l'usuari entri ràpid.
            logging.info("Sembla que hi ha disponibilitat (no s'ha trobat missatge d'error).")
            return True

        except Exception as e:
            logging.error(f"Error durant la comprovació: {e}")
            return False

    def close(self):
        try:
            self.driver.quit()
        except:
            pass
