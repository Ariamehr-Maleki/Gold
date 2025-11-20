import json
import logging
import os
import time
from datetime import datetime

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait
from selenium.common.exceptions import TimeoutException, NoSuchElementException

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")


class CountryCodeExtractor:
    BASE_URL = (
        "https://exportpotential.intracen.org/en/products/tree-map?"
        "fromMarker=w&exporter=w&toMarker=w&market=w&whatMarker=k"
    )
    WAIT_TIME = 15

    def __init__(self, headless=False, driver_path="./geckodriver.exe"):
        self.headless = headless
        self.driver_path = driver_path
        self.driver = None
        self.wait = None

    def start(self):
        options = Options()
        if self.headless:
            options.add_argument("--headless")

        # Auto-select Firefox on Linux + Windows
        win_path = r"C:\Program Files\Mozilla Firefox\firefox.exe"
        if os.path.exists(win_path):
            options.binary_location = win_path

        service = Service(self.driver_path)

        self.driver = webdriver.Firefox(service=service, options=options)
        self.wait = WebDriverWait(self.driver, self.WAIT_TIME)

    def handle_popup(self):
        """
        Checks for the disclaimer popup, accepts the checkbox if present,
        and closes the dialog.
        """
        try:
            # Use a short local wait so we don't block execution if no popup exists
            short_wait = WebDriverWait(self.driver, 5)

            # Try to detect popup root first
            popup_present = short_wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".mat-mdc-dialog-container"))
            )

            if popup_present:
                logging.info("Popup detected. Attempting to handle...")
                
                # 1. Try to click the checkbox ("Don't show again" or similar)
                try:
                    checkbox = self.driver.find_element(By.ID, "mat-mdc-checkbox-1-input")
                    if not checkbox.is_selected():
                        self.driver.execute_script("arguments[0].click();", checkbox)
                except Exception:
                    logging.debug("Checkbox not found inside popup (ignoring).")

                # 2. Try to close the popup
                try:
                    close_btn = self.driver.find_element(
                        By.XPATH,
                        "//button[contains(@class, 'mat-mdc-dialog-close-button')]"
                    )
                    close_btn.click()
                    
                    # Wait for the overlay to disappear
                    short_wait.until(EC.invisibility_of_element_located(
                        (By.CLASS_NAME, "cdk-overlay-backdrop")
                    ))
                    logging.info("Popup closed successfully.")
                except Exception:
                    logging.warning("Close button not found — popup may already be absent.")

        except TimeoutException:
            # This is good! It means no popup blocked our view.
            # logging.info("No popup detected.")
            pass
        except Exception as e:
            logging.warning(f"Unexpected error handling popup: {e}")

    def open_page(self):
        # logging.info("Opening/Resetting main page...")
        self.driver.get(self.BASE_URL)
        
        # Wait for the app root to load
        self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "app-root")))
        
        # Check for popup immediately after load
        self.handle_popup()

    def open_exporter_dropdown(self):
        # logging.info("Opening country dropdown...")
        dropdown = self.wait.until(
            EC.element_to_be_clickable(
                (By.XPATH, "//h4[contains(text(),'For exporter')]/ancestor::div[contains(@class,'ddinput')]")
            )
        )
        dropdown.click()
        time.sleep(0.5)

    def search_and_select_country(self, country):
        logging.info(f"Processing: {country}")

        input_box = self.wait.until(
            EC.presence_of_element_located((By.ID, "search-exporter"))
        )

        input_box.clear()
        input_box.send_keys(country)
        
        # Wait for list to populate via AJAX
        time.sleep(1.5)

        # Logic to click the specific result based on HTML title attribute
        xpath_expression = (
            f"//app-country-list[@type='exporters']"
            f"//div[contains(@class, 'clickable') and @title='{country}']"
        )

        country_option = self.wait.until(
            EC.element_to_be_clickable((By.XPATH, xpath_expression))
        )
        country_option.click()
        
        time.sleep(2.5)  # Allow page reload / URL update

    def extract_country_code_from_url(self):
        url = self.driver.current_url
        if "exporter=" not in url:
            return None

        code = url.split("exporter=")[1].split("&")[0]
        if code == 'w': # 'w' means World (selection failed or default)
            return None
            
        return code

    def quit(self):
        if self.driver:
            self.driver.quit()


def main():
    input_file = "countries.json"
    output_file = "extracted_country_codes.json"
    
    # 1. Load Countries
    try:
        with open(input_file, "r", encoding="utf-8") as f:
            countries_list = json.load(f)
        logging.info(f"Loaded {len(countries_list)} countries from {input_file}")
    except FileNotFoundError:
        logging.error(f"File {input_file} not found. Please create it.")
        return

    # 2. Start WebDriver
    extractor = CountryCodeExtractor(headless=False)
    extractor.start()

    results = []

    try:
        for i, country in enumerate(countries_list):
            result_entry = {
                "country": country,
                "code": None,
                "status": "Pending",
                "timestamp": datetime.now().isoformat()
            }

            try:
                # Reset page state for each country
                extractor.open_page()
                
                extractor.open_exporter_dropdown()
                extractor.search_and_select_country(country)
                
                code = extractor.extract_country_code_from_url()
                
                if code:
                    result_entry["code"] = code
                    result_entry["status"] = "Success"
                    logging.info(f"Successfully extracted {country}: {code}")
                else:
                    result_entry["status"] = "Code detection failed"
                    logging.warning(f"Could not detect code in URL for {country}")

            except TimeoutException:
                result_entry["status"] = "Not Found / Timeout"
                logging.error(f"Timeout: Could not find or select '{country}'")
            except Exception as e:
                result_entry["status"] = f"Error: {str(e)}"
                logging.error(f"Error processing '{country}': {e}")
            
            results.append(result_entry)

    except KeyboardInterrupt:
        logging.warning("Process interrupted by user. Saving current progress...")
    finally:
        # 3. Save Results
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(results, f, indent=4, ensure_ascii=False)
        
        logging.info(f"Finished. Results saved to {output_file}")
        extractor.quit()

if __name__ == "__main__":
    main()