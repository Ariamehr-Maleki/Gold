# eping_scraper.py (Standalone, Final Version with Direct Click)

import json
import logging
import os
import time
import glob
from datetime import datetime
import pandas as pd

# --- Selenium Imports ---
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException, ElementClickInterceptedException
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC

# --- Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class EPingScraper:
    """
    Scrapes ePing by using the UI to filter by HS code, and then downloads the results.
    This version uses a direct click on the suggestion for maximum reliability.
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
            
    # --- FINAL REFACTORED METHOD ---
    def _filter_by_hs_code(self, hs_code_prefix):
        """Robust HS-code selection for vue-treeselect component with fallback to keyboard selection."""
        try:
            logging.info("Opening advanced search fields...")
            more_fields_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Search more fields')]")))
            more_fields_button.click()

            placeholder_div = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//div[@data-text='Select HS code(s)']")))
            placeholder_div.click()
            logging.info("Clicked HS code placeholder.")

            # Try to locate the real input inside the treeselect (sometimes an <input> inside .vue-treeselect__input)
            logging.info("Locating HS input element...")
            hs_input = None
            try:
                hs_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".vue-treeselect__input input")))
            except TimeoutException:
                # fallback to the container (some versions use a contenteditable div)
                hs_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, ".vue-treeselect__input")))

            # Focus the field and set value with events so Vue/two-way binding notices the change
            logging.info(f"Setting HS code to '{hs_code_prefix}' (dispatching input events)...")
            set_value_js = """
            const node = arguments[0];
            const val = arguments[1];
            // if there's a real input inside, set its value; otherwise set textContent of the element
            if (node.tagName === 'INPUT' || node.tagName === 'TEXTAREA') {
                node.focus();
                node.value = val;
                node.dispatchEvent(new Event('input', {bubbles: true}));
                node.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, key:'a'}));
            } else {
                // sometimes element is a container: find input inside or set innerText
                const inner = node.querySelector && node.querySelector('input');
                if (inner) {
                    inner.focus();
                    inner.value = val;
                    inner.dispatchEvent(new Event('input', {bubbles: true}));
                    inner.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, key:'a'}));
                } else {
                    node.focus();
                    node.textContent = val;
                    node.dispatchEvent(new Event('input', {bubbles: true}));
                    node.dispatchEvent(new KeyboardEvent('keydown', {bubbles: true, key:'a'}));
                }
            }
            return true;
            """
            self.driver.execute_script(set_value_js, hs_input, hs_code_prefix)
            time.sleep(0.6)  # small pause to let the component process

            # Some components require an extra key to trigger search; send one safely
            try:
                if hs_input.tag_name.lower() == "input":
                    hs_input.send_keys(Keys.SPACE)
                    hs_input.send_keys(Keys.BACKSPACE)
                else:
                    # try to find nested input and send keys
                    nested = hs_input.find_element(By.CSS_SELECTOR, "input")
                    nested.send_keys(Keys.SPACE)
                    nested.send_keys(Keys.BACKSPACE)
            except Exception:
                # ignore; already attempted JS events
                pass

            logging.info("Waiting for HS code suggestion to appear...")
            suggestion_selectors = [
                ".vue-treeselect__option", 
                ".vue-treeselect__option-label-container",
                ".treeselect__option",  # a possible variant
                "//div[contains(@class,'vue-treeselect__option') and contains(., '{}')]".format(hs_code_prefix)
            ]

            suggestion = None
            # Try CSS selectors first (proper waits)
            try:
                suggestion = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, f".vue-treeselect__option-label-container:contains('{hs_code_prefix}')")))
            except Exception:
                # selenium doesn't support :contains in CSS; search generically then filter
                try:
                    candidates = self.driver.find_elements(By.CSS_SELECTOR, ".vue-treeselect__option, .vue-treeselect__option-label-container, .treeselect__option")
                    for c in candidates:
                        try:
                            if hs_code_prefix in c.text:
                                suggestion = c
                                break
                        except Exception:
                            continue
                except Exception:
                    suggestion = None

            # If suggestion still None, try an XPath search (more reliable for contains)
            if not suggestion:
                try:
                    xpath = f"//div[contains(@class,'vue-treeselect__option') or contains(@class,'treeselect__option')]//*[contains(text(), '{hs_code_prefix}')]/ancestor::div[contains(@class,'vue-treeselect__option') or contains(@class,'treeselect__option')]"
                    suggestion = self.wait.until(EC.element_to_be_clickable((By.XPATH, xpath)))
                except Exception:
                    suggestion = None

            # If we found a suggestion element, click via JS (avoids intercept problems)
            if suggestion:
                logging.info("Suggestion found — clicking it via JS.")
                try:
                    self.driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", suggestion)
                except Exception as ex:
                    logging.warning(f"JS click failed ({ex}), attempting normal click.")
                    try:
                        suggestion.click()
                    except Exception:
                        logging.warning("Normal click failed; will try keyboard fallback.")
                        suggestion = None

            # Fallback: use keyboard arrows + enter (works if the suggestion list is focused)
            if not suggestion:
                logging.info("Falling back to keyboard selection: ARROW_DOWN + ENTER")
                try:
                    # Try to send keys to the actual input (or nested input)
                    target_input = hs_input
                    if hs_input.tag_name.lower() != "input":
                        try:
                            target_input = hs_input.find_element(By.CSS_SELECTOR, "input")
                        except Exception:
                            pass
                    target_input.send_keys(Keys.ARROW_DOWN)
                    time.sleep(0.2)
                    target_input.send_keys(Keys.ENTER)
                    time.sleep(0.5)
                except Exception as e:
                    logging.error(f"Keyboard fallback failed: {e}", exc_info=True)
                    self.save_snapshot("eping_hs_fallback_fail")
                    return False

            # Close advanced panel and wait a bit for results to update
            try:
                close_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[@title='Close']")))
                close_button.click()
            except Exception:
                logging.info("No 'Close' button found or unable to click — continuing anyway.")
            logging.info("Closed advanced search panel (if present). Waiting for results to update...")
            time.sleep(5)
            return True

        except Exception as e:
            logging.error(f"Failed during HS code filtering: {e}", exc_info=True)
            self.save_snapshot("eping_filter_fail")
            return False

            
    def _download_and_parse_excel(self):
        try:
            # Clean previous files
            for f in glob.glob(os.path.join(self.download_dir, "*.xlsx")):
                try:
                    os.remove(f)
                except Exception:
                    pass

            export_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//button[contains(., 'Export search results')]")))
            export_button.click()
            logging.info("Clicked 'Export'. Waiting for download or modal...")

            # --- Handle "Warning" modal if it appears ---
            try:
                modal_ok = WebDriverWait(self.driver, 5).until(
                    EC.element_to_be_clickable((By.XPATH, "//div[contains(@class,'modal-card')]//button[contains(., 'OK')]"))
                )
                logging.info("Download warning modal detected — clicking OK.")
                modal_ok.click()
                time.sleep(1)
            except TimeoutException:
                logging.info("No modal detected — continuing normally.")

            # --- Wait for download to complete ---
            end_time = time.time() + 90
            downloaded_file_path = None
            while time.time() < end_time:
                files = glob.glob(os.path.join(self.download_dir, "*.xlsx"))
                if files:
                    downloaded_file_path = files[0]
                    last_size, stable_count = -1, 0
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
                        logging.info(f"Download complete: {os.path.basename(downloaded_file_path)}")
                        break
                time.sleep(0.5)

            if not downloaded_file_path:
                logging.error("Download timed out.")
                return None

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
        logging.info(f"Final search URL is: {final_url}")
        
        try:
            short_wait = WebDriverWait(self.driver, 5)
            short_wait.until(EC.presence_of_element_located((By.XPATH, "//div[contains(text(), 'Showing 0 - 0 of 0')]")))
            logging.warning("No notifications found.")
            self.quit()
            return {"source_url": final_url, "status": "No notifications found", "notifications": []}

        except TimeoutException:
            logging.info("Results detected. Proceeding to download.")
            data = self._download_and_parse_excel()
            self.quit()
            
            if data is not None:
                return {"source_url": final_url, "status": "Success", "notifications": data}
            else:
                return {"source_url": final_url, "status": "Error during download", "notifications": []}
        except Exception as e:
            logging.error(f"An unexpected error occurred: {e}", exc_info=True)
            self.save_snapshot("eping_error")
            self.quit()
            return None

    def save_snapshot(self, label="snapshot"):
        os.makedirs('debug_snapshots', exist_ok=True)
        path = os.path.join('debug_snapshots', f"{label}_{datetime.now():%Y%m%d_%H%M%S}")
        self.driver.save_screenshot(f"{path}.png")

    def quit(self):
        if self.driver: self.driver.quit()

if __name__ == '__main__':
    CONFIG = {"hs_code": "8471", "target_market_id": "840"}
    scraper = EPingScraper(headless=False)
    try:
        data = scraper.scrape_notifications(CONFIG)
        if data:
            with open("eping_data.json", 'w', encoding='utf-8') as f:
                json.dump(data, f, ensure_ascii=False, indent=4, default=str)
            logging.info(f"SUCCESS: ePing data saved. Status: {data['status']}")
        else:
            logging.error("FAIL: ePing scraping could not be completed.")
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)