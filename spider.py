# tradespider_trademap_complete.py
# Enhanced TradeSpider: extract as much as possible from TradeMap TXT tables
# - Parses value, quantity and unit-value columns from time series files
# - Returns full timeseries arrays for World and Your Country (years, values, quantities, unit_values)
# - Builds a detailed suppliers list with unit values and growths where available
# - Improved company TXT parsing to capture phone/email/address when present

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
import math

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
            # 2. Wait for the product clarification table to be visible.
            clarification_table = (By.ID, "ctl00_PageContent_MyGridView1")
            logging.info("Waiting for the product clarification table to appear...")
            self.wait.until(EC.visibility_of_element_located(clarification_table))
            logging.info("Clarification table found.")

            # 2a. Find product anchors (ignore header anchors). Prefer anchors with id containing 'LinkButton_CompanyProduct'
            product_anchors = self.driver.find_elements(By.XPATH, "//a[contains(@id,'LinkButton_CompanyProduct')]")

            if not product_anchors:
                # Fallback: find anchors in data rows (ignore header <th>)
                product_anchors = self.driver.find_elements(By.XPATH, "//table[@id='ctl00_PageContent_MyGridView1']//tr[td]//a")

            if not product_anchors:
                logging.error("No product anchors found on clarification page.")
                self._save_snapshot("company_no_product_anchors")
                return False

            # Pick the first product anchor
            first_anchor = product_anchors[0]
            logging.info(f"Found {len(product_anchors)} product anchors; clicking the first: id={first_anchor.get_attribute('id')} text='{first_anchor.text}'")

            # Try a sequence of click strategies (safe_click -> JS click -> execute onclick -> __doPostBack)
            clicked = False
            try:
                # Strategy 1: use _safe_click by building an exact xpath for this element
                anchor_id = first_anchor.get_attribute("id")
                if anchor_id:
                    anchor_xpath = f"//*[@id='{anchor_id}']"
                    logging.info("Attempting _safe_click on anchor by id...")
                    if self._safe_click(By.XPATH, anchor_xpath):
                        clicked = True
                # Strategy 2: JS click on the element object
                if not clicked:
                    logging.info("Attempting JS click (arguments[0].click())...")
                    try:
                        self.driver.execute_script("arguments[0].scrollIntoView(true); arguments[0].click();", first_anchor)
                        clicked = True
                    except Exception as e:
                        logging.debug(f"JS click failed: {e}")
                # Strategy 3: Execute the element's onclick JS directly (if present)
                if not clicked:
                    onclick_js = first_anchor.get_attribute("onclick")
                    if onclick_js:
                        logging.info("Attempting to run onclick JS directly.")
                        try:
                            # remove leading 'javascript:' if present
                            exec_js = onclick_js.strip()
                            if exec_js.lower().startswith("javascript:"):
                                exec_js = exec_js[len("javascript:"):]
                            self.driver.execute_script(exec_js)
                            clicked = True
                        except Exception as e:
                            logging.debug(f"Executing onclick JS failed: {e}")
                # Strategy 4: If href contains __doPostBack, call it explicitly
                if not clicked:
                    href = first_anchor.get_attribute("href") or ""
                    if "__doPostBack" in href:
                        logging.info("Attempting to call __doPostBack from href.")
                        try:
                            # href looks like "javascript:__doPostBack('ctl00$PageContent$MyGridView1$ctl03$LinkButton_CompanyProduct','')"
                            js_call = href.strip()
                            if js_call.lower().startswith("javascript:"):
                                js_call = js_call[len("javascript:"):]
                            self.driver.execute_script(js_call)
                            clicked = True
                        except Exception as e:
                            logging.debug(f"Calling __doPostBack failed: {e}")
            except Exception as e:
                logging.error(f"Exception while attempting click strategies: {e}", exc_info=True)

            if not clicked:
                logging.error("All click strategies failed for the first product anchor.")
                self._save_snapshot("company_first_anchor_click_failed")
                return False

            # After click, wait for either the expected CompaniesList.aspx URL or a clear landmark on the resulting page.
            try:
                logging.info("Waiting for final companies list page or an expected landmark after clicking...")
                WebDriverWait(self.driver, 20).until(EC.any_of(
                    EC.url_contains("CompaniesList.aspx"),
                    EC.presence_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")),  # table on final page
                    EC.presence_of_element_located((By.XPATH, "//input[@type='image' and @title='Text file']"))  # the text file download button
                ))
                logging.info("Successfully handled redirect and landed on the final companies list page (or landmark found).")
            except Exception as e:
                logging.error(f"Failed to detect final companies page after click: {e}", exc_info=True)
                self._save_snapshot("company_post_click_verify_failed")
                return False

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
        logging.info(f"Parsing Time Series data from TXT file: {os.path.basename(file_path)}")
        try:
            df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig')
            df.columns = [col.strip().strip('"') for col in df.columns]
            df = df.apply(lambda x: x.str.strip().str.strip('"') if x.dtype == "object" else x)

            # Identify the main data source column (country/product names)
            data_source_col = df.columns[0]

            # Identify columns for values, quantities and unit values
            value_cols = [col for col in df.columns if re.search(r'value in \d{4}', col.lower())]
            qty_cols = [col for col in df.columns if re.search(r'quantity in \d{4}', col.lower()) or re.search(r'qty in \d{4}', col.lower())]
            uv_cols = [col for col in df.columns if re.search(r'unit value in \d{4}', col.lower())]

            # fallback: sometimes columns are like 'Value in 2024', 'Imported value in 2024'
            if not value_cols:
                value_cols = [col for col in df.columns if 'value in' in col.lower() or col.lower().endswith('value')]
            # convert numeric
            for col in value_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            for col in qty_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')
            for col in uv_cols:
                df[col] = pd.to_numeric(df[col], errors='coerce')

            df.fillna(0, inplace=True)

            # years list inferred from the column names
            def year_from_col(col):
                m = re.search(r'(\d{4})', col)
                return int(m.group(1)) if m else None

            years = sorted([year_from_col(c) for c in (value_cols or qty_cols) if year_from_col(c)])
            if not years and value_cols:
                # try to extract digits
                years = sorted(list({year_from_col(c) for c in value_cols if year_from_col(c)}))

            latest_year = years[-1] if years else None
            start_year = years[0] if years else None
            periods = (latest_year - start_year) if latest_year and start_year else 0

            # helper: map year -> column name
            def col_for_year(prefix_cols, y):
                for c in prefix_cols:
                    if str(y) in c:
                        return c
                return None

            data = {
                'data_source_column': data_source_col,
                'years': years,
                'latest_year': latest_year,
                'start_year': start_year,
                'periods': periods,
                'raw_file': os.path.basename(file_path)
            }

            # extract world row timeseries
            world_row = df[df[data_source_col].astype(str).str.lower() == 'world']
            if not world_row.empty and years:
                world_values = []
                world_quantities = []
                world_unit_values = []
                for y in years:
                    vc = col_for_year(value_cols, y)
                    qc = col_for_year(qty_cols, y) if qty_cols else None
                    uc = col_for_year(uv_cols, y) if uv_cols else None
                    v = int(world_row[vc].iloc[0]) if vc and vc in world_row.columns else 0
                    q = int(world_row[qc].iloc[0]) if qc and qc in world_row.columns else None
                    u = float(world_row[uc].iloc[0]) if uc and uc in world_row.columns else None
                    world_values.append(v)
                    world_quantities.append(q)
                    world_unit_values.append(u)
                data.update({'world_values_usd': world_values, 'world_quantities': world_quantities, 'world_unit_values': world_unit_values})

                data['total_value_usd'] = world_values[-1] if world_values else 0

            # extract your country row timeseries
            yc_row = df[df[data_source_col].astype(str).str.lower() == config['your_country'].lower()]
            if not yc_row.empty and years:
                yc_values = []
                yc_quantities = []
                yc_unit_values = []
                for y in years:
                    vc = col_for_year(value_cols, y)
                    qc = col_for_year(qty_cols, y) if qty_cols else None
                    uc = col_for_year(uv_cols, y) if uv_cols else None
                    v = int(yc_row[vc].iloc[0]) if vc and vc in yc_row.columns else 0
                    q = int(yc_row[qc].iloc[0]) if qc and qc in yc_row.columns else None
                    u = float(yc_row[uc].iloc[0]) if uc and uc in yc_row.columns else None
                    yc_values.append(v)
                    yc_quantities.append(q)
                    yc_unit_values.append(u)
                data.update({'your_country_values_usd': yc_values, 'your_country_quantities': yc_quantities, 'your_country_unit_values': yc_unit_values})

                data['imports_from_your_country_usd'] = data['your_country_values_usd'][-1] if data.get('your_country_values_usd') else 0

            # compute CAGR and last-year growth when possible
            def safe_cagr(end, start, n):
                try:
                    return round(((end / start) ** (1 / n) - 1) * 100, 2) if start > 0 and n > 0 else 0.0
                except Exception:
                    return 0.0

            if data.get('total_value_usd') and data.get('world_values_usd'):
                if len(data['world_values_usd']) >= 2:
                    last = data['world_values_usd'][-1]
                    prev = data['world_values_usd'][-2]
                    data['market_growth_last_year_pct'] = round((last - prev) / prev * 100, 2) if prev > 0 else 0.0
                if start_year and latest_year and data['world_values_usd'][0] > 0:
                    data['market_growth_cagr_pct'] = safe_cagr(data['world_values_usd'][-1], data['world_values_usd'][0], periods)

            if data.get('your_country_values_usd'):
                if len(data['your_country_values_usd']) >= 2:
                    last = data['your_country_values_usd'][-1]
                    prev = data['your_country_values_usd'][-2]
                    data['your_country_growth_last_year_pct'] = round((last - prev) / prev * 100, 2) if prev > 0 else 0.0
                if start_year and latest_year and data['your_country_values_usd'][0] > 0:
                    data['your_country_growth_cagr_pct'] = safe_cagr(data['your_country_values_usd'][-1], data['your_country_values_usd'][0], periods)

            # compute supplier ranking table if file lists suppliers
            suppliers = []
            try:
                # assume rows other than 'World' are suppliers
                comp_df = df[df[data_source_col].astype(str).str.lower() != 'world']
                # pick latest year column for ranking
                latest_col = None
                if years:
                    latest_col = col_for_year(value_cols, years[-1])
                if latest_col:
                    comp_df_sorted = comp_df.sort_values(by=latest_col, ascending=False)
                else:
                    comp_df_sorted = comp_df

                # compute world total for share calculations
                world_total = data.get('total_value_usd') or (comp_df_sorted[latest_col].sum() if latest_col and latest_col in comp_df_sorted.columns else 0)
                for i, row in comp_df_sorted.iterrows():
                    name = str(row[data_source_col]).strip()
                    v = int(row[latest_col]) if latest_col and latest_col in comp_df_sorted.columns else 0
                    q = None
                    u = None
                    if qty_cols:
                        qcol = col_for_year(qty_cols, years[-1]) if years else None
                        if qcol and qcol in row.index:
                            q = int(row[qcol]) if not math.isnan(float(row[qcol])) else None
                    if uv_cols:
                        ucol = col_for_year(uv_cols, years[-1]) if years else None
                        if ucol and ucol in row.index:
                            try:
                                u = float(row[ucol])
                            except Exception:
                                u = None

                    suppliers.append({
                        'rank': len(suppliers) + 1,
                        'name': name,
                        'value_usd': v,
                        'market_share_pct': round((v / world_total) * 100, 2) if world_total else 0.0,
                        'quantity_latest': q,
                        'unit_value_latest': u,
                        'raw_value': row[latest_col] if latest_col in row.index else None
                    })

                data['suppliers_full_list'] = suppliers
                # top N
                data['top_suppliers_sample'] = suppliers[:20]

                # calculate HHI (sum of squared market shares) on top suppliers
                hhi = sum([(s['market_share_pct'] ** 2) for s in suppliers[:50]]) if suppliers else 0
                data['hhi'] = round(hhi, 2)
                if hhi < 1500:
                    concentration = 'not concentrated'
                elif hhi < 2500:
                    concentration = 'moderately concentrated'
                else:
                    concentration = 'concentrated'
                data['concentration'] = concentration

                # find your country's rank
                found = next((s for s in suppliers if s['name'].lower() == config['your_country'].lower()), None)
                if found:
                    data['your_country_rank_in_target_market_imports'] = found['rank']
            except Exception as e:
                logging.debug(f"Could not compute supplier list details: {e}")

            logging.info("Successfully parsed Time Series data.")
            return data

        except Exception as e:
            logging.error(f"Failed parsing timeseries file: {e}")
            return {}

    def _parse_company_txt(self, file_path):
        logging.info(f"Parsing Company data from TXT file: {os.path.basename(file_path)}")
        try:
            df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig', dtype=str).fillna('')
            original_cols = list(df.columns)
            df.columns = [c.strip() for c in original_cols]
            lowered = [c.strip().lower() for c in original_cols]

            def find_col(candidates):
                for cand in candidates:
                    for i, c in enumerate(lowered):
                        if cand == c or cand in c or c in cand:
                            return original_cols[i]
                return None

            name_col = find_col(['importers', 'company name', 'company', 'exporters', 'importer', 'exporter', 'name'])
            city_col = find_col(['city', 'town'])
            website_col = find_col(['website', 'web site', 'web', 'url', 'site'])
            phone_col = find_col(['phone', 'tel', 'telephone'])
            email_col = find_col(['email', 'e-mail'])
            addr_col = find_col(['address', 'addr'])

            if not name_col:
                logging.error(f"No valid company column found. Columns available: {original_cols}")
                return []

            records = []
            for _, row in df.iterrows():
                rec = {
                    'name': str(row.get(name_col, '')).strip(),
                    'city': str(row.get(city_col, '')).strip() if city_col else '',
                    'website': str(row.get(website_col, '')).strip() if website_col else '',
                    'phone': str(row.get(phone_col, '')).strip() if phone_col else '',
                    'email': str(row.get(email_col, '')).strip() if email_col else '',
                    'address': str(row.get(addr_col, '')).strip() if addr_col else ''
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
            logging.info("===== TASK 1 of 3: SCRAPING TARGET MARKET IMPORTS =====")
            market_data = s.download_and_parse_timeseries_data(CONFIG, trade_flow='I')
            if market_data:
                final_data["market_size"] = {"target_market_imports_from_world_usd": market_data.get("total_value_usd")}
                final_data["market_growth"] = {"target_market_growth_last_year_pct": market_data.get("market_growth_last_year_pct"), "target_market_growth_cagr_pct": market_data.get("market_growth_cagr_pct")}
                final_data["your_country_performance"] = market_data
                # move suppliers into competition block
                final_data["competition"] = {"top_suppliers_sample": market_data.get('top_suppliers_sample'), "hhi": market_data.get('hhi'), "concentration": market_data.get('concentration'), "top_3_suppliers": market_data.get('top_suppliers_sample')[:3] if market_data.get('top_suppliers_sample') else []}

            logging.info("===== TASK 2 of 3: SCRAPING YOUR COUNTRY'S EXPORTS =====")
            export_data = s.download_and_parse_timeseries_data(CONFIG, trade_flow='E')
            if export_data and "your_country_performance" in final_data:
                final_data["your_country_performance"]["your_country_total_exports_to_world_usd"] = export_data.get("total_value_usd")

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
            try:
                s.driver.quit()
            except Exception:
                pass
        else:
            print("Script finished or encountered an error before browser started.")
