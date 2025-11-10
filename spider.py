from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
import pandas as pd
import time
import random
import logging
import os
import json
from datetime import datetime
import glob

# Basic logging configuration
try:
    from setlog import setlog
except ImportError:
    def setlog():
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        return logging.getLogger(__name__)

logging = setlog()


class TradeSpider(object):
    DEFAULT_WAIT = 15

    def __init__(self, headless=False, driver_path='./geckodriver', wait_seconds=None):
        logging.info("TradeSpider: initializing")
        self.driver = None
        self.wait = None
        self.headless = headless
        self.driver_path = driver_path
        self.wait_seconds = wait_seconds or self.DEFAULT_WAIT
        self.download_dir = os.getcwd()

    def set_driver(self):
        logging.info("Starting Firefox WebDriver")
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        
        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", self.download_dir)
        options.set_preference("browser.download.useDownloadDir", True)
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        # --- NEW --- Added a log message to confirm the download path
        logging.info(f"WebDriver configured to automatically download files to: {self.download_dir}")

        options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0")
        options.set_preference("dom.webdriver.enabled", False)
        
        service = Service(self.driver_path)
        self.driver = webdriver.Firefox(service=service, options=options)
        
        self.driver.set_page_load_timeout(60)
        self.wait = WebDriverWait(self.driver, self.wait_seconds)

    # ... (All other methods like _save_snapshot, _wait_for_ready_state, etc., remain the same) ...
    def _save_snapshot(self, label="snapshot"):
        os.makedirs('debug_snapshots', exist_ok=True)
        timestamp = int(time.time())
        html_file = f"debug_snapshots/{label}_{timestamp}.html"
        png_file = f"debug_snapshots/{label}_{timestamp}.png"
        try:
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
            self.driver.save_screenshot(png_file)
            logging.debug(f"Saved snapshot: {html_file}, {png_file}")
        except Exception as e:
            logging.warning(f"Failed to save snapshot: {e}")

    def _wait_for_ready_state(self, timeout=20):
        logging.debug("Waiting for document.readyState == 'complete'")
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            return True
        except TimeoutException:
            logging.debug("Document readyState did not become 'complete' within timeout")
            return False

    def _safe_click(self, by, locator, attempts=3, sleep_between=0.5):
        for attempt in range(1, attempts + 1):
            try:
                el = self.wait.until(EC.element_to_be_clickable((by, locator)))
                el.click()
                return True
            except Exception:
                time.sleep(sleep_between)
        logging.error(f"_safe_click failed for {by}={locator}")
        return False

    def goto(self, url):
        logging.info(f"Navigating to {url}")
        try:
            self.driver.get(url)
            self._wait_for_ready_state(timeout=30)
            return True
        except Exception as e:
            logging.error(f"Error while navigating to {url}: {e}")
            return False

    def login(self, ac, pw):
        url = "https://www.trademap.org/Country_SelProduct_TS.aspx"
        if not self.goto(url): return False
        time.sleep(random.uniform(5.0, 8.0))
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
            WebDriverWait(self.driver, 30).until(EC.any_of(
                EC.url_contains("Country_SelProduct_TS.aspx"),
                EC.url_contains("stCaptcha.aspx")
            ))
            if "stCaptcha.aspx" in self.driver.current_url:
                print("ACTION REQUIRED: Please solve the CAPTCHA in the browser window.")
                WebDriverWait(self.driver, 300).until_not(EC.url_contains("stCaptcha.aspx"))
            logging.info("Login successful!")
            return True
        except TimeoutException:
            logging.error("Failed to redirect after login or CAPTCHA timed out.")
            return False
    
    def navigate_to_main_page(self, product_code, country):
        logging.info(f"Navigating to Time Series page for product {product_code}")
        url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm=1|{country}||||{product_code}|||4|1|1|2|2|1|2|1|1|1"
        return self.goto(url)

    def download_and_parse_timeseries_excel(self, config):
        logging.info("--- Starting Download and Parse Method ---")
        
        if not self.navigate_to_main_page(config['hs_code'], config['target_market_id']):
            logging.error("Failed to navigate to the data page for download.")
            return None

        # --- MODIFIED SECTION ---
        # Using a more flexible file pattern and removing old files
        file_pattern = os.path.join(self.download_dir, "Export*.xlsx")
        for f in glob.glob(file_pattern):
            os.remove(f)
            logging.info(f"Removed old file: {f}")
        for f in glob.glob(file_pattern + ".part"): # Also remove partial files
            os.remove(f)
            logging.info(f"Removed old partial file: {f}")

        download_button_id = "ctl00_PageContent_GridViewPanelControl_ImageButton_ExportExcel"
        logging.info("Clicking the Excel download button...")
        if not self._safe_click(By.ID, download_button_id):
            logging.error("Could not click the download button.")
            return None

        # --- MODIFIED --- This is the new, more robust waiting logic
        logging.info(f"Waiting for download to complete...")
        timeout = 60  # Increased timeout to 60 seconds for safety
        end_time = time.time() + timeout
        downloaded_file_path = None
        while time.time() < end_time:
            # First, check if the final file exists
            xlsx_files = glob.glob(file_pattern)
            if xlsx_files:
                downloaded_file_path = xlsx_files[0]
                # Check if the file size is stable (not still being written)
                initial_size = os.path.getsize(downloaded_file_path)
                time.sleep(1) # Wait a second
                final_size = os.path.getsize(downloaded_file_path)
                if initial_size == final_size and final_size > 0:
                    logging.info(f"File download confirmed: {downloaded_file_path}")
                    break
            
            # If not, check if a .part file exists, which means we should keep waiting
            part_files = glob.glob(file_pattern + ".part")
            if part_files:
                logging.info(f"Download in progress, found partial file: {part_files[0]}")
                # Reset timeout slightly to be patient while download is active
                end_time = time.time() + timeout 
            
            time.sleep(1) # Check once per second

        if not downloaded_file_path:
            logging.error("Download timed out. No file was found or the file was empty.")
            return None
        
        time.sleep(2) # Extra pause to ensure the file is fully usable

        return self._parse_downloaded_excel(downloaded_file_path, config)

    def _parse_downloaded_excel(self, file_path, config):
        logging.info(f"Parsing data from: {file_path}")
        try:
            df = pd.read_excel(file_path, header=4)
            latest_year_column = df.columns[1]
        except Exception as e:
            logging.error(f"Failed to read Excel file: {e}")
            return None

        factsheet_data = { "market_size": {}, "market_growth": {"note": "Growth rates unavailable in this export."}, "competition": {} }
        world_row = df[df['Exporters'] == 'World']
        your_country_row = df[df['Exporters'] == config['your_country']]
        world_imports_value = 0
        if not world_row.empty:
            world_imports_value = world_row[latest_year_column].iloc[0] * 1000
            factsheet_data["market_size"]["target_market_imports_from_world_usd"] = world_imports_value
        if not your_country_row.empty:
            your_country_imports_value = your_country_row[latest_year_column].iloc[0] * 1000
            factsheet_data["market_size"]["target_market_imports_from_your_country_usd"] = your_country_imports_value
            if world_imports_value > 0:
                market_share = (your_country_imports_value / world_imports_value) * 100
                factsheet_data["market_size"]["your_country_share_in_target_market_imports_pct (calculated)"] = round(market_share, 2)
        top_3 = []
        for _, row in df[df['Exporters'] != 'World'].head(3).iterrows():
            value = row[latest_year_column] * 1000
            share = (value / world_imports_value) * 100 if world_imports_value > 0 else 0
            top_3.append({"name": row['Exporters'], "market_share_pct (calculated)": round(share, 2)})
        factsheet_data["competition"]["top_3_suppliers"] = top_3
        logging.info("Successfully parsed data from the Excel file.")
        return factsheet_data

    def close(self):
        if self.driver: self.driver.quit()

def save_to_json(data, filename="factsheet_data.json"):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logging.info(f"Successfully saved data to {filename}")

if __name__ == '__main__':
    CONFIG = {
        "product_name": "Fresh Apples", "hs_code": "080810",
        "your_country": "South Africa", "your_country_id": "710",
        "target_market": "United Kingdom", "target_market_id": "826",
    }
    factsheet_template = {
        "header": {"product": CONFIG["product_name"], "hs_code": CONFIG["hs_code"], "target_market": CONFIG["target_market"], "your_country": CONFIG["your_country"], "date": datetime.now().strftime("%B %Y")},
        "market_size": {}, "market_growth": {}, "competition": {}
    }
    ac = os.environ.get('TM_USERNAME') or input('Enter TradeMap username: ')
    pw = os.environ.get('TM_PASSWORD') or input('Enter TradeMap password: ')
    s = TradeSpider(headless=False)
    try:
        s.set_driver()
        if s.login(ac, pw):
            scraped_data = s.download_and_parse_timeseries_excel(CONFIG)
            if scraped_data:
                factsheet_template.update(scraped_data)
                save_to_json(factsheet_template)
            else:
                logging.error("Failed to get data using the download and parse method.")
    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}", exc_info=True)
    finally:
        input("Press Enter to exit and close the browser...")
        s.close()