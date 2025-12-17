from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
from selenium.webdriver.support.ui import Select
from selenium.webdriver.common.keys import Keys
import time
import json

def scrape_tramits():
    options = webdriver.ChromeOptions()
    options.add_argument('--no-sandbox')
    options.add_argument('--disable-dev-shm-usage')
    options.add_argument('--disable-blink-features=AutomationControlled')
    options.add_argument("user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36")

    driver = webdriver.Chrome(service=Service(ChromeDriverManager().install()), options=options)
    wait = WebDriverWait(driver, 20)
    
    results = {}

    try:
        print("Accedint a la web...")
        url = "https://sede.sepe.gob.es/portalSede/procedimientos-y-servicios/personas/proteccion-por-desempleo/cita-previa/cita-previa-solicitud.html"
        driver.get(url)

        # Cookies
        try:
            cookie_btn = WebDriverWait(driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//button[contains(text(), 'Aceptar todas') or contains(text(), 'Aceptar')]")))
            cookie_btn.click()
            time.sleep(1)
        except:
            pass

        # Iframe
        try:
            iframe = WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.XPATH, "//iframe[contains(@src, 'citaprevia')]")))
            driver.switch_to.frame(iframe)
        except:
            print("No s'ha trobat iframe, continuem al context principal.")

        # CP
        print("Introduint CP 08001...")
        
        # Try interacting with Select2 natively (click -> type -> enter)
        try:
            # Click the Select2 container to open dropdown
            # Use a very specific selector for the Zip Code Select2 container
            select2_container = wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, ".select2-selection[aria-labelledby='select2-datosCodigoPostal-container']")))
            select2_container.click()
            
            # Wait for search box
            search_box = wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "select2-search__field")))
            search_box.send_keys("08001")
            time.sleep(1) # Wait for search results
            search_box.send_keys(Keys.ENTER)
            
        except Exception as e:
            print(f"Error interactuant amb Select2: {e}")
            # Fallback to JS injection if native interaction fails
            print("Intentant fallback JS...")
            driver.execute_script("""
                var newOption = new Option('08001', '08001', true, true);
                $('#datosCodigoPostal').append(newOption).trigger('change');
                if (typeof seleccionDeCodigoPostal === 'function') {
                    seleccionDeCodigoPostal();
                }
            """)

        # Wait for Trámite select to be enabled/visible
        print("Esperant càrrega de tràmits...")
        
        # Wait until divComboServiciosNivel has content (the select is injected there)
        try:
            WebDriverWait(driver, 15).until(lambda d: d.find_element(By.ID, "divComboServiciosNivel").get_attribute("innerHTML").strip() != "")
            # Debug: print full content to find the correct ID
            elem = driver.find_element(By.ID, "divComboServiciosNivel")
            print(f"DEBUG: Contingut divComboServiciosNivel:\n{elem.get_attribute('innerHTML')}")
            
            # Try to find any select element inside
            selects = elem.find_elements(By.TAG_NAME, "select")
            if selects:
                print(f"DEBUG: Trobats {len(selects)} selects dins divComboServiciosNivel")
                for s in selects:
                    print(f"DEBUG: Select ID: {s.get_attribute('id')}, Name: {s.get_attribute('name')}")
                    tramite_select_elem = s # Use the first one found
            else:
                print("DEBUG: Cap select trobat dins divComboServiciosNivel")
                # Maybe it's loading? Wait a bit more
                time.sleep(2)
                selects = elem.find_elements(By.TAG_NAME, "select")
                if selects:
                     tramite_select_elem = selects[0]
                else:
                     raise Exception("No s'ha trobat cap select de tràmits")

        except Exception as e:
            print(f"Error esperant tràmits: {e}")
            # Debug: print page source snippet around divComboServiciosNivel
            try:
                elem = driver.find_element(By.ID, "divComboServiciosNivel")
                print(f"Contingut divComboServiciosNivel: {elem.get_attribute('innerHTML')[:100]}...")
            except:
                print("Element divComboServiciosNivel NO trobat.")
            raise e
        
        # tramite_select_elem is already set above
        # We want comboNivelServicio2 as the main "Trámite" list
        try:
            tramite_select_elem = driver.find_element(By.ID, "comboNivelServicio2")
        except:
            print("No s'ha trobat comboNivelServicio2. Potser només hi ha nivell 1?")
            # Fallback to whatever we found
            pass

        tramite_select = Select(tramite_select_elem)
        
        tramite_options = [opt for opt in tramite_select.options if opt.get_attribute("value") != ""]
        
        print(f"Trobats {len(tramite_options)} tràmits principals.")
        
        results = {}
        
        for i in range(len(tramite_options)):
            # Re-find element to avoid stale reference
            tramite_select_elem = driver.find_element(By.ID, "comboNivelServicio2")
            tramite_select = Select(tramite_select_elem)
            option = [opt for opt in tramite_select.options if opt.get_attribute("value") != ""][i]
            
            tramite_text = option.text
            tramite_value = option.get_attribute("value")
            print(f"Processant tràmit: {tramite_text} ({tramite_value})")
            
            # Select the option
            tramite_select.select_by_value(tramite_value)
            
            # Wait for potential next level (AJAX)
            time.sleep(2)
            
            # Check for level 3 (Subtrámite)
            subtramites = []
            try:
                # Check if comboNivelServicio3 exists and is visible
                level3_id = "comboNivelServicio3"
                if len(driver.find_elements(By.ID, level3_id)) > 0:
                    level3 = driver.find_element(By.ID, level3_id)
                    if level3.is_displayed():
                        l3_select = Select(level3)
                        subtramites = [{"text": o.text, "value": o.get_attribute("value")} 
                                       for o in l3_select.options if o.get_attribute("value") != ""]
                        print(f"  -> Trobats {len(subtramites)} subtràmits.")
            except Exception as e:
                print(f"  -> Error buscant subtràmits: {e}")
            
            results[tramite_text] = {
                "value": tramite_value,
                "subtramites": subtramites
            }
            
        print("Extracció finalitzada.")
        
    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

    finally:
        driver.quit()

    print("\n\n=== RESULTATS DE COMBINACIONS ===")
    print(json.dumps(results, indent=4, ensure_ascii=False))
    
    # Define paths relative to this script
    import os
    BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    DATA_DIR = os.path.join(BASE_DIR, 'data')
    OUTPUT_FILE = os.path.join(DATA_DIR, "tramits_sepe.json")

    # Save to file
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(results, f, indent=4, ensure_ascii=False)

    return results

if __name__ == "__main__":
    scrape_tramits()
