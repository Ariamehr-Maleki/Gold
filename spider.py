# --- FULLY REFACTORED AND COMPLETE SCRIPT ---

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
)
from selenium.webdriver.common.by import By
import pandas as pd
import time
import random
import logging
import os
import json
from datetime import datetime
import glob

# Basic logging configuration for clear output
try:
    from setlog import setlog
except ImportError:
    def setlog():
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        return logging.getLogger(__name__)

logging = setlog()


class TradeSpider(object):
    """
    Automates downloading and parsing of Trade Map data.
    Logs in, navigates, downloads an Excel file, and extracts data into a JSON structure.
    """
    DEFAULT_WAIT = 15

    def __init__(self, headless=False, driver_path='./geckodriver', wait_seconds=None):
        logging.info("TradeSpider: initializing")
        self.driver = None
        self.wait = None
        self.headless = headless
        self.driver_path = driver_path
        self.wait_seconds = wait_seconds or self.DEFAULT_WAIT
        
        # All downloads will now go into a 'downloads' subfolder.
        self.download_dir = os.path.join(os.getcwd(), "downloads")

    def set_driver(self):
        """Configures and launches the Firefox WebDriver for automatic downloads."""
        logging.info("Starting Firefox WebDriver")
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        
        # Automatically create the downloads folder if it doesn't exist.
        os.makedirs(self.download_dir, exist_ok=True)

        # Configure Firefox to automatically download files to our specified directory
        options.set_preference("browser.download.folderList", 2)  # 2 = use custom folder
        options.set_preference("browser.download.dir", self.download_dir)
        options.set_preference("browser.download.useDownloadDir", True)
        # This tells Firefox not to ask for confirmation for these file types
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", 
                               "application/vnd.ms-excel, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

        logging.info(f"WebDriver configured to automatically download files to: {self.download_dir}")
        
        # Standard anti-detection options
        options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0")
        
        service = Service(self.driver_path)
        self.driver = webdriver.Firefox(service=service, options=options)
        
        self.driver.set_page_load_timeout(60)
        self.wait = WebDriverWait(self.driver, self.wait_seconds)

    def _save_snapshot(self, label="snapshot"):
        """Saves a screenshot and HTML source for debugging."""
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
        """Waits for the browser's document.readyState to become 'complete'."""
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            return True
        except TimeoutException:
            logging.debug("Document readyState did not become 'complete' within timeout.")
            return False

    def _safe_click(self, by, locator, attempts=3, sleep_between=0.5):
        """A robust click method with retries."""
        for attempt in range(1, attempts + 1):
            try:
                el = self.wait.until(EC.element_to_be_clickable((by, locator)))
                el.click()
                return True
            except (StaleElementReferenceException, ElementClickInterceptedException):
                time.sleep(sleep_between)
        logging.error(f"_safe_click failed for {by}={locator} after {attempts} attempts.")
        return False

    def goto(self, url):
        """Navigates to a URL."""
        logging.info(f"Navigating to {url}")
        try:
            self.driver.get(url)
            return self._wait_for_ready_state()
        except Exception as e:
            logging.error(f"Error while navigating to {url}: {e}")
            return False

    def login(self, ac, pw):
        """Handles the entire login process, including CAPTCHA waits."""
        url = "https://www.trademap.org/Country_SelProduct_TS.aspx"
        if not self.goto(url): return False
        
        time.sleep(random.uniform(5.0, 8.0)) # Wait for page to settle
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

    def navigate_to_timeseries_page(self, product_code, country_id):
        """Navigates directly to the page with the time-series data table."""
        logging.info(f"Navigating to Time Series page for product {product_code}")
        url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm=1|{country_id}||||{product_code}|||4|1|1|2|2|1|2|1|1|1"
        return self.goto(url)

    def download_and_parse_excel(self, config):
        """The main method to automate downloading and parsing the Excel file."""
        logging.info("--- Starting Download and Parse Method ---")
        
        if not self.navigate_to_timeseries_page(config['hs_code'], config['target_market_id']):
            logging.error("Failed to navigate to the data page for download.")
            return None

        # Clean up any old excel files from the downloads directory
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

        # Robustly wait for the download to complete
        logging.info("Waiting for download to complete...")
        timeout = 60
        end_time = time.time() + timeout
        downloaded_file_path = None
        while time.time() < end_time:
            # Look for any .xls or .xlsx file, regardless of name
            excel_files = glob.glob(os.path.join(self.download_dir, "*.xls")) + glob.glob(os.path.join(self.download_dir, "*.xlsx"))
            if excel_files:
                latest_file = max(excel_files, key=os.path.getctime)
                # Check if the file is fully written by comparing size over a short interval
                initial_size = os.path.getsize(latest_file)
                time.sleep(1.5)
                final_size = os.path.getsize(latest_file)
                if initial_size == final_size and final_size > 0:
                    downloaded_file_path = latest_file
                    logging.info(f"File download confirmed: {downloaded_file_path}")
                    break
            
            # If a partial file exists, the download is still active, so we wait patiently
            if glob.glob(os.path.join(self.download_dir, "*.part")):
                end_time = time.time() + timeout  # Reset timer
            
            time.sleep(1)

        if not downloaded_file_path:
            logging.error("Download timed out. No Excel file was found.")
            return None
        
        return self._parse_downloaded_excel(downloaded_file_path, config)

    def _parse_downloaded_excel(self, file_path, config):
        """Parses the downloaded Excel file and extracts key data points."""
        logging.info(f"Parsing data from: {os.path.basename(file_path)}")
        try:
            df = pd.read_excel(file_path, header=4)
            # Make column access more robust by using integer location
            exporters_col = df.columns[0]
            latest_year_col = df.columns[1]
        except Exception as e:
            logging.error(f"Failed to read Excel file: {e}")
            return None

        data = { "market_size": {}, "market_growth": {"note": "Growth data unavailable in this export."}, "competition": {} }
        
        world_row = df[df[exporters_col] == 'World']
        your_country_row = df[df[exporters_col] == config['your_country']]
        
        world_imports_value = 0
        if not world_row.empty:
            world_imports_value = world_row[latest_year_col].iloc[0] * 1000
            data["market_size"]["target_market_imports_from_world_usd"] = world_imports_value

        if not your_country_row.empty:
            your_country_imports_value = your_country_row[latest_year_col].iloc[0] * 1000
            data["market_size"]["target_market_imports_from_your_country_usd"] = your_country_imports_value
            if world_imports_value > 0:
                share = (your_country_imports_value / world_imports_value) * 100
                data["market_size"]["your_country_share_in_target_market_imports_pct (calculated)"] = round(share, 2)
        
        top_3 = []
        competitors_df = df[df[exporters_col] != 'World'].head(3)
        for _, row in competitors_df.iterrows():
            value = row[latest_year_col] * 1000
            share = (value / world_imports_value) * 100 if world_imports_value > 0 else 0
            top_3.append({"name": row[exporters_col], "market_share_pct (calculated)": round(share, 2)})
        data["competition"]["top_3_suppliers"] = top_3
        
        logging.info("Successfully parsed data from the Excel file.")
        return data

    def close(self):
        """Closes the WebDriver instance safely."""
        try:
            if self.driver:
                self.driver.quit()
                logging.info('Driver closed successfully.')
        except Exception as e:
            logging.warning(f"Error closing driver: {e}")

def save_to_json(data, filename="factsheet_data.json"):
    """Saves the final data dictionary to a JSON file."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logging.info(f"Successfully saved all data to {filename}")

if __name__ == '__main__':
    # --- CONFIGURATION ---
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
            scraped_data = s.download_and_parse_excel(CONFIG)
            if scraped_data:
                factsheet_template.update(scraped_data)
                save_to_json(factsheet_template)
            else:
                logging.error("The script failed to get data. Please check the logs above.")
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
    finally:
        input("Press Enter to exit and close the browser...")
        s.close()