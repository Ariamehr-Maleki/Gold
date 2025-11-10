# --- FINAL SCRIPT WITH ENHANCED PARSING, REVERSE CONFIG, AND ROBUST COMPANY SAMPLING ---

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
    NoSuchElementException,
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

    def navigate_to_timeseries_page(self, product_code, country_id, trade_flow='I'):
        logging.info(f"Navigating to Time Series page for product {product_code} (Flow: {trade_flow})")
        trade_flow_code = '1' if trade_flow == 'I' else '2'
        url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm=1|{country_id}||||{product_code}|||2|1|1|{trade_flow_code}|2|1|2|1|1|1"
        if not self.goto(url): return False
        time.sleep(3)
        return True

    def navigate_to_companies_page(self, product_code, country_id, trade_flow='I'):
        logging.info(f"Navigating to Companies page for product {product_code} (Flow: {trade_flow})")
        trade_flow_code = '1' if trade_flow == 'I' else '2'
        url = f"https://www.trademap.org/CompaniesList.aspx?nvpm=1|{country_id}||||{product_code}|||4|1|1|{trade_flow_code}|3|1|1|1|1|4"
        if not self.goto(url): return False
        time.sleep(3)
        return True

    def download_and_parse_timeseries_data(self, config, trade_flow='I'):
        logging.info(f"--- Starting Download and Parse for Time Series (Flow: {trade_flow}) ---")
        country_id = config['target_market_id'] if trade_flow == 'I' else config['your_country_id']
        if not self.navigate_to_timeseries_page(config['hs_code'], country_id, trade_flow): return None
        try:
            self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
            logging.info("Data table found. Page is ready for download.")
        except TimeoutException:
            logging.error("Data table did not load for Time Series data.")
            self._save_snapshot(f"no_timeseries_table_found_{trade_flow}")
            return None
        downloaded_file_path = self._download_file()
        return self._parse_timeseries_txt(downloaded_file_path, config) if downloaded_file_path else None

    def download_and_parse_company_sample_data(self, config, trade_flow='I'):
        logging.info(f"--- Starting Download for a SAMPLE of Company Data ---")
        if not self.navigate_to_companies_page(config['hs_code'], config['target_market_id'], trade_flow):
            return []
        try:
            category_links_xpath = "//table[@id='ctl00_PageContent_MyGridView1']//a[contains(@id, 'LinkButton_CompanyProduct')]"
            try:
                WebDriverWait(self.driver, 5).until(EC.presence_of_element_located((By.XPATH, category_links_xpath)))
                is_intermediate_page = True
            except TimeoutException:
                is_intermediate_page = False

            if is_intermediate_page:
                first_link_el = self.wait.until(EC.element_to_be_clickable((By.XPATH, category_links_xpath)))
                category_name = first_link_el.text.strip()
                logging.info(f"Found product categories. Clicking the first one to get a sample: '{category_name}'")
                # use safe click and wait a little
                self.driver.execute_script("arguments[0].scrollIntoView(true);", first_link_el)
                time.sleep(random.uniform(0.8, 1.5))
                if not self._safe_click(By.XPATH, category_links_xpath):
                    logging.error("Failed to click first category link.")
                    return []
                # let the page settle
                time.sleep(random.uniform(1.5, 3.0))
            else:
                logging.info("No sub-categories found. Proceeding to download directly.")

            download_button_xpath = "//input[@type='image' and @title='Text file']"
            logging.info("Company list page loaded. Waiting for download button to be ready.")
            self.wait.until(EC.element_to_be_clickable((By.XPATH, download_button_xpath)))

            logging.info("Download button is ready. Downloading data.")
            # Verify content contains the target market name (case-insensitive)
            expected_keywords = [config.get('target_market'), config.get('your_country')]
            downloaded_file_path = self._download_file(expected_keywords=[k for k in expected_keywords if k], max_attempts=4, click_xpath=download_button_xpath)

            if downloaded_file_path:
                parsed = self._parse_company_txt(downloaded_file_path)
                if parsed:
                    return parsed
                else:
                    self._save_snapshot("company_parse_empty")
                    return []
            else:
                self._save_snapshot("company_download_failed")
                return []
        except Exception as e:
            logging.error(f"An error occurred while getting the company data sample: {e}")
            self._save_snapshot("company_sample_error")
            return []

    # --- CORRECTED _download_file FUNCTION ---
    def _download_file(self, expected_keywords: list | None = None, max_attempts: int = 3, click_xpath: str = "//input[@type='image' and @title='Text file']"):
        logging.info(f"Cleaning old text files from '{self.download_dir}'...")
        for f in glob.glob(os.path.join(self.download_dir, "*.txt*")):
            try:
                os.remove(f)
            except Exception:
                pass

        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            logging.info(f"Download attempt {attempt}/{max_attempts}...")
            if not self._safe_click(By.XPATH, click_xpath):
                logging.error("Failed to click download button.")
                return None

            timeout = 60
            end_time = time.time() + timeout
            downloaded_file_path = None
            while time.time() < end_time:
                text_files = glob.glob(os.path.join(self.download_dir, "*.txt"))
                if text_files:
                    latest_file = max(text_files, key=os.path.getctime)
                    # ensure file has some content
                    time.sleep(1.0)
                    try:
                        if os.path.getsize(latest_file) > 0:
                            downloaded_file_path = latest_file
                            logging.info(f"File download confirmed: {downloaded_file_path}")
                            break
                    except Exception as e:
                        logging.debug(f"Error checking file size: {e}")
                time.sleep(0.5)

            if not downloaded_file_path:
                logging.error("Download timed out. No .txt file was found.")
                continue

            # If no expected keywords requested, accept the file
            if not expected_keywords:
                return downloaded_file_path

            # Verify file content contains at least one expected keyword (case-insensitive)
            try:
                with open(downloaded_file_path, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read(5000)  # read first chunk only
                found = False
                for kw in expected_keywords:
                    if kw and kw.lower() in content.lower():
                        found = True
                        break
                if found:
                    logging.info("Downloaded file verified contains expected keywords.")
                    return downloaded_file_path
                else:
                    logging.warning(f"Downloaded file did not contain expected keywords {expected_keywords}. Deleting and retrying.")
                    try:
                        os.remove(downloaded_file_path)
                    except Exception:
                        pass
                    time.sleep(random.uniform(1.0, 2.0))
                    continue
            except Exception as e:
                logging.error(f"Error verifying downloaded file: {e}")
                try:
                    os.remove(downloaded_file_path)
                except Exception:
                    pass
                continue

        logging.error("All download attempts failed or verification didn't pass.")
        return None

    def _parse_timeseries_txt(self, file_path, config):
        # This function remains unchanged as it is already robust.
        logging.info(f"Parsing Time Series data from TXT file: {os.path.basename(file_path)}")
        try:
            df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig')
            df.columns = [col.strip().strip('"') for col in df.columns]
            df = df.apply(lambda x: x.str.strip().str.strip('"') if x.dtype == "object" else x)
            value_cols = sorted([col for col in df.columns if ' value in ' in col])
            if len(value_cols) < 2: return {}
            for col in value_cols: df[col] = pd.to_numeric(df[col], errors='coerce')
            df.fillna(0, inplace=True)
            latest_year_col, prior_year_col = value_cols[-1], value_cols[-2]
            start_year_col = value_cols[-5] if len(value_cols) >= 5 else value_cols[0]
            data_source_col = df.columns[0]
            num_periods = int(re.search(r'(\d{4})', latest_year_col).group(1)) - int(re.search(r'(\d{4})', start_year_col).group(1))
        except Exception: return {}
        def calculate_cagr(end, start, periods): return round(((end / start) ** (1 / periods) - 1) * 100, 2) if start > 0 and periods > 0 else 0.0
        data = {}
        world_row = df[df[data_source_col] == 'World']
        if not world_row.empty:
            world_latest = world_row[latest_year_col].iloc[0]
            data["total_value_usd"] = int(world_latest * 1000)
            if 'Imported value in' in latest_year_col:
                data.update({
                    "market_growth_last_year_pct": round((world_latest - world_row[prior_year_col].iloc[0]) / world_row[prior_year_col].iloc[0] * 100 if world_row[prior_year_col].iloc[0] > 0 else 0, 2),
                    "market_growth_cagr_pct": calculate_cagr(world_latest, world_row[start_year_col].iloc[0], num_periods)
                })
        your_country_row = df[df[data_source_col] == config['your_country']]
        if not your_country_row.empty:
            yc_latest = your_country_row[latest_year_col].iloc[0]
            data.update({
                "imports_from_your_country_usd": int(yc_latest * 1000),
                "your_country_share_in_target_market_imports_pct": round((yc_latest / world_row[latest_year_col].iloc[0]) * 100 if not world_row.empty and world_row[latest_year_col].iloc[0] > 0 else 0, 2),
                "your_country_growth_cagr_pct": calculate_cagr(yc_latest, your_country_row[start_year_col].iloc[0], num_periods)
            })
        competitors_df = df[df[data_source_col] != 'World']
        top_10 = competitors_df.sort_values(by=latest_year_col, ascending=False).head(10)
        top_3 = [{"name": r[data_source_col], "market_share_pct": round((r[latest_year_col] / world_row[latest_year_col].iloc[0]) * 100 if not world_row.empty and world_row[latest_year_col].iloc[0] > 0 else 0, 2)} for i, r in top_10.head(3).iterrows()]
        gaining = [r[data_source_col] for i, r in top_10.iterrows() if (r[latest_year_col] / (world_row[latest_year_col].iloc[0] or 1)) > (r[start_year_col] / (world_row[start_year_col].iloc[0] or 1))]
        data["competition"] = {"top_3_suppliers": top_3, "gaining_suppliers_top_10": gaining}
        logging.info("Successfully parsed Time Series data.")
        return data

    def _parse_company_txt(self, file_path):
        logging.info(f"Parsing Company data from TXT file: {os.path.basename(file_path)}")
        try:
            # Read forcing string dtype (prevents dtype issues and fillna warnings)
            df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig', dtype=str).fillna('N/A')
            # normalize column names
            original_cols = list(df.columns)
            cols_map = {c: c.strip().lower() for c in original_cols}
            df.columns = [c.strip() for c in original_cols]  # keep original stripped for display

            lowered = [c.strip().lower() for c in original_cols]

            # helper to find a column by checking substrings & exact matches
            def find_col(candidates):
                for cand in candidates:
                    for i, c in enumerate(lowered):
                        if cand == c or cand in c or c in cand:
                            return original_cols[i]
                return None

            name_col = find_col(['importers', 'company name', 'company', 'exporters', 'importer', 'exporter', 'name'])
            city_col = find_col(['city', 'town'])
            website_col = find_col(['website', 'web site', 'web', 'url', 'site'])

            if not name_col:
                logging.error(f"No valid company column found. Columns available: {original_cols}")
                return []

            # Ensure the three columns exist in df (fill missing with 'N/A')
            if name_col not in df.columns:
                df[name_col] = 'N/A'
            if city_col and city_col not in df.columns:
                df[city_col] = 'N/A'
            if website_col and website_col not in df.columns:
                df[website_col] = 'N/A'

            # build result records
            records = []
            for _, row in df.iterrows():
                rec = {
                    "name": str(row.get(name_col, 'N/A')).strip(),
                    "city": str(row.get(city_col, 'N/A')).strip() if city_col else 'N/A',
                    "website": str(row.get(website_col, 'N/A')).strip() if website_col else 'N/A'
                }
                records.append(rec)
            return records
        except Exception as e:
            logging.error(f"Could not parse company file. Error: {e}")
            return []



def save_to_json(data, filename="final_factsheet_data.json"):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logging.info(f"Successfully saved all combined data to {filename}")

if __name__ == '__main__':
    CONFIG = {
        "product_name": "Electrical machinery and equipment", "hs_code": "85",
        "your_country": "South Africa", "your_country_id": "710",
        "target_market": "Germany", "target_market_id": "276",
    }
    
    final_data = {"header": {**CONFIG, "date": datetime.now().strftime("%B %Y")}}
    
    ac, pw = os.environ.get('TM_USERNAME') or input('Enter TM username: '), os.environ.get('TM_PASSWORD') or input('Enter TM password: ')
    s = TradeSpider(headless=False, driver_path=r".\geckodriver.exe")
    
    try:
        if s.set_driver() and s.login(ac, pw):
            # --- TASK 1: Get Target Market's Import Data ---
            logging.info("===== TASK 1 of 3: SCRAPING TARGET MARKET IMPORTS =====")
            market_data = s.download_and_parse_timeseries_data(CONFIG, trade_flow='I')
            if market_data:
                final_data["market_size"] = {"target_market_imports_from_world_usd": market_data.pop("total_value_usd", None)}
                final_data["market_growth"] = {"target_market_growth_last_year_pct": market_data.pop("market_growth_last_year_pct", None), "target_market_growth_cagr_pct": market_data.pop("market_growth_cagr_pct", None)}
                final_data["your_country_performance"] = market_data
                final_data["competition"] = market_data.pop("competition", None)
            
            # --- TASK 2: Get Your Country's Total Export Data ---
            logging.info("===== TASK 2 of 3: SCRAPING YOUR COUNTRY'S EXPORTS =====")
            export_data = s.download_and_parse_timeseries_data(CONFIG, trade_flow='E')
            if export_data and "your_country_performance" in final_data:
                final_data["your_country_performance"]["your_country_total_exports_to_world_usd"] = export_data.get("total_value_usd")

            # --- TASK 3: Get Company Data from Target Market ---
            logging.info("===== TASK 3 of 3: SCRAPING COMPANY DATA SAMPLE =====")
            company_data = s.download_and_parse_company_sample_data(CONFIG, trade_flow='I')
            if company_data:
                final_data["business_partners_sample"] = company_data
            
            save_to_json(final_data)

    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
    finally:
        if s and s.driver:
            input("Press Enter to exit and close the browser...")
            s.close()
        else:
            print("Script finished or encountered an error before browser started.")