# scrapers/eping_scraper.py

import argparse
import glob
import json
import logging
import os
import sys
import time
import re
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

# Add parent directories to path to allow importing from 'support'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Import Formatter ---
try:
    from support.eping_formatter import EPingReportBuilder
except ImportError:
    logging.warning("Could not import EPingReportBuilder. Output will be raw JSON.")
    EPingReportBuilder = None

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - EPING - %(levelname)s - %(message)s')

class EPingScraper:
    def __init__(self, headless=False, driver_path='./geckodriver.exe'):
        self.driver = None
        self.wait = None
        self.headless = headless
        self.driver_path = driver_path
        self.download_dir = os.path.abspath(os.path.join(os.getcwd(), "eping_downloads"))

    def _get_firefox_options(self):
        options = Options()
        if self.headless: 
            options.add_argument("--headless")
            options.add_argument("--window-size=1920,1080")

        # Attempt to find Firefox binary automatically
        common_paths = [
            r"C:\Program Files\Mozilla Firefox\firefox.exe", 
            r"C:\Program Files (x86)\Mozilla Firefox\firefox.exe"
        ]
        found_path = next((path for path in common_paths if os.path.exists(path)), None)
        if found_path:
            options.binary_location = found_path
            logging.info(f"Auto-detected Firefox at: {found_path}")
        
        # Configure automatic downloads
        os.makedirs(self.download_dir, exist_ok=True)
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", self.download_dir)
        options.set_preference("browser.download.useDownloadDir", True)
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", 
            "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet, application/vnd.ms-excel")
        return options

    def start_browser(self):
        logging.info("Starting Firefox WebDriver...")
        try:
            self.driver = webdriver.Firefox(service=Service(executable_path=self.driver_path), options=self._get_firefox_options())
            self.wait = WebDriverWait(self.driver, 45)
            self.driver.maximize_window()
            return True
        except Exception as e:
            logging.error(f"FATAL: WebDriver failed to start. Error: {e}")
            return False

    def handle_cookie_banner(self):
        try:
            short_wait = WebDriverWait(self.driver, 5)
            accept_button = short_wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Accept all') or contains(., 'I agree')]")))
            accept_button.click()
            logging.info("Accepted cookies.")
            time.sleep(1)
        except TimeoutException:
            pass

    def _filter_by_hs_code(self, hs_code_prefix):
        """
        Filters by HS Code and closes the dropdown using the ESCAPE key.
        """
        try:
            logging.info("--- START HS CODE FILTER ---")
            logging.info("⏳ Waiting 5s for page stability...")
            time.sleep(5)

            # --- STEP 1: Find and Click Placeholder ---
            placeholder_xpath = "//div[@data-text='Select HS code(s)']"
            
            try:
                trigger_div = self.driver.find_element(By.XPATH, placeholder_xpath)
                # If hidden, click 'Search more fields'
                if not trigger_div.is_displayed():
                    more_btn = self.wait.until(EC.element_to_be_clickable(
                        (By.XPATH, "//button[contains(., 'Search more fields')]")
                    ))
                    self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", more_btn)
                    more_btn.click()
                    time.sleep(2)
            except NoSuchElementException:
                pass

            logging.info("Clicking the HS Code placeholder...")
            trigger_div = self.wait.until(EC.element_to_be_clickable((By.XPATH, placeholder_xpath)))
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", trigger_div)
            trigger_div.click()
            time.sleep(1) 

            # --- STEP 2: Find Input & Type ---
            logging.info("Typing HS Code...")
            container = self.driver.find_element(By.ID, "hs-tree-select-container")
            hs_input = container.find_element(By.CSS_SELECTOR, "input.vue-treeselect__input")
            
            hs_input.send_keys(Keys.CONTROL + "a")
            hs_input.send_keys(Keys.DELETE)
            time.sleep(0.5)
            
            for char in hs_code_prefix:
                hs_input.send_keys(char)
                time.sleep(0.1)

            # Force Vue to recognize input
            self.driver.execute_script("arguments[0].dispatchEvent(new Event('input', { bubbles: true }));", hs_input)
            time.sleep(3)

            # --- STEP 3: Select Exact Code ---
            suggestion_xpath = f"//div[contains(@class, 'vue-treeselect__label') and contains(., '{hs_code_prefix}')]"
            
            try:
                suggestion = self.wait.until(EC.presence_of_element_located((By.XPATH, suggestion_xpath)))
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", suggestion)
                time.sleep(1)
                
                try:
                    suggestion.click()
                except ElementClickInterceptedException:
                    self.driver.execute_script("arguments[0].click();", suggestion)
                
                logging.info("Suggestion selected.")
            except TimeoutException:
                logging.warning("Exact suggestion not found, trying Enter key...")
                hs_input.send_keys(Keys.ENTER)

            # --- STEP 4: Cleanup (Close the Flywheel) ---
            try:
                logging.info("Closing the flywheel/dropdown...")
                time.sleep(1)
                # FIX: Send ESCAPE to the input field to close the menu
                hs_input.send_keys(Keys.ESCAPE)
                time.sleep(0.5)
                
                # Fallback: Click on the body
                self.driver.find_element(By.TAG_NAME, "body").click()
            except Exception as e: 
                logging.warning(f"Cleanup warning: {e}")

            logging.info("✅ Filter sequence finished.")
            time.sleep(5)
            return True

        except Exception as e:
            logging.error(f"❌ Filter Error: {e}", exc_info=True)
            self.save_snapshot("hs_filter_failed")
            return False

    def _check_results_count(self):
        try:
            count_elem = self.wait.until(EC.presence_of_element_located(
                (By.XPATH, "//div[contains(text(), 'Showing') and contains(text(), 'of')]")
            ))
            text = count_elem.text.strip()
            match = re.search(r'of\s+(\d+)', text)
            if match and int(match.group(1)) > 0:
                return True
            return False
        except:
            return False
            
    def _download_and_parse_excel(self):
        try:
            # Clear old files
            for f in glob.glob(os.path.join(self.download_dir, "*.xlsx")): 
                try: os.remove(f)
                except: pass

            logging.info("Clicking Export...")
            export_btn = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Export search results')]")))
            export_btn.click()
            
            # Handle modal
            try:
                WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'modal-card')]//button[contains(., 'OK')]"))).click()
            except TimeoutException: pass

            # Wait for download
            end_time = time.time() + 90
            while time.time() < end_time:
                files = glob.glob(os.path.join(self.download_dir, "*.xlsx"))
                if files:
                    f_path = files[0]
                    # Check file size stability
                    last_size, stable_count = -1, 0
                    while stable_count < 3:
                        try:
                            curr = os.path.getsize(f_path)
                            if curr == last_size and curr > 0: stable_count += 1
                            else: stable_count = 0
                            last_size = curr
                            time.sleep(1)
                        except: time.sleep(1)
                    
                    logging.info(f"✅ Download complete: {os.path.basename(f_path)}")
                    df = pd.read_excel(f_path)
                    df = df.where(pd.notnull(df), None)
                    return df.to_dict('records')
                time.sleep(1)
            return None
        except Exception as e:
            logging.error(f"Download Error: {e}")
            return None

    def scrape_notifications(self, config):
        hs_code_prefix = config['hs_code'] 
        country_code = config['target_market_id']
        url = f"https://www.epingalert.org/en/Search/Index?countryIds=C{country_code}"

        if not self.start_browser(): 
             return {"status": "Driver Start Failed", "notifications": []}
        
        try:
            logging.info(f"Navigating to {url}")
            self.driver.get(url)
            self.handle_cookie_banner()
            
            if not self._filter_by_hs_code(hs_code_prefix):
                return {"status": "Filter Failed", "notifications": []}

            if self._check_results_count():
                data = self._download_and_parse_excel()
                return {"status": "Success", "notifications": data or []}
            else:
                return {"status": "No notifications found", "notifications": []}

        except Exception as e:
            logging.error(f"Scrape Loop Error: {e}")
            self.save_snapshot("crash")
            return {"status": "Crash", "notifications": []}
        finally:
            if self.driver: self.driver.quit()

    def save_snapshot(self, label="snapshot"):
        try:
            os.makedirs('debug_snapshots', exist_ok=True)
            self.driver.save_screenshot(f"debug_snapshots/{label}_{datetime.now():%H%M%S}.png")
        except: pass
        
if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape ePing notifications.")
    parser.add_argument("--output", required=True, help="Output JSON file.")
    parser.add_argument("--headless", action='store_true', help="Headless mode.")
    parser.add_argument("--hs-code", help="HS code.", required=True)
    
    # ID arguments 
    parser.add_argument("--your-country-id", help="Numeric ID (Ignored by this scraper).")
    parser.add_argument("--target-market-id", help="Numeric ID.", required=True)

    # Name arguments
    parser.add_argument("--your-country-name", help="Your country.")
    parser.add_argument("--target-market-name", help="Target market.")

    args = parser.parse_args()

    # --- ADDED LOGGING ---
    logging.info(f"CLI ARGS RECEIVED: HS Code={args.hs_code}, Target ID={args.target_market_id}")

    config = {
        "hs_code": args.hs_code, 
        "target_market_id": args.target_market_id,
        "your_country_name": args.your_country_name if args.your_country_name else "[Your Country]",
        "target_market_name": args.target_market_name if args.target_market_name else "[Target Market]",
    }
    
    # Initialize result placeholder
    raw_result = None

    try:
        scraper = EPingScraper(headless=args.headless, driver_path=r".\geckodriver.exe")
        raw_result = scraper.scrape_notifications(config)
    except Exception as e:
        logging.error(f"Execution failed: {e}")
        raw_result = {"status": "Execution Error", "error": str(e), "notifications": []}

    # If raw_result ended up None (e.g. driver failed immediately)
    if raw_result is None:
        raw_result = {"status": "Unknown Failure", "notifications": []}

    # Prepare final payload with config included
    final_payload = {
        "config": config,
        "data": raw_result,
        "scraped_at": datetime.now().isoformat()
    }

    # Write to File
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            # default=str handles datetime/pandas objects serialization
            json.dump(final_payload, f, indent=4, ensure_ascii=False, default=str)
        logging.info(f"Successfully wrote output to {args.output}")
        
        # Also print to stdout for piping support
        print(json.dumps(final_payload, indent=4, default=str))
        
    except Exception as e:
        logging.error(f"Failed to write JSON output: {e}")