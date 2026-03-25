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
        self.driver.set_script_timeout(30)
        self.wait = WebDriverWait(self.driver, 20)
        self.headless = headless

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
                # Use JS method directly - Select2 gives stale elements inside iframe
                cp_elem = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((By.ID, "datosCodigoPostal")))
                # SEPE stores all CP data (including lat/lng) in a hidden input
                # #mapaListadosCp as HTML-entity-encoded JSON keyed by 3-digit prefix.
                # getCP() reads data-latitud/data-longitud from the selected <option>.
                # cargaOficinasMapa() needs these coords to find nearby offices.
                # Without coordinates, SEPE returns "no podemos ofrecerle citas".
                self.driver.execute_script("""
                    var sel = arguments[0];
                    var cp = arguments[1];
                    var prefix = cp.substring(0, 3);
                    var lat = 0, lng = 0;
                    
                    // Read coords from #mapaListadosCp hidden field (the real source)
                    try {
                        var mapaCp = document.getElementById('mapaListadosCp');
                        if (mapaCp && mapaCp.value) {
                            var allData = JSON.parse(mapaCp.value);
                            var cpList = allData[prefix];
                            if (cpList) {
                                for (var i = 0; i < cpList.length; i++) {
                                    if (cpList[i].codigo === cp) {
                                        lat = cpList[i].latitud;
                                        lng = cpList[i].longitud;
                                        break;
                                    }
                                }
                            }
                        }
                    } catch(e) { console.error('Error parsing mapaListadosCp:', e); }
                    
                    // Create option with data attributes (for getCP())
                    var newOption = new Option(cp, cp, true, true);
                    newOption.setAttribute('data-latitud', lat);
                    newOption.setAttribute('data-longitud', lng);
                    sel.appendChild(newOption);
                    sel.value = cp;
                    
                    // Set hidden lat/lng fields directly (for AJAX params)
                    $('#latitudCP').val(lat);
                    $('#longitudCP').val(lng);
                    
                    // Trigger change events for Select2 and any listeners
                    $(sel).val(cp).trigger('change');
                    if(typeof seleccionDeCodigoPostal === 'function') { seleccionDeCodigoPostal(); }
                """, cp_elem, zip_code)
                
                # Verify lat/lng were set
                lat_val = self.driver.execute_script("return $('#latitudCP').val()")
                lng_val = self.driver.execute_script("return $('#longitudCP').val()")
                logging.debug(f"CP {zip_code} introduït via JS. Coords: lat={lat_val}, lng={lng_val}")
                
                if not lat_val or lat_val == '0' or lat_val == '':
                    logging.warning(f"⚠️ latitudCP buit després d'injectar coords!")
                
                time.sleep(2)  # Wait for AJAX to load tramites
            except Exception as e:
                logging.error(f"Error general emplenant CP: {e}")
                raise e

            # 3b. Seleccionar "Tipus d'oficina de gestió" (comboNivelServicio1 = PRESTACIONES)
            logging.debug("Seleccionant Tipus d'oficina de gestió (Nivell 1)...")
            try:
                nivel1_elem = WebDriverWait(self.driver, 8).until(
                    EC.visibility_of_element_located((By.ID, "comboNivelServicio1"))
                )
                nivel1_select = Select(nivel1_elem)
                # Select PRESTACIONES (first non-placeholder option, value 146)
                if len(nivel1_select.options) > 1:
                    nivel1_select.select_by_index(1)
                    logging.info(f"Nivell 1 seleccionat: {nivel1_select.first_selected_option.text}")
                time.sleep(2)  # Wait for level 2 options to load via AJAX
            except Exception as e:
                logging.debug(f"comboNivelServicio1 no trobat o ja seleccionat: {e}")

            # 4. Seleccionar Tràmit (comboNivelServicio2) — amb retry per StaleElement
            tramite_ok = False
            for _attempt in range(3):
                try:
                    tramite_select_elem = WebDriverWait(self.driver, 10).until(
                        EC.visibility_of_element_located((By.ID, "comboNivelServicio2")))
                    time.sleep(0.5)  # Let AJAX finish populating options
                    tramite_select = Select(tramite_select_elem)
                    
                    if tramite_id:
                        tramite_select.select_by_value(tramite_id)
                        logging.info(f"Tràmit {tramite_id} seleccionat.")
                    else:
                        if len(tramite_select.options) > 1:
                            tramite_select.select_by_index(1)
                            logging.info(f"Tràmit seleccionat: {tramite_select.first_selected_option.text}")
                        else:
                            logging.warning("No hi ha opcions de tràmit disponibles.")
                    tramite_ok = True
                    break
                except Exception as e:
                    if _attempt < 2:
                        logging.info(f"Retry {_attempt+1}/3 selecció tràmit (StaleElement?)")
                        time.sleep(2)
                    else:
                        logging.warning(f"No s'ha pogut seleccionar el tràmit (3 intents): {e}")

            if not tramite_ok:
                # Fallback to old method if specific IDs fail
                try:
                    selects = self.driver.find_elements(By.TAG_NAME, "select")
                    for s in selects:
                        if s.get_attribute("id") not in ["datosCodigoPostal", "datosIdiomas", "comboNivelServicio1"] and s.is_displayed():
                            Select(s).select_by_index(1)
                            logging.info("Tràmit seleccionat per fallback.")
                            tramite_ok = True
                            break
                except:
                    pass

            if not tramite_ok:
                logging.error("No s'ha pogut seleccionar cap tràmit. Abortant comprovació.")
                return results

            # 5. Seleccionar Subtràmit (comboNivelServicio3) si existeix
            time.sleep(1)
            try:
                subtramite_select_elem = WebDriverWait(self.driver, 5).until(
                    EC.visibility_of_element_located((By.ID, "comboNivelServicio3"))
                )
                subtramite_select = Select(subtramite_select_elem)
                if subtramite_id:
                    subtramite_select.select_by_value(subtramite_id)
                    logging.info(f"Subtràmit {subtramite_id} seleccionat.")
                elif len(subtramite_select.options) > 1:
                    subtramite_select.select_by_index(1)
                    logging.info(f"Subtràmit auto-seleccionat: {subtramite_select.first_selected_option.text}")
                time.sleep(1)
            except Exception as e_sub:
                logging.debug(f"Subtràmit (comboNivelServicio3) no requerit o no trobat: {e_sub}")

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
                if self.headless:
                    logging.warning("CAPTCHA detectat en mode headless — no es pot resoldre. Abortant.")
                    self._save_debug_snapshot("captcha_headless")
                    return results
                
                logging.info("⚠️  ATENCIÓ: Resol el CAPTCHA manualment al navegador.")
                current_url = self.driver.current_url
                logging.info("Esperant resolució manual del CAPTCHA (màxim 120s)...")
                
                try:
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
                    return results
            else:
                logging.debug("No s'ha detectat CAPTCHA visible. Intentant continuar automàticament...")
                try:
                    # Intentem clicar el botó de continuar
                    submit_btn = None
                    
                    # Llista de selectors possibles per al botó
                    selectors = [
                        (By.ID, "btnContinuar1"),
                        (By.ID, "btnAceptar"),
                        (By.ID, "btnContinuar"),
                        (By.CSS_SELECTOR, "[id^='btnContinuar']"),
                        (By.CSS_SELECTOR, "input[type='button'][id*='Continuar']"),
                        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'continuar')]"),
                        (By.XPATH, "//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'aceptar')]"),
                        (By.XPATH, "//input[@type='submit']"),
                        (By.XPATH, "//input[@type='button']"),
                        (By.CSS_SELECTOR, "button.btn-primary"),
                        (By.CSS_SELECTOR, ".boton_azul")
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
                            
                        logging.info("Botó 'Continuar' clicat. Esperant que SEPE carregui pas 2...")
                        # SEPE fa una cadena d'AJAX síncrons:
                        #   validaNIE → compruebaMascaraDNI → validaDatosServicio
                        #   → loadMensajesYPantallaMapa → showPantallaMapa
                        # showPantallaMapa posa HTML dins #contenido2.
                        # Si hi ha error al formulari, apareix un mensajeInfo visible.
                        # Esperem que #contenido2 tingui contingut O que hi hagi un error visible.
                        try:
                            WebDriverWait(self.driver, 30).until(
                                lambda d: (
                                    # Pas 2 carregat (contenido2 té HTML)
                                    len(d.execute_script(
                                        "var el = document.getElementById('contenido2');"
                                        "return el ? el.innerHTML.trim() : '';"
                                    )) > 50
                                ) or (
                                    # Error de validació visible (mensajeInfo amb display != none)
                                    d.execute_script(
                                        "var msgs = document.querySelectorAll('.mensajeInfo');"
                                        "for(var i=0;i<msgs.length;i++){"
                                        "  if(msgs[i].style.display !== 'none' && msgs[i].textContent.trim()){"
                                        "    return msgs[i].textContent.trim();"
                                        "  }"
                                        "} return '';"
                                    ) != ''
                                )
                            )
                            # Check what we got
                            contenido2_len = self.driver.execute_script(
                                "var el = document.getElementById('contenido2');"
                                "return el ? el.innerHTML.trim().length : 0;")
                            if contenido2_len > 50:
                                logging.info(f"Pas 2 carregat (contenido2: {contenido2_len} chars)")
                            else:
                                error_msg = self.driver.execute_script(
                                    "var msgs = document.querySelectorAll('.mensajeInfo');"
                                    "for(var i=0;i<msgs.length;i++){"
                                    "  if(msgs[i].style.display !== 'none' && msgs[i].textContent.trim()){"
                                    "    return msgs[i].textContent.trim();"
                                    "  }"
                                    "} return '';"
                                )
                                logging.warning(f"Error de validació SEPE: {error_msg}")
                        except:
                            logging.warning("Timeout 30s esperant pas 2 del SEPE.")
                    else:
                        logging.warning("No s'ha trobat el botó de continuar, però tampoc hi ha captcha.")
                        # Debug HTML per veure per què no troba el botó
                        with open("debug_no_button.html", "w", encoding="utf-8") as f:
                            f.write(self.driver.page_source)
                except Exception as e:
                    logging.error(f"Error intentant clicar continuar: {e}")

            # 6. Comprovar disponibilitat
            logging.info("Analitzant resultat de la cerca...")
            
            # 6b. GESTIÓ DEL CANAL: comprovar cada tipus de cita sol·licitat
            channel_select_elem = self._find_channel_selector(timeout=12)
            
            if channel_select_elem:
                # Hi ha selector de canal — comprovem cada tipus
                for i, appt_type in enumerate(appt_types):
                    if i > 0:
                        # Re-buscar el selector per si la pàgina ha canviat
                        channel_select_elem = self._find_channel_selector(timeout=5)
                        if not channel_select_elem:
                            logging.warning("No s'ha pogut re-trobar el selector de canal per al següent tipus.")
                            break
                    
                    self._select_channel(channel_select_elem, appt_type)
                    
                    # Wait for offices or error to appear after channel selection
                    try:
                        WebDriverWait(self.driver, 15).until(
                            lambda d: any(kw in d.find_element(By.TAG_NAME, "body").text.lower()
                                          for kw in ["primer hueco", "primer buit",
                                                     "no podemos ofrecerle", "no podem oferir",
                                                     "no hay citas", "no hi ha cites",
                                                     "seleccione la oficina", "seleccioneu l'oficina",
                                                     "listado de oficinas", "llistat d'oficines",
                                                     "en estos momentos no podemos",
                                                     "no existen huecos"])
                        )
                        logging.info("Contingut detectat després de selecció de canal.")
                    except:
                        logging.warning("Timeout esperant contingut després de selecció de canal (15s).")
                    
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

    def _find_channel_selector(self, timeout=12):
        """Busca el selector de canal amb polling fins que aparegui o timeout."""
        end_time = time.time() + timeout
        while time.time() < end_time:
            try:
                channel_selects = self.driver.find_elements(By.TAG_NAME, "select")
                
                # Buscar per nom/id amb 'canal'
                for s in channel_selects:
                    try:
                        if s.is_displayed() and (
                            'canal' in (s.get_attribute('name') or '').lower() or 
                            'canal' in (s.get_attribute('id') or '').lower()
                        ):
                            logging.info("Selector de canal trobat.")
                            return s
                    except:
                        continue
                
                # Fallback: text-based
                page_lower = self.driver.page_source.lower()
                if "seleccione el canal" in page_lower or "seleccioneu el canal" in page_lower:
                    for s in channel_selects:
                        try:
                            if s.is_displayed():
                                logging.info("Selector de canal trobat (per text).")
                                return s
                        except:
                            continue
                
                # If page already shows result/error, don't wait more
                body_lower = self.driver.find_element(By.TAG_NAME, "body").text.lower()
                early_exit_kws = [
                    "no podemos ofrecerle", "no podem oferir",
                    "no hay citas", "no hi ha cites",
                    "no existen gestiones", "no existeixen gestions",
                    "campos obligatorios", "camps obligatoris",
                    "primer hueco", "primer buit",
                    "seleccione la oficina", "seleccioneu l'oficina",
                ]
                if any(kw in body_lower for kw in early_exit_kws):
                    logging.info("No hi ha selector de canal; pàgina ja té resultat.")
                    return None
                
                time.sleep(1)
            except Exception as e:
                logging.debug(f"Error buscant selector de canal: {e}")
                time.sleep(1)
        
        logging.warning(f"Timeout {timeout}s buscant selector de canal.")
        return None

    def _select_channel(self, channel_select_elem, appt_type):
        """Selecciona un canal (presencial/telefònica) al selector."""
        try:
            select_obj = Select(channel_select_elem)
            options_text = [o.text.lower() for o in select_obj.options]
            logging.debug(f"Opcions de canal disponibles: {options_text}")
            
            # SEPE uses specific values: 1=Presencial, 3=Telefònica
            if appt_type == 'person':
                try:
                    select_obj.select_by_value("1")
                    logging.debug("Canal 'Presencial' seleccionat (value=1).")
                except:
                    # Fallback to text matching
                    for i, text in enumerate(options_text):
                        if 'presencial' in text:
                            select_obj.select_by_index(i)
                            logging.debug(f"Canal 'Presencial' seleccionat per text (opció: '{text}').")
                            break
            else:
                try:
                    select_obj.select_by_value("3")
                    logging.debug("Canal 'Telefònica' seleccionat (value=3).")
                except:
                    for i, text in enumerate(options_text):
                        if 'telef' in text:
                            select_obj.select_by_index(i)
                            logging.debug(f"Canal 'Telefònica' seleccionat per text (opció: '{text}').")
                            break
            
            # Trigger SEPE's own onchange handlers (limpiarMensajes + cargaOficinasMapa)
            self.driver.execute_script("""
                var el = arguments[0];
                el.dispatchEvent(new Event('change', { bubbles: true }));
                if (typeof $ !== 'undefined') { $(el).trigger('change'); }
                if (typeof limpiarMensajes === 'function') { limpiarMensajes(); }
                if (typeof cargaOficinasMapa === 'function') { cargaOficinasMapa(); }
            """, channel_select_elem)
            
            return True
        except Exception as e:
            logging.warning(f"Error seleccionant canal: {e}")
            return False

    def _check_page_result(self, zip_code, dni):
        """Comprova la pàgina actual per determinar si hi ha disponibilitat."""
        time.sleep(2)
        
        # Use VISIBLE text only — page_source includes i18n/JS strings that cause
        # false negatives (e.g. 'no podemos ofrecerle cita' in message bundles)
        try:
            visible_text = self.driver.find_element(By.TAG_NAME, "body").text.lower()
        except:
            visible_text = ""
        
        logging.info(f"[DETECT] Visible text length: {len(visible_text)} chars")
        logging.info(f"[DETECT] First 500 chars: {visible_text[:500]}")
        
        # === POSITIVE indicators FIRST (castellà i català) ===
        positive_indicators = [
            # Llistat d'oficines (pas 2 del SEPE) - SPECIFIC phrases only
            "primer hueco disponible",
            "primer buit disponible",
            # NOTE: "oficinas disponibles" removed - matches instructional text
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
            if indicator in visible_text:
                logging.info(f"Resultat POSITIU detectat per indicador: '{indicator}'")
                self._save_debug_snapshot("success")
                return True
        
        # Check positive HTML elements (only specific, reliable ones)
        positive_elements = [
            (By.CLASS_NAME, "tablaOferta"),
            (By.CSS_SELECTOR, "input[type='checkbox'][name*='oficina']"),
            (By.CSS_SELECTOR, "input[type='checkbox'][name*='Oficina']"),
            (By.CSS_SELECTOR, ".oficina-card"),
            # NOTE: [class*='disponible'], [class*='mapa'], .leaflet-container
            # removed — they match page-structure elements always present on step 2
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
        
        # === NEGATIVE phrases (only in visible text, not page_source) ===
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
            "no s'han trobat cites",
            # Errors de formulari (pas 1 no superat)
            "no ha seleccionat cap",
            "no ha seleccionado ning",
            "camps obligatoris",
            "campos obligatorios",
            "no existeixen gestions disponibles",
            "no existen gestiones disponibles",
            "no es posible solicitar cita",
            "en estos momentos no podemos ofrecer",
            "en aquests moments no podem oferir",
            "no existen huecos disponibles",
            "no existeixen buits disponibles",
            "ha superat el nombre",
            "ha superado el n\u00famero",
        ]
        
        for phrase in negative_phrases:
            if phrase in visible_text:
                logging.debug(f"Resultat NEGATIU detectat per frase: '{phrase}'")
                self._save_debug_snapshot("negative")
                return False

        logging.warning("Resultat incert. No s'ha trobat ni error ni confirmació clara.")
        self._save_debug_snapshot("uncertain")
        return False

    def _extract_offices(self):
        """Extreu oficines disponibles com a llista de dicts {name, date}.

        Usa text visible (no page_source) per evitar tags HTML residuals.
        El text del SEPE segueix el patró:
            A. NOM OFICINA - SEPE
            Primer hueco disponible:
            día, DD de mes de YYYY, HH:MM
        """
        offices = []
        try:
            body_text = self.driver.find_element(By.TAG_NAME, "body").text
            lines = [l.strip() for l in body_text.split('\n') if l.strip()]

            # Patró: "A. NOM - SEPE" seguit de "Primer hueco/buit disponible:" + data
            i = 0
            while i < len(lines):
                line = lines[i]
                # Detectar línia de nom d'oficina: "A. ...", "B. ...", etc.
                if re.match(r'^[A-Z]\.\s+', line):
                    name = line
                    date_str = ''
                    # Buscar "Primer hueco/buit disponible:" a continuació
                    for j in range(i + 1, min(i + 4, len(lines))):
                        if re.match(r'primer\s+(?:hueco|buit)\s+disponible', lines[j], re.IGNORECASE):
                            # La data pot estar a la mateixa línia o a la següent
                            rest = re.sub(r'primer\s+(?:hueco|buit)\s+disponible[:\s]*', '', lines[j], flags=re.IGNORECASE).strip()
                            if rest and re.search(r'\d{1,2}:\d{2}', rest):
                                date_str = rest
                            elif j + 1 < len(lines) and re.search(r'\d{1,2}:\d{2}', lines[j + 1]):
                                date_str = lines[j + 1].strip()
                            break
                    offices.append({'name': name, 'date': date_str})
                i += 1

            # Fallback: si no hem trobat el patró A./B., buscar per "Primer hueco"
            if not offices:
                for i, line in enumerate(lines):
                    if re.match(r'primer\s+(?:hueco|buit)\s+disponible', line, re.IGNORECASE):
                        rest = re.sub(r'primer\s+(?:hueco|buit)\s+disponible[:\s]*', '', line, flags=re.IGNORECASE).strip()
                        date_str = rest if rest and re.search(r'\d{1,2}:\d{2}', rest) else ''
                        if not date_str and i + 1 < len(lines) and re.search(r'\d{1,2}:\d{2}', lines[i + 1]):
                            date_str = lines[i + 1].strip()
                        if date_str:
                            offices.append({'name': f'Oficina {len(offices) + 1}', 'date': date_str})

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
