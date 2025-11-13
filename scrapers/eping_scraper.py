# scrapers/eping_scraper.py (Corrected and Robust Version)

import argparse
import glob
import json
import logging
import os
import sys
import time
from datetime import datetime

import pandas as pd
from selenium import webdriver
from selenium.common.exceptions import (ElementClickInterceptedException,
                                        NoSuchElementException, TimeoutException)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

# Add parent directories to path to allow importing from 'support' if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class EPingScraper:
    """
    Scrapes ePing by using the UI to filter by HS code, and then downloads the results.
    This version uses robust interaction methods for the Vue.js components.
    """

    def __init__(self, headless=False, driver_path='./geckodriver.exe'):
        self.driver = None
        self.wait = None
        self.headless = headless
        self.driver_path = driver_path
        self.download_dir = os.path.join(os.getcwd(), "eping_downloads")

    def _get_firefox_options(self):
        options = Options()
        if self.headless: options.add_argument("--headless")
        common_paths = [r"C:\Program Files\Mozilla Firefox\firefox.exe", r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"]
        found_path = next((path for path in common_paths if os.path.exists(path)), None)
        if found_path:
            options.binary_location = found_path
            logging.info(f"Auto-detected Firefox at: {found_path}")
        else:
            logging.warning("Could not auto-detect Firefox. Letting Selenium try.")
        os.makedirs(self.download_dir, exist_ok=True)
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", self.download_dir)
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/vnd.ms-excel")
        return options

    def start_browser(self):
        logging.info("Starting Firefox WebDriver...")
        try:
            self.driver = webdriver.Firefox(service=Service(executable_path=self.driver_path), options=self._get_firefox_options())
            self.wait = WebDriverWait(self.driver, 20)
            return True
        except Exception as e:
            logging.error(f"FATAL: WebDriver failed to start. Error: {e}")
            return False

    def handle_cookie_banner(self):
        try:
            short_wait = WebDriverWait(self.driver, 5)
            accept_button = short_wait.until(EC.element_to_be_clickable((By.XPATH, "//button[.//span[contains(text(), 'Accept all')]]")))
            accept_button.click()
            logging.info("Accepted cookies.")
            time.sleep(1)
        except TimeoutException:
            logging.info("No cookie banner was detected.")

    def _filter_by_hs_code(self, hs_code_prefix):
        """Robust HS-code selection for vue-treeselect component with fallback to keyboard selection."""
        try:
            logging.info("Opening advanced search fields...")
            self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Search more fields')]"))).click()
            self.wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@data-text='Select HS code(s)']"))).click()
            logging.info("Clicked HS code placeholder.")

            try:
                hs_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".vue-treeselect__input input")))
            except TimeoutException:
                hs_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".vue-treeselect__input")))

            logging.info(f"Setting HS code to '{hs_code_prefix}' by dispatching JS events...")
            set_value_js = "arguments[0].value = arguments[1]; arguments[0].dispatchEvent(new Event('input', {bubbles: true}));"
            self.driver.execute_script(set_value_js, hs_input, hs_code_prefix)
            time.sleep(1) # Allow component to react

            logging.info("Waiting for HS code suggestion to appear...")
            suggestion_xpath = f"//div[contains(@class,'vue-treeselect__option')]//*[contains(text(), '{hs_code_prefix}')]"
            suggestion = self.wait.until(EC.element_to_be_clickable((By.XPATH, suggestion_xpath)))
            
            logging.info("Suggestion found — clicking it via JS.")
            self.driver.execute_script("arguments[0].click();", suggestion)
            
            self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@title='Close']"))).click()
            logging.info("Successfully filtered by HS code. Waiting for results to load...")
            time.sleep(5)
            return True

        except Exception as e:
            logging.error(f"Failed during HS code filtering: {e}", exc_info=True)
            self.save_snapshot("eping_filter_fail")
            return False
            
    def _download_and_parse_excel(self):
        """Downloads the excel file and waits for the download to stabilize before parsing."""
        try:
            for f in glob.glob(os.path.join(self.download_dir, "*.xlsx")): os.remove(f)

            self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Export search results')]"))).click()
            
            try: # Handle the optional warning modal
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'modal-card')]//button[contains(., 'OK')]"))).click()
                logging.info("Download warning modal detected — clicking OK.")
            except TimeoutException:
                logging.info("No download modal detected.")

            # --- Robustly wait for download to complete by checking file size stabilization ---
            end_time = time.time() + 90
            downloaded_file_path = None
            while time.time() < end_time:
                files = glob.glob(os.path.join(self.download_dir, "*.xlsx"))
                if files:
                    downloaded_file_path = files[0]
                    last_size, stable_count = -1, 0
                    # Check for size stability 3 times to be sure
                    while time.time() < end_time and stable_count < 3:
                        try:
                            current_size = os.path.getsize(downloaded_file_path)
                            if current_size > 0 and current_size == last_size:
                                stable_count += 1
                            else:
                                stable_count = 0
                            last_size = current_size
                            time.sleep(1)
                        except OSError:
                            time.sleep(1)
                    if stable_count >= 3:
                        logging.info(f"Download complete and stable: {os.path.basename(downloaded_file_path)}")
                        break
                time.sleep(0.5)

            if not downloaded_file_path: raise TimeoutException("Download timed out.")
            
            df = pd.read_excel(downloaded_file_path)
            return df.to_dict('records')

        except Exception as e:
            logging.error(f"Error during download/parsing: {e}", exc_info=True)
            self.save_snapshot("eping_download_fail")
            return None

    def scrape_notifications(self, config):
        hs_code_prefix = config['hs_code'][:4]
        country_code = f"C{config['target_market_id']}"
        url = f"https://www.epingalert.org/en/Search/Index?countryIds={country_code}"

        if not self.start_browser(): return None
        
        self.driver.get(url)
        self.handle_cookie_banner()
        
        if not self._filter_by_hs_code(hs_code_prefix):
            self.quit()
            return None

        final_url = self.driver.current_url
        
        try:
            WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Showing 0 - 0 of 0')]")))
            logging.warning("No notifications found.")
            return {"source_url": final_url, "status": "No notifications found", "notifications": []}
        except TimeoutException:
            logging.info("Results detected. Proceeding to download.")
            data = self._download_and_parse_excel()
            if data is not None:
                return {"source_url": final_url, "status": "Success", "notifications": data}
            else:
                return {"source_url": final_url, "status": "Error during download", "notifications": []}
        finally:
            self.quit()

    def save_snapshot(self, label="snapshot"):
        os.makedirs('debug_snapshots', exist_ok=True)
        path = os.path.join('debug_snapshots', f"{label}_{datetime.now():%Y%m%d_%H%M%S}")
        self.driver.save_screenshot(f"{path}.png")

    def quit(self):
        if self.driver: self.driver.quit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape ePing notifications.")
    parser.add_argument("--output", required=True, help="Path to save the output JSON file.")
    parser.add_argument("--headless", action='store_true', help="Run in headless mode.")
    args = parser.parse_args()

    CONFIG = {
        "hs_code": "847130",
        "target_market_id": "842"
    }
    
    scraper = EPingScraper(headless=args.headless, driver_path=r".\geckodriver.exe")
    
    try:
        data = scraper.scrape_notifications(CONFIG)
        if data:
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4, default=str)
            logging.info(f"SUCCESS: ePing data saved to {args.output}")
        else:
            logging.error("FAIL: ePing scraping could not be completed.")
            sys.exit(1)
    except Exception as e:
        logging.critical(f"A critical error occurred during execution: {e}", exc_info=True)
        sys.exit(1)