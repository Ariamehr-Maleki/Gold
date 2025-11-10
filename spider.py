# --- FINAL SCRIPT WITH ENHANCED JAVASCRIPT CLICK FALLBACK ---

from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    WebDriverException,
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
import re

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
        """Saves a screenshot and the page source for debugging."""
        debug_dir = 'debug_snapshots'
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = os.path.join(debug_dir, f"{label}_{timestamp}")
    
        # Save Screenshot
        png_path = f"{filename_base}.png"
        try:
            self.driver.save_screenshot(png_path)
            logging.info(f"Saved screenshot to {png_path}")
        except Exception as e:
            logging.error(f"Failed to save screenshot: {e}")
    
        # Save Page Source
        html_path = f"{filename_base}.html"
        try:
            with open(html_path, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
            logging.info(f"Saved page source to {html_path}")
        except Exception as e:
            logging.error(f"Failed to save page source: {e}")


    def _wait_for_ready_state(self, timeout=20):
        try:
            WebDriverWait(self.driver, timeout).until(lambda d: d.execute_script('return document.readyState') == 'complete')
            return True
        except TimeoutException:
            return False

    def _safe_click(self, by, locator, attempts=3, sleep_between=0.5):
        """A more robust click method that falls back to JavaScript if the standard click is intercepted."""
        last_exception = None
        for attempt in range(attempts):
            try:
                el = self.wait.until(EC.presence_of_element_located((by, locator)))
                logging.debug(f"Attempting standard click on {by}={locator}")
                el.click()
                return True
            except (StaleElementReferenceException, ElementClickInterceptedException) as e:
                logging.warning(f"Standard click failed: {type(e).__name__}. Attempting JavaScript click.")
                try:
                    self.driver.execute_script("arguments[0].click();", el)
                    return True
                except Exception as e2:
                    logging.error(f"JavaScript click also failed: {e2}")
                    last_exception = e2
            except Exception as e:
                last_exception = e

            time.sleep(sleep_between)
        
        logging.error(f"_safe_click failed for {by}={locator} after {attempts} attempts. Last exception: {last_exception}")
        return False

    def goto(self, url):
        logging.info(f"Navigating to {url}")
        try:
            self.driver.get(url)
            return self._wait_for_ready_state()
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
            WebDriverWait(self.driver, 30).until(EC.any_of(EC.url_contains("Country_SelProduct_TS.aspx"), EC.url_contains("stCaptcha.aspx")))
            if "stCaptcha.aspx" in self.driver.current_url:
                print("ACTION REQUIRED: Please solve the CAPTCHA in the browser window.")
                WebDriverWait(self.driver, 300).until_not(EC.url_contains("stCaptcha.aspx"))
            logging.info("Login successful!")
            return True
        except TimeoutException:
            logging.error("Failed to redirect after login or CAPTCHA timed out.")
            return False

    def navigate_to_timeseries_page(self, product_code, country_id):
        logging.info(f"Navigating to Time Series page for product {product_code}")
        url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm=1|{country_id}||||{product_code}|||4|1|1|2|2|1|2|1|1|1"
        if not self.goto(url):
            return False
        time.sleep(3) # Allow a moment for the page to settle
        return True

    def download_and_parse_data(self, config):
        logging.info("--- Starting Download and Parse Method (TXT) ---")
        if not self.navigate_to_timeseries_page(config['hs_code'], config['target_market_id']):
            return None
        
        try:
            # --- FIXED --- Updated waiting strategy for new page structure
            logging.info("Waiting for the data table container to be visible...")
            data_container_id = "div_Gvpanelc" # This div holds all the table controls and the table itself
            self.wait.until(EC.visibility_of_element_located((By.ID, data_container_id)))
            
            logging.info("Container found. Now waiting for the data table itself...")
            # --- FIXED --- The ID of the table has changed from GridView_grd to MyGridView1
            table_id = "ctl00_PageContent_MyGridView1"
            self.wait.until(EC.visibility_of_element_located((By.ID, table_id)))
            logging.info("Data table found. Page is ready for download.")

        except TimeoutException:
            logging.error("Data table did not load. No data available for this selection or page structure changed.")
            self._save_snapshot("no_data_table_found")
            return None

        logging.info(f"Cleaning old text files from '{self.download_dir}'...")
        for f in glob.glob(os.path.join(self.download_dir, "*.txt*")): os.remove(f)

        download_button_id = "ctl00_PageContent_GridViewPanelControl_ImageButton_Text"
        if not self._safe_click(By.ID, download_button_id):
            return None

        logging.info("Waiting for download to complete...")
        timeout, downloaded_file_path = 60, None
        end_time = time.time() + timeout
        while time.time() < end_time:
            text_files = glob.glob(os.path.join(self.download_dir, "*.txt"))
            if text_files:
                latest_file = max(text_files, key=os.path.getctime)
                initial_size, _ = os.path.getsize(latest_file), time.sleep(1.5)
                if initial_size == os.path.getsize(latest_file) and initial_size > 0:
                    downloaded_file_path = latest_file
                    logging.info(f"File download confirmed: {downloaded_file_path}")
                    break
            if glob.glob(os.path.join(self.download_dir, "*.part")): end_time = time.time() + timeout
            time.sleep(1)

        if not downloaded_file_path:
            logging.error("Download timed out. No .txt file was found.")
            return None
        
        return self._parse_downloaded_txt(downloaded_file_path, config)

    def _parse_downloaded_txt(self, file_path, config):
        logging.info(f"Parsing data from TXT file: {os.path.basename(file_path)}")
        try:
            df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig')
            df.columns = [col.strip().strip('"') for col in df.columns]
            df = df.apply(lambda x: x.str.strip().str.strip('"') if x.dtype == "object" else x)
            value_cols = [col for col in df.columns if 'Imported value' in col]
            for col in value_cols: df[col] = pd.to_numeric(df[col], errors='coerce')
            df.fillna(0, inplace=True)

            latest_year_col = None
            latest_year = 0
            for col in value_cols:
                match = re.search(r'(\d{4})', col)
                if match:
                    year = int(match.group(1))
                    if year > latest_year:
                        latest_year = year
                        latest_year_col = col
            
            if not latest_year_col:
                logging.error("Could not determine the latest year's column from the file.")
                return None

            logging.info(f"Identified the latest year for analysis as {latest_year} ('{latest_year_col}')")
            exporters_col = df.columns[0]

        except Exception as e:
            logging.error(f"Failed to read file with pandas.read_csv: {e}")
            return None
            
        data, world_imports_value = {"market_size": {}, "competition": {}}, 0
        world_row = df[df[exporters_col] == 'World']
        if not world_row.empty:
            world_imports_value = world_row[latest_year_col].iloc[0] * 1000
            data["market_size"]["target_market_imports_from_world_usd"] = int(world_imports_value)
            
        your_country_row = df[df[exporters_col] == config['your_country']]
        if not your_country_row.empty:
            your_country_imports_value = your_country_row[latest_year_col].iloc[0] * 1000
            data["market_size"]["target_market_imports_from_your_country_usd"] = int(your_country_imports_value)
            if world_imports_value > 0:
                data["market_size"]["your_country_share_in_target_market_imports_pct (calculated)"] = round((your_country_imports_value / world_imports_value) * 100, 2)
        
        top_3 = []
        top_exporters_df = df[df[exporters_col] != 'World'].sort_values(by=latest_year_col, ascending=False)
        for _, row in top_exporters_df.head(3).iterrows():
            value = row[latest_year_col] * 1000
            top_3.append({
                "name": row[exporters_col], 
                "market_share_pct (calculated)": round((value / world_imports_value) * 100 if world_imports_value > 0 else 0, 2)
            })
        data["competition"]["top_3_suppliers"] = top_3
        logging.info("Successfully parsed data from the TXT file.")
        return data

    def close(self):
        if self.driver: self.driver.quit()

def save_to_json(data, filename="factsheet_data.json"):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logging.info(f"Successfully saved all data to {filename}")

if __name__ == '__main__':
    CONFIG = { "product_name": "All Products", "hs_code": "TOTAL", "your_country": "South Africa", "target_market": "Germany", "target_market_id": "276",}
    factsheet_template = {"header": {**CONFIG, "date": datetime.now().strftime("%B %Y")}, "market_size": {}, "competition": {}}
    ac, pw = os.environ.get('TM_USERNAME') or input('Enter TM username: '), os.environ.get('TM_PASSWORD') or input('Enter TM password: ')
    s = TradeSpider(headless=False, driver_path=r".\geckodriver.exe")
    try:
        if s.set_driver():
            if s.login(ac, pw):
                scraped_data = s.download_and_parse_data(CONFIG)
                if scraped_data:
                    factsheet_template.update(scraped_data)
                    save_to_json(factsheet_template)
                else:
                    logging.error("Script failed to get data. Check logs.")
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
    finally:
        if s and s.driver:
            input("Press Enter to exit and close the browser...")
            s.close()
        else:
            print("Script finished or encountered an error before browser started.")