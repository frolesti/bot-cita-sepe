from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import Select
import time
import logging

# Configurem el logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Deixem que l'aplicació principal configuri el logging

# Cache the driver path globally to avoid race conditions in threads
DRIVER_PATH = None

class SepeBot:
    def __init__(self, headless=True):
        global DRIVER_PATH
        if DRIVER_PATH is None:
            try:
                DRIVER_PATH = ChromeDriverManager().install()
            except Exception as e:
                logging.error(f"Error installing ChromeDriver: {e}")
                raise e

        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled') # Per evitar detecció bàsica
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")

        self.driver = webdriver.Chrome(service=Service(DRIVER_PATH), options=options)
        self.driver.set_page_load_timeout(45) # Timeout de 45 segons per carregar pàgines
        self.wait = WebDriverWait(self.driver, 20)

    def check_appointment(self, zip_code, dni, appt_type, tramite_id=None, subtramite_id=None):
        """
        Retorna True si troba disponibilitat, False si no.
        appt_type: 'person' (Presencial) o 'phone' (Telefònica)
        """
        try:
            logging.info(f"Iniciant comprovació per DNI: {dni}, CP: {zip_code}")
            
            # 1. Accedir a la pàgina d'inici de la cita prèvia
            url = "https://sede.sepe.gob.es/portalSede/procedimientos-y-servicios/personas/proteccion-por-desempleo/cita-previa/cita-previa-solicitud.html"
            self.driver.get(url)
            
            # 1b. Gestionar cookies si apareixen
            try:
                cookie_btn = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Aceptar todas') or contains(text(), 'Aceptar')]")))
                cookie_btn.click()
                logging.debug("Cookies acceptades.")
                time.sleep(1)
            except:
                pass

            # 2. Detectar iframe (El formulari sol estar dins un iframe)
            try:
                iframe = WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'citaprevia')]")))
                logging.debug("Iframe del formulari detectat. Canviant de context...")
                self.driver.switch_to.frame(iframe)
            except:
                logging.debug("No s'ha detectat iframe específic, buscant al context principal.")

            # 3. Introduir Dades (CP i DNI)
            logging.debug("Buscant camps del formulari...")
            
            cp_element = None
            
            # 3. Emplenar CP
            logging.debug("Emplenant CP...")
            try:
                # Try robust Select2 interaction first
                try:
                    # Wait for the specific Select2 container for CP
                    # We assume ID is datosCodigoPostal as per scraping analysis
                    select2_container = WebDriverWait(self.driver, 10).until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-selection[aria-labelledby='select2-datosCodigoPostal-container']")))
                    select2_container.click()
                    
                    search_box = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.CLASS_NAME, "select2-search__field")))
                    search_box.send_keys(zip_code)
                    time.sleep(1)
                    search_box.send_keys(Keys.ENTER)
                    logging.debug("CP introduït via Select2 natiu.")
                except Exception as e:
                    logging.debug(f"Error Select2 natiu: {e}. Provant fallback JS...")
                    # Fallback JS
                    self.driver.execute_script("""
                        var newOption = new Option(arguments[1], arguments[1], true, true);
                        $('#datosCodigoPostal').append(newOption).trigger('change');
                        if(typeof seleccionDeCodigoPostal === 'function') { seleccionDeCodigoPostal(); }
                    """, self.driver.find_element(By.ID, "datosCodigoPostal"), zip_code)
                    logging.debug("CP introduït via JS.")
            except Exception as e:
                logging.error(f"Error general emplenant CP: {e}")
                raise e

            # 4. Seleccionar Tràmit (MOVED BEFORE DNI)
            try:
                # Wait for comboNivelServicio2 (Trámite)
                # Note: comboNivelServicio1 is usually "PRESTACIONES" and auto-selected.
                
                # Wait for the element to be present and visible
                tramite_select_elem = WebDriverWait(self.driver, 10).until(EC.visibility_of_element_located((By.ID, "comboNivelServicio2")))
                tramite_select = Select(tramite_select_elem)
                
                if tramite_id:
                    tramite_select.select_by_value(tramite_id)
                    logging.debug(f"Tràmit {tramite_id} seleccionat.")
                else:
                    # Default to first valid option (index 1 usually, 0 is placeholder)
                    if len(tramite_select.options) > 1:
                        tramite_select.select_by_index(1)
                        logging.debug("Tràmit per defecte seleccionat.")
                    else:
                        logging.warning("No hi ha opcions de tràmit disponibles.")

                # 5. Seleccionar Subtràmit (if applicable)
                if subtramite_id:
                    time.sleep(1) # Wait for load
                    subtramite_select_elem = WebDriverWait(self.driver, 5).until(EC.visibility_of_element_located((By.ID, "comboNivelServicio3")))
                    subtramite_select = Select(subtramite_select_elem)
                    subtramite_select.select_by_value(subtramite_id)
                    logging.debug(f"Subtràmit {subtramite_id} seleccionat.")
                
            except Exception as e:
                logging.warning(f"No s'ha pogut seleccionar el tràmit automàticament: {e}")
                # Fallback to old method if specific IDs fail
                try:
                    selects = self.driver.find_elements(By.TAG_NAME, "select")
                    for s in selects:
                        if s.get_attribute("id") not in ["datosCodigoPostal", "datosIdiomas", "comboNivelServicio1"] and s.is_displayed():
                            Select(s).select_by_index(1)
                            logging.debug("Tràmit seleccionat per fallback.")
                            break
                except:
                    pass

            # Introduir DNI (MOVED AFTER TRAMITE)
            # El camp DNI (inputDNI) està ocult inicialment i apareix després de posar el CP i Tràmit
            logging.debug("Esperant que aparegui el camp DNI...")
            try:
                dni_element = WebDriverWait(self.driver, 10).until(EC.visibility_of_element_located((By.ID, "inputDNI")))
                dni_element.clear()
                dni_element.send_keys(dni)
                logging.debug("DNI introduït.")
            except Exception as e:
                logging.error(f"No s'ha pogut trobar o interactuar amb el camp DNI: {e}")
                # Debug HTML
                with open("debug_iframe_dni_fail.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                raise e

            # 5. GESTIÓ DEL CAPTCHA I CONTINUACIÓ
            # Aquest és el punt crític. El SEPE té un captcha visual.
            # Per a una automatització real 100%, caldria un servei de resolució de captchas (com 2captcha).
            # Com que no en tenim, aquí fem una pausa si estem en mode visual, o fallem si és headless.
            
            # Comprovem si hi ha captcha VISIBLE
            all_captcha_elements = self.driver.find_elements(By.ID, "captcha") + self.driver.find_elements(By.XPATH, "//img[contains(@src, 'captcha')]")
            visible_captcha_elements = [el for el in all_captcha_elements if el.is_displayed()]
            
            if len(visible_captcha_elements) > 0:
                logging.info("⚠️  ATENCIÓ: Resol el CAPTCHA manualment al navegador o configura un servei OCR.")
                # Si estem executant en local amb interfície gràfica:
                # Esperem fins que l'usuari canviï de pàgina (signe que ha passat el captcha)
                current_url = self.driver.current_url
                logging.info("Esperant resolució manual del CAPTCHA (màxim 120s)...")
                
                try:
                    # Esperem 120 segons màxim perquè l'usuari resolgui el captcha i cliqui "Aceptar"
                    # Detectem canvi d'URL O aparició de missatges de resultat
                    WebDriverWait(self.driver, 120).until(
                        lambda d: d.current_url != current_url or \
                                  "no hay citas" in d.page_source.lower() or \
                                  "no existe disponibilidad" in d.page_source.lower() or \
                                  "presencial" in d.page_source.lower() or \
                                  "telefónica" in d.page_source.lower() or \
                                  "telefonica" in d.page_source.lower()
                    )
                    logging.info("S'ha detectat avançament després del CAPTCHA.")
                except Exception as e:
                    logging.warning("Temps d'espera esgotat (120s) sense detectar canvis després del CAPTCHA.")
                    return False
            else:
                logging.debug("No s'ha detectat CAPTCHA visible. Intentant continuar automàticament...")
                try:
                    # Intentem clicar el botó de continuar
                    submit_btn = None
                    
                    # Llista de selectors possibles per al botó
                    selectors = [
                        (By.ID, "btnAceptar"),
                        (By.ID, "btnContinuar"),
                        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continuar')]"),
                        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'aceptar')]"),
                        (By.XPATH, "//input[@type='submit']"),
                        (By.XPATH, "//input[@type='button' and contains(@value, 'Continuar')]"),
                        (By.CSS_SELECTOR, "button.btn-primary"),
                        (By.CSS_SELECTOR, ".boton_azul") # Classe comuna en webs antigues
                    ]
                    
                    for by, value in selectors:
                        try:
                            elements = self.driver.find_elements(by, value)
                            for el in elements:
                                if el.is_displayed():
                                    submit_btn = el
                                    logging.debug(f"Botó trobat amb selector: {value}")
                                    break
                            if submit_btn: break
                        except:
                            continue

                    if submit_btn:
                        # Scroll to element to ensure it's clickable
                        self.driver.execute_script("arguments[0].scrollIntoView(true);", submit_btn)
                        time.sleep(0.5)
                        try:
                            submit_btn.click()
                        except:
                            # Fallback JS click
                            self.driver.execute_script("arguments[0].click();", submit_btn)
                            
                        logging.debug("Botó 'Continuar' clicat.")
                        # Esperem una mica perquè carregui la següent pàgina
                        time.sleep(3)
                    else:
                        logging.warning("No s'ha trobat el botó de continuar, però tampoc hi ha captcha.")
                        # Debug HTML per veure per què no troba el botó
                        with open("debug_no_button.html", "w", encoding="utf-8") as f:
                            f.write(self.driver.page_source)
                except Exception as e:
                    logging.error(f"Error intentant clicar continuar: {e}")

            # 6. Comprovar disponibilitat
            
            # 6. Comprovar disponibilitat
            # Un cop passat el captcha, mirem si hi ha missatge d'error o si ens deixa triar cita.
            
            logging.debug("Analitzant resultat de la cerca...")
            time.sleep(2) # Esperem càrrega
            
            # 6b. GESTIÓ DE LA PANTALLA "SELECCIONE EL CANAL"
            # A vegades apareix una pantalla intermèdia on has de triar "Presencial" o "Telefónica"
            try:
                # Busquem si hi ha un selector de canal
                # Sol ser un select amb id o name relacionat amb 'canal' o l'únic select visible
                channel_selects = self.driver.find_elements(By.TAG_NAME, "select")
                channel_select = None
                
                # Filtrem per trobar el bo (sovint té 'canal' al name o id, o és l'únic)
                for s in channel_selects:
                    if s.is_displayed() and ('canal' in s.get_attribute('name').lower() or 'canal' in s.get_attribute('id').lower()):
                        channel_select = s
                        break
                
                # Si no trobem per nom, mirem si hi ha un select visible i estem a la pantalla correcta
                if not channel_select and "seleccione el canal" in self.driver.page_source.lower():
                    for s in channel_selects:
                        if s.is_displayed():
                            channel_select = s
                            break

                if channel_select:
                    logging.debug("Detectada pantalla de selecció de CANAL.")
                    select_obj = Select(channel_select)
                    
                    # Mirem quines opcions hi ha
                    options_text = [o.text.lower() for o in select_obj.options]
                    logging.debug(f"Opcions de canal disponibles: {options_text}")
                    
                    target_text = "presencial" if appt_type == 'person' else "telefónica"
                    if appt_type == 'phone': target_text = "telefonica" # Normalize
                    
                    found_option = False
                    for index, text in enumerate(options_text):
                        if target_text in text:
                            select_obj.select_by_index(index)
                            logging.debug(f"Canal '{text}' seleccionat.")
                            found_option = True
                            break
                    
                    if not found_option:
                        # Si no trobem l'específic, potser només n'hi ha un de disponible?
                        if len(select_obj.options) > 1:
                            select_obj.select_by_index(1) # Seleccionem el primer que no sigui el placeholder
                            logging.debug("Canal per defecte seleccionat (no s'ha trobat l'específic).")
                    
                    # Esperem que la pàgina reaccioni a la selecció (AJAX)
                    time.sleep(3)
            except Exception as e:
                logging.warning(f"Error gestionant selecció de canal (potser no calia): {e}")

            # Re-llegim el source després de la possible interacció
            page_source = self.driver.page_source.lower()
            
            # Llista de frases que indiquen NO disponibilitat
            negative_phrases = [
                "no hay citas",
                "no existe disponibilidad",
                "no podemos ofrecerle cita",
                "no podemos ofrecerle citas", # Plural
                "el horario de atención",
                "inténtelo de nuevo",
                "no se han encontrado citas"
            ]
            
            for phrase in negative_phrases:
                if phrase in page_source:
                    logging.debug(f"Resultat NEGATIU detectat per frase: '{phrase}'")
                    return False
            
            # Si no trobem frases negatives, busquem indicadors positius FORTS
            # Això evita falsos positius amb text genèric del footer/header
            positive_indicators = [
                "seleccione la oficina",
                "seleccione el día",
                "seleccione una oficina",
                "listado de oficinas",
                "citas disponibles",
                "su cita ha sido reservada", # Molt optimista
                "datos de la cita"
            ]
            
            found_positive = False
            for indicator in positive_indicators:
                if indicator in page_source:
                    logging.info(f"Resultat POSITIU detectat per indicador: '{indicator}'")
                    found_positive = True
                    break
            
            if found_positive:
                # Guardem HTML per si de cas
                with open("debug_success_found.html", "w", encoding="utf-8") as f:
                    f.write(self.driver.page_source)
                return True
            
            # Si no trobem ni positiu ni negatiu clar, som conservadors
            # Però si hem passat el formulari i no hi ha error, potser és que sí.
            # Mirem si hi ha elements de formulari nous
            if len(self.driver.find_elements(By.NAME, "idOficina")) > 0 or \
               len(self.driver.find_elements(By.CLASS_NAME, "tablaOferta")) > 0:
                 logging.info("Resultat POSITIU detectat per elements HTML.")
                 return True

            logging.warning("Resultat incert. No s'ha trobat ni error ni confirmació clara.")
            # Guardem HTML per depurar
            with open("debug_uncertain_result.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
            
            return False # Per defecte, si no estem segurs, millor no alertar falsament

        except Exception as e:
            logging.error(f"Error durant la comprovació: {e}")
            return False

    def close(self):
        try:
            self.driver.quit()
        except:
            pass
