from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select
import time

def automate_sepe_appointment():
    # Configuration
    DNI = "12345678Z"  # Replace with your DNI
    ZIP_CODE = "28001" # Replace with your ZIP
    
    # Initialize Driver (Ensure you have chromedriver installed)
    options = webdriver.ChromeOptions()
    # options.add_argument("--headless") # Don't use headless for Captcha
    driver = webdriver.Chrome(options=options)
    
    try:
        # 1. Start Page
        print("Navigating to SEPE Cita Previa...")
        driver.get("https://sede.sepe.gob.es/portalSede/procedimientos-y-servicios/personas/proteccion-por-desempleo/cita-previa/cita-previa-solicitud.html")
        
        # Wait for and click "Iniciar solicitud"
        # Note: The text might be inside a nested span or different tag
        start_btn = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.XPATH, "//a[contains(text(), 'Iniciar solicitud') or contains(text(), 'Solicitar cita')]"))
        )
        start_btn.click()
        
        # 2. Form Page (ZIP, DNI, Procedure)
        print("Filling form details...")
        
        # Wait for the form to load
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.XPATH, "//input[contains(@id, 'nif') or contains(@name, 'nif')]"))
        )
        
        # Enter ZIP Code
        # Strategy: Find label containing 'Postal' and get the following input
        zip_input = driver.find_element(By.XPATH, "//label[contains(text(), 'Postal')]/following::input[1]")
        zip_input.clear()
        zip_input.send_keys(ZIP_CODE)
        
        # Enter DNI/NIE
        dni_input = driver.find_element(By.XPATH, "//label[contains(text(), 'NIF') or contains(text(), 'NIE')]/following::input[1]")
        dni_input.clear()
        dni_input.send_keys(DNI)
        
        # Select Procedure (Trámite)
        # This is usually a dropdown. We select the first available option or a specific one by value/text
        try:
            tramite_select = Select(driver.find_element(By.XPATH, "//label[contains(text(), 'Trámite')]/following::select[1]"))
            # Example: Select by index (1 is usually the first real option)
            tramite_select.select_by_index(1) 
            print("Selected procedure.")
        except Exception as e:
            print("Could not select procedure automatically (might be radio buttons):", e)

        # 3. CAPTCHA Handling (Manual)
        print("\n" + "="*40)
        print("ACTION REQUIRED: Please solve the CAPTCHA in the browser window.")
        print("Once solved, press ENTER here in the console to continue...")
        print("="*40 + "\n")
        input() # Wait for user input
        
        # Click "Aceptar" / "Enviar"
        submit_btn = driver.find_element(By.XPATH, "//input[@type='submit' or @value='Aceptar' or @value='Enviar']")
        submit_btn.click()
        
        # 4. Check Results
        # Wait to see if we get a success message or error
        time.sleep(5) # Simple wait for page transition
        
        if "no hay citas" in driver.page_source.lower():
            print("Result: No appointments available.")
        else:
            print("Result: Appointments might be available! Check the browser.")
            
        # Keep browser open for a bit to review
        time.sleep(10)
        
    except Exception as e:
        print(f"An error occurred: {e}")
        
    finally:
        driver.quit()

if __name__ == "__main__":
    automate_sepe_appointment()
