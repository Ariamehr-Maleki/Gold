# support/spider_core.py (Fixed: Correct Verification Elements)

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    NoSuchElementException,
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
        target_page_filename = url.split('?')[0].split('/')[-1]
        
        for attempt in range(1, max_attempts + 1):
            logging.info(f"Navigating to {url} (Attempt {attempt}/{max_attempts})")
            try:
                self.driver.get(url)
                WebDriverWait(self.driver, 15).until(
                    EC.url_contains(target_page_filename)
                )
                self._wait_for_ready_state(10)
                logging.info(f"Successfully loaded and verified URL for '{target_page_filename}' on attempt {attempt}.")
                return True
            except TimeoutException:
                logging.warning(
                    f"Navigation timed out on attempt {attempt}. "
                    f"Expected URL containing '{target_page_filename}', but current URL is '{self.driver.current_url}'. Retrying..."
                )
            except Exception as e:
                logging.error(f"An unexpected error occurred during navigation on attempt {attempt}: {e}")
        
        logging.error(f"Failed to navigate to '{target_page_filename}' after {max_attempts} attempts.")
        self._save_snapshot(f"goto_failed_{target_page_filename}")
        return False

    def login(self, ac, pw):
        url = "https://www.trademap.org/Country_SelProduct_TS.aspx"
        if not self.goto(url): return False
        
        time.sleep(random.uniform(2.0, 4.0))
        if not self._safe_click(By.ID, 'ctl00_MenuControl_marmenu_login'): return False
        
        time.sleep(random.uniform(2, 4))
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, 'Username')))
            self.driver.find_element(By.ID, 'Username').send_keys(ac)
            self.driver.find_element(By.ID, 'Password').send_keys(pw)
            self._safe_click(By.XPATH, "//button[@name='button' and @value='login']")
        except Exception as e:
            logging.error(f"Error during login input: {e}")
            self._save_snapshot("login_input_fail")
            return False
            
        try:
            logging.info("Login submitted. Waiting for outcome (Success, CAPTCHA, or Failure)...")
            logging.debug(f"[DEBUG] Current URL before outcome wait: {self.driver.current_url}")
            
            username_input_locator = (By.ID, "Username")
            login_error_locator = (By.ID, "ValidationSummary1") 
            
            # --- ATOMIC WAIT ---
            # 1. Username input disappears (Success)
            # 2. Captcha URL appears (Captcha)
            # 3. Error element appears (Failure)
            WebDriverWait(self.driver, 20).until(EC.any_of(
                EC.invisibility_of_element_located(username_input_locator),
                EC.url_contains("stCaptcha.aspx"),
                EC.presence_of_element_located(login_error_locator)
            ))

            # --- OUTCOME ANALYSIS ---
            current_url = self.driver.current_url
            logging.info(f"[DEBUG] Outcome detection finished. Current URL: {current_url}")

            # 1. Check for Failure
            try:
                error_element = self.driver.find_element(*login_error_locator)
                if error_element.is_displayed():
                    error_text = error_element.text.strip().replace('\n', ' ')
                    logging.error(f"LOGIN FAILED. Site reported an error: '{error_text}'")
                    self._save_snapshot("login_explicit_fail")
                    return False
            except NoSuchElementException:
                pass 

            # 2. Check for CAPTCHA
            if "stCaptcha.aspx" in current_url:
                logging.warning("ACTION REQUIRED: CAPTCHA detected. Please solve it. Waiting up to 5 minutes.")
                WebDriverWait(self.driver, 300).until_not(EC.url_contains("stCaptcha.aspx"))
                logging.info("CAPTCHA page is gone. Verifying final destination...")
            
            # 3. Success Path
            else:
                 logging.info("[DEBUG] No CAPTCHA found and Login form disappeared. Proceeding as successful login.")

            # --- FINAL VERIFICATION (Fixed using IDs from your HTML) ---
            logging.info("Verifying destination page is fully loaded and interactive...")
            
            self.wait.until(EC.any_of(
                # The main data table
                EC.presence_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")),
                # The user name label (visible when logged in)
                EC.presence_of_element_located((By.ID, "ctl00_MenuControl_Label_Login")),
                # The product dropdown
                EC.presence_of_element_located((By.ID, "ctl00_NavigationControl_DropDownList_Product"))
            ))

            self._wait_for_ready_state(5)
            logging.info("Login process complete and destination page is verified.")
            return True

        except TimeoutException:
            logging.error("Verification failed. Timed out waiting for page elements (MyGridView1, Label_Login, etc). Saving snapshot...")
            logging.error(f"[DEBUG] Final stuck URL: {self.driver.current_url}")
            self._save_snapshot("post_login_timeout_or_fail")
            return False
        except Exception as e:
            logging.error(f"An unexpected error occurred during login verification: {e}")
            self._save_snapshot("post_login_unexpected_error")
            return False