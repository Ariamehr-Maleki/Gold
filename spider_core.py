# spider_core.py (Corrected Final Version with Robust Login Landmark)

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
)
from selenium.webdriver.common.by import By
import time
import random
import logging
import os
from datetime import datetime

# Basic logging configuration
try:
    from setlog import setlog
except ImportError:
    def setlog():
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        return logging.getLogger(__name__)

logging = setlog()


class TradeSpider(object):
    DEFAULT_WAIT = 20

    def __init__(self, headless=False, driver_path='./geckodriver.exe', wait_seconds=None):
        logging.info("TradeSpider: initializing")
        self.driver = None
        self.wait = None
        self.headless = headless
        self.driver_path = driver_path
        self.wait_seconds = wait_seconds or self.DEFAULT_WAIT
        self.download_dir = os.path.join(os.getcwd(), "downloads")
        self.archive_dir = os.path.join(os.getcwd(), "archived_downloads")

    def set_driver(self):
        logging.info("Starting Firefox WebDriver")
        options = Options()
        try:
            firefox_path = r"C:\Program Files\Mozilla Firefox\firefox.exe"
            options.binary_location = firefox_path
        except Exception:
            logging.error("Could not set Firefox binary location. Check the path.")

        if self.headless:
            options.add_argument("--headless")

        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)

        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", self.download_dir)
        options.set_preference("browser.download.useDownloadDir", True)
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", "text/plain, application/vnd.ms-excel, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0")

        service = Service(executable_path=self.driver_path)

        try:
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, self.wait_seconds)
            return True
        except WebDriverException as e:
            logging.error(f"WebDriver failed to start. Check geckodriver/Firefox compatibility.")
            logging.error(f"Original error: {e}")
            return False

    def _save_snapshot(self, label="snapshot"):
        debug_dir = 'debug_snapshots'
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = os.path.join(debug_dir, f"{label}_{timestamp}")
        try:
            self.driver.save_screenshot(f"{filename_base}.png")
            logging.info(f"Saved screenshot to {filename_base}.png")
            with open(f"{filename_base}.html", 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
            logging.info(f"Saved page source to {filename_base}.html")
        except Exception as e:
            logging.error(f"Failed to save snapshot: {e}")

    def _wait_for_ready_state(self, timeout=20):
        try:
            WebDriverWait(self.driver, timeout).until(lambda d: d.execute_script('return document.readyState') == 'complete')
            return True
        except TimeoutException:
            return False

    def _safe_click(self, by, locator, attempts=3, sleep_between=0.5):
        last_exception = None
        for attempt in range(attempts):
            try:
                el = self.wait.until(EC.element_to_be_clickable((by, locator)))
                self.driver.execute_script("arguments[0].scrollIntoView(true);", el)
                time.sleep(0.5)
                el.click()
                return True
            except Exception as e:
                last_exception = e
            time.sleep(sleep_between)
        logging.error(f"_safe_click failed for {by}={locator} after {attempts} attempts. Last exception: {last_exception}")
        return False

    def goto(self, url):
        max_attempts = 4
        for attempt in range(1, max_attempts + 1):
            logging.info(f"Navigating to {url} (Attempt {attempt}/{max_attempts})")
            try:
                self.driver.get(url)
                if not self._wait_for_ready_state():
                    logging.warning(f"Document did not report 'complete' on attempt {attempt}.")
                time.sleep(random.uniform(3.0, 5.0))
                current_url_base = self.driver.current_url.split('?')[0]
                target_url_base = url.split('?')[0]
                if current_url_base.endswith(target_url_base.split('/')[-1]):
                    logging.info(f"Successfully loaded URL after {attempt} attempt(s).")
                    return True
                else:
                    logging.warning(f"URL mismatch after navigation (attempt {attempt}). Current: {current_url_base}, Target: {target_url_base}")
            except Exception as e:
                logging.error(f"Error while navigating to {url} on attempt {attempt}: {e}")
        logging.error(f"Failed to navigate and confirm page load after {max_attempts} attempts.")
        return False

    def login(self, ac, pw):
        url = "https://www.trademap.org/Country_SelProduct_TS.aspx"
        if not self.goto(url): return False
        
        time.sleep(random.uniform(3.0, 5.0))
        if not self._safe_click(By.ID, 'ctl00_MenuControl_marmenu_login'): return False
        
        time.sleep(random.uniform(2, 4))
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, 'Username')))
            self.driver.find_element(By.ID, 'Username').send_keys(ac)
            self.driver.find_element(By.ID, 'Password').send_keys(pw)
            self._safe_click(By.XPATH, "//button[@name='button' and @value='login']")
        except Exception as e:
            logging.error(f"Error during login input: {e}")
            return False
            
        try:
            logging.info("Login submitted. Waiting for redirect...")
            
            WebDriverWait(self.driver, 30).until(EC.any_of(
                EC.url_contains("Country_SelProduct_TS.aspx"), 
                EC.url_contains("stCaptcha.aspx")
            ))

            if "stCaptcha.aspx" in self.driver.current_url:
                print("ACTION REQUIRED: Please solve the CAPTCHA in the browser window.")
                WebDriverWait(self.driver, 300).until(EC.any_of(
                    EC.url_contains("Country_SelProduct_TS.aspx"),
                    EC.url_contains("Index.aspx")
                ))
            
            logging.info("URL confirmed. Now waiting for page to be fully interactive...")

            WebDriverWait(self.driver, 15).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            logging.info("Browser reports document is 'complete'.")

            logging.info("Waiting for a landmark element to confirm successful login...")
            # --- FIX APPLIED HERE: ADDED A THIRD, MORE RELIABLE LANDMARK (THE LOGOUT BUTTON) ---
            self.wait.until(EC.any_of(
                EC.presence_of_element_located((By.ID, "ctl00_PageContent_Panel1")), # Landmark for Country_SelProduct_TS.aspx
                EC.presence_of_element_located((By.ID, "selectionMenu")),             # Landmark for Index.aspx
                EC.presence_of_element_located((By.ID, "ctl00_MenuControl_marmenu_logout")) # Universal landmark
            ))
            # --- END OF FIX ---
            logging.info("Landmark element found. Login is fully complete and verified.")
            
            time.sleep(1)

            logging.info("Login successful and page is confirmed to be loaded!")
            return True

        except TimeoutException:
            logging.error("Verification failed. The script timed out waiting for the page after login.")
            self._save_snapshot("post_login_verification_failed")
            return False