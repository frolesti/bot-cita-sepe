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
import os
import re
import threading

# Configurem el logging
# logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
# Deixem que l'aplicació principal configuri el logging

# Cache the driver path globally to avoid race conditions in threads
DRIVER_PATH = None
_driver_lock = threading.Lock()

class SepeBot:
    def __init__(self, headless=True):
        global DRIVER_PATH
        
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--no-sandbox')
        options.add_argument('--disable-dev-shm-usage')
        options.add_argument('--disable-blink-features=AutomationControlled') # Per evitar detecció bàsica
        options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")

        # Check for system installed chromedriver (Docker/Linux ARM)
        system_chromedriver = os.environ.get('CHROMEDRIVER_PATH')
        system_chrome_bin = os.environ.get('CHROME_BIN')

        if system_chrome_bin:
            options.binary_location = system_chrome_bin

        if system_chromedriver and os.path.exists(system_chromedriver):
            logging.info(f"Using system chromedriver at: {system_chromedriver}")
            self.service = Service(system_chromedriver)
        else:
            # Fallback to ChromeDriverManager (Local Windows/Standard)
            with _driver_lock:
                if DRIVER_PATH is None:
                    try:
                        logging.info("Descarregant ChromeDriver (nomes un cop)...")
                        DRIVER_PATH = ChromeDriverManager().install()
                    except Exception as e:
                        logging.error(f"Error installing ChromeDriver: {e}")
                        raise e
            self.service = Service(DRIVER_PATH)

        self.driver = webdriver.Chrome(service=self.service, options=options)
        self.driver.set_page_load_timeout(45) # Timeout de 45 segons per carregar pàgines
        self.wait = WebDriverWait(self.driver, 20)

    def check_appointment(self, zip_code, dni, appt_types=None, tramite_id=None, subtramite_id=None):
        """
        Comprova la disponibilitat per un o múltiples tipus de cita en una sola sessió.
        appt_types: llista com ['person', 'phone'] o ['person']. Per defecte ['person'].
        Retorna: dict com {'person': True, 'phone': False}
        """
        # Backward compatibility
        if appt_types is None:
            appt_types = ['person']
        if isinstance(appt_types, str):
            appt_types = [appt_types]
        
        results = {t: False for t in appt_types}
        
        try:
            logging.info(f"Iniciant comprovació per DNI: {dni}, CP: {zip_code}, Tipus: {appt_types}")
            
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
            logging.debug("Analitzant resultat de la cerca...")
            time.sleep(2) # Esperem càrrega
            
            # 6b. GESTIÓ DEL CANAL: comprovar cada tipus de cita sol·licitat
            channel_select_elem = self._find_channel_selector()
            
            if channel_select_elem:
                # Hi ha selector de canal — comprovem cada tipus
                for i, appt_type in enumerate(appt_types):
                    if i > 0:
                        # Re-buscar el selector per si la pàgina ha canviat
                        channel_select_elem = self._find_channel_selector()
                        if not channel_select_elem:
                            logging.warning("No s'ha pogut re-trobar el selector de canal per al següent tipus.")
                            break
                    
                    self._select_channel(channel_select_elem, appt_type)
                    time.sleep(3)  # Esperem AJAX
                    
                    found = self._check_page_result(zip_code, dni)
                    results[appt_type] = found
                    
                    if found:
                        type_name = 'Presencial' if appt_type == 'person' else 'Telefònica'
                        logging.info(f"CITA {type_name} TROBADA per {dni} a {zip_code}!")
                        offices = self._extract_offices()
                        if offices:
                            results['offices'] = offices
            else:
                # No hi ha selector de canal — el resultat val per tots els tipus
                found = self._check_page_result(zip_code, dni)
                for t in appt_types:
                    results[t] = found
                if found:
                    offices = self._extract_offices()
                    if offices:
                        results['offices'] = offices
            
            return results

        except Exception as e:
            logging.error(f"Error durant la comprovació: {e}")
            return results

    def _find_channel_selector(self):
        """Busca el selector de canal (presencial/telefònica) a la pàgina."""
        try:
            channel_selects = self.driver.find_elements(By.TAG_NAME, "select")
            
            # Buscar per nom/id amb 'canal'
            for s in channel_selects:
                try:
                    if s.is_displayed() and (
                        'canal' in (s.get_attribute('name') or '').lower() or 
                        'canal' in (s.get_attribute('id') or '').lower()
                    ):
                        return s
                except:
                    continue
            
            # Fallback: si la pàgina conté "seleccione/seleccioneu el canal", agafar el primer select visible
            page_lower = self.driver.page_source.lower()
            if "seleccione el canal" in page_lower or "seleccioneu el canal" in page_lower:
                for s in channel_selects:
                    try:
                        if s.is_displayed():
                            return s
                    except:
                        continue
        except Exception as e:
            logging.debug(f"Error buscant selector de canal: {e}")
        return None

    def _select_channel(self, channel_select_elem, appt_type):
        """Selecciona un canal (presencial/telefònica) al selector."""
        try:
            select_obj = Select(channel_select_elem)
            options_text = [o.text.lower() for o in select_obj.options]
            logging.debug(f"Opcions de canal disponibles: {options_text}")
            
            target_text = "presencial" if appt_type == 'person' else "telef\u00f3nica"
            if appt_type == 'phone':
                target_text = "telefonica"  # Sense accent per matching més flexible
            
            for index, text in enumerate(options_text):
                if target_text in text or (appt_type == 'phone' and 'telef' in text):
                    select_obj.select_by_index(index)
                    type_name = 'Presencial' if appt_type == 'person' else 'Telefònica'
                    logging.debug(f"Canal '{type_name}' seleccionat (opció: '{text}').")
                    return True
            
            # Fallback: primer no-placeholder
            if len(select_obj.options) > 1:
                select_obj.select_by_index(1)
                logging.debug("Canal per defecte seleccionat (no s'ha trobat l'específic).")
            return True
        except Exception as e:
            logging.warning(f"Error seleccionant canal: {e}")
            return False

    def _check_page_result(self, zip_code, dni):
        """Comprova la pàgina actual per determinar si hi ha disponibilitat."""
        time.sleep(2)
        page_source = self.driver.page_source.lower()
        
        # Frases que indiquen NO disponibilitat (castellà i català)
        negative_phrases = [
            "no hay citas",
            "no hi ha cites",
            "no existe disponibilidad",
            "no existeix disponibilitat",
            "no podemos ofrecerle cita",
            "no podem oferir-li cita",
            "no podemos ofrecerle citas",
            "el horario de atenci\u00f3n",
            "l'horari d'atenci\u00f3",
            "int\u00e9ntelo de nuevo",
            "torneu-ho a intentar",
            "no se han encontrado citas",
            "no s'han trobat cites"
        ]
        
        for phrase in negative_phrases:
            if phrase in page_source:
                logging.debug(f"Resultat NEGATIU detectat per frase: '{phrase}'")
                return False
        
        # Indicadors positius forts (castellà i català)
        positive_indicators = [
            # Llistat d'oficines (pas 2 del SEPE)
            "primer hueco disponible",
            "primer buit disponible",
            "oficinas disponibles",
            "oficines disponibles",
            "seleccione el canal",
            "seleccioneu el canal",
            # Selecció d'oficina
            "seleccione la oficina",
            "seleccioneu l'oficina",
            "seleccione una oficina",
            "seleccioneu una oficina",
            "listado de oficinas",
            "llistat d'oficines",
            # Selecció de dia/hora
            "seleccione el d\u00eda",
            "seleccioneu el dia",
            "citas disponibles",
            "cites disponibles",
            # Confirmació
            "su cita ha sido reservada",
            "la seva cita ha estat reservada",
            "datos de la cita",
            "dades de la cita",
        ]
        
        for indicator in positive_indicators:
            if indicator in page_source:
                logging.info(f"Resultat POSITIU detectat per indicador: '{indicator}'")
                self._save_debug_snapshot("success")
                return True
        
        # Comprovar elements HTML de resultat positiu
        positive_elements = [
            (By.NAME, "idOficina"),
            (By.CLASS_NAME, "tablaOferta"),
            # Checkboxes d'oficines al llistat del SEPE
            (By.CSS_SELECTOR, "input[type='checkbox'][name*='oficina']"),
            (By.CSS_SELECTOR, "input[type='checkbox'][name*='Oficina']"),
            (By.CSS_SELECTOR, ".oficina-card"),
            (By.CSS_SELECTOR, "[class*='disponible']"),
            # Mapa d'oficines
            (By.CSS_SELECTOR, ".leaflet-container"),
            (By.CSS_SELECTOR, "[class*='mapa']"),
        ]
        
        for by, selector in positive_elements:
            try:
                elems = self.driver.find_elements(by, selector)
                visible = [e for e in elems if e.is_displayed()]
                if visible:
                    logging.info(f"Resultat POSITIU detectat per element HTML: {selector} ({len(visible)} trobats)")
                    self._save_debug_snapshot("success_elements")
                    return True
            except:
                continue

        logging.warning("Resultat incert. No s'ha trobat ni error ni confirmació clara.")
        self._save_debug_snapshot("uncertain")
        return False

    def _extract_offices(self):
        """Extreu informacio de les oficines disponibles de la pagina de resultats."""
        offices = []
        try:
            page_source = self.driver.page_source
            
            # Patro 1: "Primer hueco/buit disponible: <data>"
            pattern_hueco = re.compile(
                r'(?:primer\s+(?:hueco|buit)\s+disponible[:\s]*)(.+?\d{1,2}:\d{2})',
                re.IGNORECASE
            )
            matches = pattern_hueco.findall(page_source)
            for m in matches:
                offices.append(m.strip())
            
            # Patro 2: Oficines amb nom
            try:
                office_elements = self.driver.find_elements(By.CSS_SELECTOR, 
                    ".oficina-card, .tablaOferta tr, [class*='oficina'], label[for*='oficina']")
                for el in office_elements:
                    text = el.text.strip()
                    if text and len(text) > 5 and text not in offices:
                        offices.append(text[:200])
            except:
                pass
            
            # Patro 3: Si no hem trobat res, agafar text visible rellevant
            if not offices:
                try:
                    body_text = self.driver.find_element(By.TAG_NAME, "body").text
                    for line in body_text.split('\n'):
                        line = line.strip()
                        if line and ('disponible' in line.lower() or 'oficina' in line.lower() or re.search(r'\d{1,2}:\d{2}', line)):
                            if len(line) > 5 and line not in offices:
                                offices.append(line[:200])
                except:
                    pass
            
            if offices:
                logging.info(f"Oficines extretes: {len(offices)} entrades")
            
        except Exception as e:
            logging.debug(f"Error extraient oficines: {e}")
        
        return offices[:20]

    def _save_debug_snapshot(self, prefix):
        """Guarda HTML i captura de pantalla per depuració."""
        timestamp = int(time.time())
        try:
            with open(f"debug_{prefix}_{timestamp}.html", "w", encoding="utf-8") as f:
                f.write(self.driver.page_source)
        except:
            pass
        try:
            os.makedirs("debug_screenshots", exist_ok=True)
            self.driver.save_screenshot(f"debug_screenshots/{prefix}_{timestamp}.png")
        except:
            pass

    def close(self):
        try:
            self.driver.quit()
        except:
            pass
