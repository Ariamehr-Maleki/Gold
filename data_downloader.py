# data_downloader.py (Final Version with Robust JavaScript Click)

from spider_core import TradeSpider, logging
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from urllib.parse import unquote
import time
import random
import os
import glob

class DataDownloader(TradeSpider):

    def navigate_to_world_view_page(self, config, view='value'):
        max_attempts = 4
        hs_code = config['hs_code']
        for attempt in range(1, max_attempts + 1):
            logging.info(f"--- WORLD VIEW ATTEMPT {attempt}/{max_attempts} for '{view}' ---")
            view_codes = {'value': '1', 'quantity': '2', 'unit_value': '3'}
            view_code = view_codes.get(view.lower(), '1')
            url = f"https://www.trademap.org/Country_SelProduct_TS.aspx?nvpm=1|||||{hs_code}|||6|1|1|1|2|1|2|{view_code}|1|1"
            logging.info(f"Navigating to WORLD URL: {url}")
            if not self.goto(url):
                logging.warning(f"Navigation failed on attempt {attempt}. Retrying...")
                continue
            try:
                url_param_to_check = f"|||||{hs_code}|"
                logging.info(f"Verifying DECODED URL contains parameter: '{url_param_to_check}'...")
                self.wait.until(lambda driver: url_param_to_check in unquote(driver.current_url))
                logging.info("URL parameter for HS Code VERIFIED.")
                header_text = view.replace('_', ' ')
                header_xpath = f"//table[@id='ctl00_PageContent_MyGridView1']//th[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{header_text}')]"
                logging.info(f"Verifying column header contains '{header_text}'...")
                self.wait.until(EC.presence_of_element_located((By.XPATH, header_xpath)))
                logging.info(f"SUCCESS: World page for '{view}' is fully loaded and verified.")
                return True
            except TimeoutException:
                logging.warning(f"URL or content verification failed for '{view}' on attempt {attempt}. Retrying.")
                self._save_snapshot(f"world_verify_failed_attempt_{attempt}")
        logging.error(f"All {max_attempts} attempts failed for World '{view}'.")
        return False

    def navigate_to_country_view_page(self, config, country_id, trade_flow='I', view='value'):
        max_attempts = 4
        hs_code = config['hs_code']
        for attempt in range(1, max_attempts + 1):
            logging.info(f"--- COUNTRY VIEW ATTEMPT {attempt}/{max_attempts} for view '{view}' (Country ID: {country_id}) ---")
            trade_flow_code = '1' if trade_flow == 'I' else '2'
            view_codes = {'value': '1', 'quantity': '2', 'unit_value': '3'}
            view_code = view_codes.get(view.lower(), '1')
            url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm=1|{country_id}||||{hs_code}|||2|1|1|{trade_flow_code}|2|1|2|{view_code}|1|1"
            logging.info(f"Navigating to COUNTRY URL: {url}")
            if not self.goto(url):
                logging.warning(f"Navigation failed on attempt {attempt}. Retrying...")
                continue
            try:
                url_param_to_check = f"|{country_id}|"
                logging.info(f"Verifying DECODED URL contains parameter: '{url_param_to_check}'...")
                self.wait.until(lambda driver: url_param_to_check in unquote(driver.current_url))
                logging.info(f"URL parameter for Country ID VERIFIED.")
                header_text = view.replace('_', ' ')
                header_xpath = f"//table[@id='ctl00_PageContent_MyGridView1']//th[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{header_text}')]"
                logging.info(f"Verifying column header contains '{header_text}'...")
                self.wait.until(EC.presence_of_element_located((By.XPATH, header_xpath)))
                logging.info(f"SUCCESS: Country page for '{view}' (Country ID: {country_id}) is fully loaded and verified.")
                return True
            except TimeoutException:
                logging.warning(f"URL or content verification failed on attempt {attempt}. Retrying.")
                self._save_snapshot(f"country_verify_failed_attempt_{attempt}")
        logging.error(f"All {max_attempts} attempts failed for Country '{view}' (Country ID: {country_id}).")
        return False

    def navigate_to_companies_page(self, config, trade_flow='I'):
        country_id = config['target_market_id']
        product_code = config['hs_code']
        logging.info(f"Navigating to Companies page for product {product_code}, country {country_id}")
        trade_flow_code = '1' if trade_flow == 'I' else '2'
        url = f"https://www.trademap.org/CompaniesList.aspx?nvpm=1|{country_id}||||{product_code}|||4|1|1|{trade_flow_code}|3|1|1|1|1|4"
        
        logging.info(f"Navigating directly to COMPANIES URL: {url}")
        self.driver.get(url)
        
        time.sleep(3)
        
        if "CorrespondingProductsCompanies.aspx" in self.driver.current_url:
            logging.warning("Redirected to product clarification page. This is expected. Handling redirect...")
            try:
                clarification_table = (By.ID, "ctl00_PageContent_MyGridView1")
                logging.info("Waiting for the product clarification table to appear...")
                self.wait.until(EC.visibility_of_element_located(clarification_table))
                logging.info("Clarification table found.")

                # --- START OF FIX ---
                # The original click method can fail on JavaScript links.
                # We will now use a direct JavaScript execution which is more reliable.
                logging.info("Attempting to click the first product link using a direct JavaScript call...")
                first_product_link_locator = (By.XPATH, "//table[@id='ctl00_PageContent_MyGridView1']//a[1]")
                
                # 1. Wait for the element to be present and find it
                link_element = self.wait.until(EC.presence_of_element_located(first_product_link_locator))
                
                # 2. Execute the click via JavaScript
                self.driver.execute_script("arguments[0].click();", link_element)
                logging.info("JavaScript click executed successfully.")
                # --- END OF FIX ---
                
                self.wait.until(EC.url_contains("CompaniesList.aspx"))
                logging.info("Successfully handled redirect and landed on the final companies list page.")
                return True
            except Exception as e:
                logging.error(f"Failed to handle the company page redirect after landing on it. Error: {e}")
                self._save_snapshot("company_redirect_handler_failed")
                return False
        
        elif "CompaniesList.aspx" in self.driver.current_url:
            logging.info("Successfully landed on the companies list page directly.")
            return True
            
        else:
            logging.error(f"Navigation to companies page failed. Ended up on an unknown page: {self.driver.current_url}")
            self._save_snapshot("company_navigation_unknown_failure")
            return False

    def _download_file(self, rename_to: str | None = None, clean_dir: bool = True):
        if clean_dir:
            logging.info(f"Cleaning old text files from '{self.download_dir}'...")
            for f in glob.glob(os.path.join(self.download_dir, "*.txt*")):
                try: os.remove(f)
                except Exception: pass
        
        existing_files = set(glob.glob(os.path.join(self.download_dir, "*.txt")))
        max_attempts = 4
        click_xpath = "//input[@type='image' and @title='Text file']"
        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            logging.info(f"Download attempt {attempt}/{max_attempts} for '{rename_to or 'file'}'...")
            if not self._safe_click(By.XPATH, click_xpath):
                logging.error(f"Failed to click download button for '{rename_to}'.")
                continue 
            
            timeout = 60
            end_time = time.time() + timeout
            downloaded_file_path = None
            
            while time.time() < end_time:
                new_files = set(glob.glob(os.path.join(self.download_dir, "*.txt"))) - existing_files
                if new_files:
                    latest_file = new_files.pop()
                    time.sleep(1.5) 
                    try:
                        if os.path.getsize(latest_file) > 0:
                            downloaded_file_path = latest_file
                            logging.info(f"NEW file download confirmed: {os.path.basename(downloaded_file_path)}")
                            break 
                    except Exception as e:
                        logging.debug(f"Error checking file size (file may be locked): {e}")
                time.sleep(0.5)

            if downloaded_file_path:
                if rename_to:
                    try:
                        new_path = os.path.join(self.download_dir, rename_to)
                        os.replace(downloaded_file_path, new_path) 
                        logging.info(f"Successfully renamed downloaded file to '{rename_to}'")
                        return new_path
                    except OSError as e:
                        logging.error(f"Failed to rename file to '{rename_to}': {e}")
                        return None
                return downloaded_file_path
            
            logging.warning(f"Download attempt {attempt} timed out. No new .txt file was found.")
            
        logging.error(f"All download attempts failed for '{rename_to}'.")
        return None