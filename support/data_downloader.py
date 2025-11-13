# data_downloader.py (Corrected with Robust File Identification)

from spider_core import TradeSpider, logging
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
from urllib.parse import unquote
import time
import random
import os
import glob
import re

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
        """
        Navigate to the Companies page. If TradeMap redirects to a clarification page
        with a product-list table, click the *first* product link robustly using multiple strategies.
        """
        country_id = config['target_market_id']
        product_code = config['hs_code']
        logging.info(f"Navigating to Companies page for product {product_code}, country {country_id}")
        trade_flow_code = '1' if trade_flow == 'I' else '2'
        url = f"https://www.trademap.org/CompaniesList.aspx?nvpm=1|{country_id}||||{product_code}|||4|1|1|{trade_flow_code}|3|1|1|1|1|4"
        
        logging.info(f"Navigating directly to COMPANIES URL: {url}")
        self.driver.get(url)
        time.sleep(2.5 + random.random()*1.5)
        
        if "CorrespondingProductsCompanies.aspx" in self.driver.current_url:
            logging.warning("Redirected to product clarification page. Handling redirect...")
            try:
                self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
                logging.info("Clarification table visible.")

                first_link_xpath = "//table[@id='ctl00_PageContent_MyGridView1']//tr[2]//a"
                
                if self._safe_click(By.XPATH, first_link_xpath):
                     logging.info("Clicked first product link via _safe_click.")
                else:
                    logging.warning("Safe click failed, trying JS click as fallback...")
                    try:
                        first_el = self.driver.find_element(By.XPATH, first_link_xpath)
                        self.driver.execute_script("arguments[0].click();", first_el)
                        logging.info("Executed JavaScript click on first product link.")
                    except Exception as e:
                        logging.error(f"All click strategies failed for the first product link. Error: {e}")
                        self._save_snapshot("company_all_clicks_failed")
                        return False
                
                logging.info("Click attempted. Waiting for final CompaniesList.aspx to load...")
                WebDriverWait = self.wait.__class__
                WebDriverWait(self.driver, 15).until(EC.url_contains("CompaniesList.aspx"))
                logging.info("Successfully handled redirect and landed on the final companies list page.")
                return True

            except Exception as e:
                logging.error(f"Failed to handle the company page redirect. Error: {e}")
                self._save_snapshot("company_redirect_handler_failed")
                return False

        elif "CompaniesList.aspx" in self.driver.current_url:
            logging.info("Successfully landed on the companies list page directly.")
            return True
        else:
            logging.error(f"Navigation to companies page failed. Ended up on an unknown page: {self.driver.current_url}")
            self._save_snapshot("company_navigation_unknown_failure")
            return False

    # --- FIX APPLIED HERE ---
    def _download_file(self, rename_to: str | None = None, clean_dir: bool = True):
        """
        Atomically downloads a file by tracking the directory state.
        FIX: It now records existing files *before* download and waits for a *new* one to appear.
        This prevents race conditions when downloading multiple files to the same directory.
        """
        if clean_dir:
            logging.info(f"Preparing for single download. Cleaning old text/part files from '{self.download_dir}'...")
            # Clean both .txt and browser temporary files (.part)
            for f in glob.glob(os.path.join(self.download_dir, "*.txt*")) + glob.glob(os.path.join(self.download_dir, "*.part")):
                try:
                    os.remove(f)
                    logging.debug(f"Removed old file: {f}")
                except OSError as e:
                    logging.warning(f"Could not remove old file {f}: {e}")
        
        # --- FIX: Get the set of files in the directory BEFORE starting the download ---
        existing_files = set(glob.glob(os.path.join(self.download_dir, "*.txt")))
        
        click_xpath = "//input[@type='image' and @title='Text file']"
        
        logging.info(f"Attempting download for '{rename_to or 'file'}'...")
        if not self._safe_click(By.XPATH, click_xpath):
            logging.error(f"Failed to click download button for '{rename_to}'.")
            return None
        
        timeout = 60
        end_time = time.time() + timeout
        downloaded_file_path = None
        
        try:
            # Wait for a NEW file to appear
            while time.time() < end_time:
                # --- FIX: Find a file that is not in the 'existing_files' set ---
                current_files = set(glob.glob(os.path.join(self.download_dir, "*.txt")))
                new_files = current_files - existing_files
                
                if new_files:
                    # We found our new file
                    downloaded_file_path = new_files.pop()
                    logging.info(f"New file detected: {os.path.basename(downloaded_file_path)}")
                    break
                time.sleep(0.5)

            if not downloaded_file_path:
                logging.error("Download timed out. No new .txt file appeared.")
                self._save_snapshot("download_timeout_no_new_file")
                return None

            # Wait for the file size to stabilize, indicating download completion
            last_size = -1
            stable_checks = 3 
            stable_count = 0
            while time.time() < end_time and stable_count < stable_checks:
                try:
                    current_size = os.path.getsize(downloaded_file_path)
                    if current_size == last_size and current_size > 0:
                        stable_count += 1
                    else:
                        stable_count = 0 
                    last_size = current_size
                    logging.debug(f"Checking file size: {current_size} bytes. Stable count: {stable_count}/{stable_checks}")
                except OSError:
                    logging.debug("File is locked, waiting...")
                    stable_count = 0
                time.sleep(0.7)

            if stable_count < stable_checks:
                logging.error(f"Download timed out. File '{os.path.basename(downloaded_file_path)}' did not stabilize.")
                self._save_snapshot("download_unstable_file")
                return None

            logging.info(f"File download confirmed and stabilized at {last_size} bytes.")
            
            # Now that the file is stable, rename it
            if rename_to:
                new_path = os.path.join(self.download_dir, rename_to)
                # Use os.replace for an atomic rename operation
                os.replace(downloaded_file_path, new_path)
                logging.info(f"Successfully renamed downloaded file to '{rename_to}'")
                return new_path
            
            return downloaded_file_path

        except Exception as e:
            logging.error(f"An exception occurred during the download process for '{rename_to}': {e}", exc_info=True)
            self._save_snapshot("download_exception")
            return None