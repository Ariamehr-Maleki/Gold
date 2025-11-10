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
        # --- MODIFIED --- All downloads will now go into a 'downloads' subfolder.
        self.download_dir = os.path.join(os.getcwd(), "downloads")

    def set_driver(self):
        logging.info("Starting Firefox WebDriver")
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        
        # --- MODIFIED --- Automatically create the downloads folder if it doesn't exist.
        os.makedirs(self.download_dir, exist_ok=True)

        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", self.download_dir)
        options.set_preference("browser.download.useDownloadDir", True)
        # This will handle both .xls and .xlsx file types
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", "application/vnd.ms-excel, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        logging.info(f"WebDriver configured to automatically download files to: {self.download_dir}")

        options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0")
        
        service = Service(self.driver_path)
        self.driver = webdriver.Firefox(service=service, options=options)
        
        self.driver.set_page_load_timeout(60)
        self.wait = WebDriverWait(self.driver, self.wait_seconds)

    # ... (login, goto, and other helper methods remain the same) ...
    def _save_snapshot(self, label="snapshot"):
        os.makedirs('debug_snapshots', exist_ok=True)
        # ... (rest of the method is unchanged)

    def _wait_for_ready_state(self, timeout=20):
        # ... (method is unchanged)
        return True

    def _safe_click(self, by, locator, attempts=3, sleep_between=0.5):
        # ... (method is unchanged)
        return False

    def goto(self, url):
        # ... (method is unchanged)
        return True

    def login(self, ac, pw):
        # ... (method is unchanged)
        return True
    
    def navigate_to_main_page(self, product_code, country):
        logging.info(f"Navigating to Time Series page for product {product_code}")
        url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm=1|{country}||||{product_code}|||4|1|1|2|2|1|2|1|1|1"
        return self.goto(url)

    def download_and_parse_timeseries_excel(self, config):
        logging.info("--- Starting Download and Parse Method ---")
        
        if not self.navigate_to_main_page(config['hs_code'], config['target_market_id']):
            logging.error("Failed to navigate to the data page for download.")
            return None

        # --- MODIFIED --- More flexible cleanup for ANY .xls or .xlsx file
        logging.info(f"Cleaning old Excel files from '{self.download_dir}'...")
        for f in glob.glob(os.path.join(self.download_dir, "*.xls*")):
            os.remove(f)
        for f in glob.glob(os.path.join(self.download_dir, "*.xls*.part")):
            os.remove(f)

        download_button_id = "ctl00_PageContent_GridViewPanelControl_ImageButton_ExportExcel"
        logging.info("Clicking the Excel download button...")
        if not self._safe_click(By.ID, download_button_id):
            logging.error("Could not click the download button.")
            return None

        # --- MODIFIED --- More flexible waiting logic that looks for ANY Excel file
        logging.info("Waiting for download to complete...")
        timeout = 60
        end_time = time.time() + timeout
        downloaded_file_path = None
        while time.time() < end_time:
            # Look for both .xls and .xlsx files
            excel_files = glob.glob(os.path.join(self.download_dir, "*.xls")) + glob.glob(os.path.join(self.download_dir, "*.xlsx"))
            if excel_files:
                # File has appeared, now check if it's finished writing
                latest_file = max(excel_files, key=os.path.getctime) # Get the newest file
                initial_size = os.path.getsize(latest_file)
                time.sleep(1.5) # Wait a bit longer
                final_size = os.path.getsize(latest_file)
                
                if initial_size == final_size and final_size > 0:
                    downloaded_file_path = latest_file
                    logging.info(f"File download confirmed: {downloaded_file_path}")
                    break
            
            # Keep waiting if a .part file exists
            part_files = glob.glob(os.path.join(self.download_dir, "*.part"))
            if part_files:
                end_time = time.time() + timeout # Reset timer if download is active
            
            time.sleep(1)

        if not downloaded_file_path:
            logging.error("Download timed out. No Excel file was found in the downloads directory.")
            return None
        
        return self._parse_downloaded_excel(downloaded_file_path, config)

    def _parse_downloaded_excel(self, file_path, config):
        logging.info(f"Parsing data from: {file_path}")
        try:
            # Pandas can read both .xls and .xlsx files with the same engine
            df = pd.read_excel(file_path, header=4)
            latest_year_column = df.columns[1]
        except Exception as e:
            logging.error(f"Failed to read Excel file: {e}")
            return None

        factsheet_data = { "market_size": {}, "market_growth": {"note": "Growth rates unavailable in this export."}, "competition": {} }
        world_row = df[df.iloc[:, 0] == 'World']
        your_country_row = df[df.iloc[:, 0] == config['your_country']]
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
        for _, row in df[df.iloc[:, 0] != 'World'].head(3).iterrows():
            value = row[latest_year_column].iloc[0] * 1000
            share = (value / world_imports_value) * 100 if world_imports_value > 0 else 0
            top_3.append({"name": row.iloc[0], "market_share_pct (calculated)": round(share, 2)})
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