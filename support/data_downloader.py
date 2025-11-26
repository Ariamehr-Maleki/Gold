# support/data_downloader.py

from typing import Optional, Set, List
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote
import time
import random
import os
import glob
import logging as stdlogging

from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    MoveTargetOutOfBoundsException,
    NoSuchElementException
)

from support.spider_core import TradeSpider, logging

# Constant used across methods
_MAIN_TABLE_ID = "ctl00_PageContent_MyGridView1"
_NEXT_BTN_ID = "ctl00_PageContent_GridViewPanelControl_ImageButton_Next"

class DataDownloader(TradeSpider):
    """Downloader that navigates TradeMap pages and reliably downloads exports."""

    def _ensure_latest_period(self):
        """
        Checks if the 'Next Period' arrow is active. If so, clicks it until 
        it becomes disabled (indicating we are viewing the most recent years).
        """
        max_clicks = 5  # Safety limit to prevent infinite loops
        for i in range(max_clicks):
            try:
                # Locate the button
                next_btn = self.driver.find_element(By.ID, _NEXT_BTN_ID)

                # Check attributes to see if it's active
                # TradeMap uses src=".../NextArrow_off.png" OR disabled="disabled"
                src = next_btn.get_attribute("src")
                is_disabled = next_btn.get_attribute("disabled")

                if is_disabled == 'true' or is_disabled == 'disabled' or "NextArrow_off.png" in src:
                    logging.info("Confirmed: Currently on the latest time period.")
                    return True

                # If active, we need to click
                logging.info(f"Found active 'Next' arrow (Page {i+1}). Clicking to get latest years...")
                
                # Capture the grid to wait for it to go stale
                current_grid = self.driver.find_element(By.ID, _MAIN_TABLE_ID)
                
                # Click
                self.driver.execute_script("arguments[0].click();", next_btn)
                
                # Wait for reload
                try:
                    WebDriverWait(self.driver, 10).until(EC.staleness_of(current_grid))
                    WebDriverWait(self.driver, 10).until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                    time.sleep(1.5) # Brief settle time
                except TimeoutException:
                    logging.warning("Grid did not refresh quickly after clicking Next. Continuing...")

            except NoSuchElementException:
                # Button doesn't exist (single page of data), which is fine.
                return True
            except Exception as e:
                logging.warning(f"Error checking/clicking Next Period button: {e}")
                return True # Don't crash the scraper, just proceed with what we have
        
        logging.warning("Reached max clicks for 'Next Period'. Proceeding.")
        return True

    def navigate_to_world_view_page(self, config: dict, view: str = "value") -> bool:
        """Navigate to the world-timeseries page with strict verification and period check."""
        max_attempts = 4
        hs_code = config.get("hs_code")
        view_codes = {"value": "1", "quantity": "2", "unit_value": "3"}
        target_view_code = view_codes.get((view or "").lower(), "1")

        for attempt in range(1, max_attempts + 1):
            logging.info(f"--- WORLD VIEW ATTEMPT {attempt}/{max_attempts} for '{view}' ---")
            
            url = (
                f"https://www.trademap.org/Country_SelProduct_TS.aspx?"
                f"nvpm=1|||||{hs_code}|||6|1|1|1|2|1|2|{target_view_code}|1|1"
            )
            
            if not self.goto(url):
                continue

            # --- VERIFICATION LOGIC ---
            time.sleep(2)
            current_nvpm = self._get_nvpm_parts_from_url(self.driver.current_url)
            
            # Check 1: HS Code (Index 5)
            if not current_nvpm or len(current_nvpm) <= 5 or current_nvpm[5] != str(hs_code):
                logging.warning(f"Mismatch: HS Code in URL != Target ({hs_code}). Retrying...")
                continue

            # Check 2: View Code
            if target_view_code not in current_nvpm[-5:]: 
                logging.warning(f"Mismatch: View Code '{target_view_code}' not found. Retrying...")
                continue

            try:
                self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                
                # --- NEW: Ensure we are looking at the latest years ---
                self._ensure_latest_period()
                
                logging.info(f"SUCCESS: Verified World page for view '{view}'.")
                return True
            except TimeoutException:
                logging.warning("Table did not load. Retrying.")

        return False

    def navigate_to_country_view_page(
        self, config: dict, country_id: str, trade_flow: str = "I", view: str = "value"
    ) -> bool:
        """Navigate to the country-timeseries page with strict verification and period check."""
        max_attempts = 4
        hs_code = config.get("hs_code")
        trade_flow_code = "1" if trade_flow == "I" else "2"
        view_codes = {"value": "1", "quantity": "2", "unit_value": "3"}
        target_view_code = view_codes.get((view or "").lower(), "1")

        for attempt in range(1, max_attempts + 1):
            logging.info(
                f"--- COUNTRY VIEW ATTEMPT {attempt}/{max_attempts} for view '{view}' (Target: {country_id}) ---"
            )
            
            url = (
                f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?"
                f"nvpm=1|{country_id}||||{hs_code}|||2|1|1|{trade_flow_code}|2|1|2|{target_view_code}|1|1"
            )
            
            if not self.goto(url):
                continue

            # --- STRICT VERIFICATION LOGIC ---
            time.sleep(3) 
            current_nvpm = self._get_nvpm_parts_from_url(self.driver.current_url)
            
            if not current_nvpm or len(current_nvpm) <= 1:
                continue
                
            if current_nvpm[1] != str(country_id):
                logging.warning(f"Redirect detected! Loaded Country {current_nvpm[1]} instead of {country_id}. Retrying...")
                continue

            if target_view_code not in current_nvpm[-6:]:
                logging.warning(f"View mismatch! URL does not contain View Code '{target_view_code}'. Retrying...")
                continue

            try:
                self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                
                # --- NEW: Ensure we are looking at the latest years ---
                self._ensure_latest_period()
                
                logging.info(f"SUCCESS: Verified Country page locked on ID {country_id}, View '{view}'.")
                return True
            except TimeoutException:
                logging.warning("Table element missing. Retrying.")

        logging.error(f"All {max_attempts} attempts failed for country view '{view}'.")
        return False

    def navigate_to_companies_page(self, config: dict, country_id: str = None, trade_flow: str = 'I') -> bool:
        """
        Navigate to the Companies page with strict Country ID verification.
        """
        target_id = country_id if country_id else config.get('target_market_id')
        product_code = config.get('hs_code')
        trade_flow_code = '1' if trade_flow == 'I' else '2'
        max_attempts = 4
        redirect_handled = False 

        logging.info(f"Navigating to Companies page for Product {product_code}, Country {target_id}...")

        for attempt in range(1, max_attempts + 1):
            redirect_handled = False 
            url = (
                f"https://www.trademap.org/CompaniesList.aspx?"
                f"nvpm=1|{target_id}||||{product_code}|||4|1|1|{trade_flow_code}|3|1|1|1|1|4"
            )
            
            logging.info(f"Companies navigation attempt {attempt}/{max_attempts}...")
            self.driver.get(url)
            time.sleep(3) 

            # --- REDIRECT HANDLING ---
            if "CorrespondingProductsCompanies.aspx" in self.driver.current_url:
                logging.warning("Redirected to clarification page. Locating specific product link...")
                try:
                    self.wait.until(EC.visibility_of_element_located((By.ID, _MAIN_TABLE_ID)))
                    
                    # CSS Selector for the specific data link (Avoiding headers)
                    specific_link_selector = "a[id*='LinkButton_CompanyProduct']"
                    target_link = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, specific_link_selector)))
                    
                    logging.info(f"Found product link: '{target_link.text}'. Clicking...")
                    self.driver.execute_script("arguments[0].click();", target_link)
                    
                    WebDriverWait(self.driver, 15).until(EC.url_contains("CompaniesList.aspx"))
                    time.sleep(2)
                    redirect_handled = True 

                except Exception as e:
                    logging.error(f"Failed to handle clarification redirect: {e}")
                    continue

            # --- VERIFICATION ---
            if "CompaniesList.aspx" not in self.driver.current_url:
                logging.warning(f"Current URL is not CompaniesList.aspx. Retrying...")
                continue

            if not redirect_handled:
                current_nvpm = self._get_nvpm_parts_from_url(self.driver.current_url)
                if current_nvpm and len(current_nvpm) > 1:
                    if current_nvpm[1] != str(target_id):
                        logging.warning(f"Wrong Country ID {current_nvpm[1]} detected. Retrying...")
                        continue

            # --- FINAL SUCCESS CONFIRMATION ---
            try:
                self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                
                # Check for download button
                download_btn = self.driver.find_elements(By.XPATH, "//input[@type='image' and @title='Text file']")
                if download_btn:
                    logging.info(f"SUCCESS: Landed on Companies List (Country {target_id}).")
                    return True
                else:
                    logging.warning("Landed on page, but Download button not found yet. Waiting...")
                    time.sleep(2)
                    return True
                    
            except TimeoutException:
                logging.warning("Companies table did not load. Retrying.")

        logging.error("Failed to navigate to the correct Companies page.")
        return False

    def _download_file(self, rename_to: Optional[str] = None, clean_dir: bool = True) -> Optional[str]:
        """
        Atomically download a file by detecting a new file appearing in the download dir.
        """
        patterns = ["*.txt*", "*.part", "*.crdownload", "*.tmp", "*.download"]

        if clean_dir:
            logging.info(f"Cleaning old files from '{self.download_dir}'...")
            for pat in patterns:
                for f in glob.glob(os.path.join(self.download_dir, pat)):
                    try:
                        os.remove(f)
                    except OSError:
                        pass

        existing_files: Set[str] = set()
        for pat in patterns:
            existing_files.update(set(glob.glob(os.path.join(self.download_dir, pat))))

        click_xpath = "//input[@type='image' and @title='Text file']"
        if not self._safe_click(By.XPATH, click_xpath):
            logging.error("Failed to click download button.")
            return None

        timeout = 90
        end_time = time.time() + timeout
        downloaded_file_path: Optional[str] = None

        try:
            # Wait for new file
            while time.time() < end_time:
                current_files = set()
                for pat in patterns:
                    current_files.update(set(glob.glob(os.path.join(self.download_dir, pat))))
                new_files = current_files - existing_files
                if new_files:
                    newest = max(new_files, key=lambda p: os.path.getmtime(p))
                    downloaded_file_path = newest
                    logging.info(f"New file detected: {os.path.basename(downloaded_file_path)}")
                    break
                time.sleep(0.5)

            if not downloaded_file_path:
                return None

            # Wait for stability
            last_size = -1
            stable_count = 0
            while time.time() < end_time and stable_count < 3:
                try:
                    current_size = os.path.getsize(downloaded_file_path)
                    if current_size == last_size and current_size > 0:
                        stable_count += 1
                    else:
                        stable_count = 0
                    last_size = current_size
                except OSError:
                    stable_count = 0
                time.sleep(0.7)

            if stable_count < 3:
                return None

            if rename_to:
                new_path = os.path.join(self.download_dir, rename_to)
                try:
                    if os.path.exists(new_path): os.remove(new_path)
                    os.replace(downloaded_file_path, new_path)
                    return new_path
                except Exception as e:
                    logging.error(f"Renaming failed: {e}")
                    return downloaded_file_path

            return downloaded_file_path

        except Exception as e:
            logging.exception(f"Exception during download: {e}")
            return None

    def _get_nvpm_parts_from_url(self, url: str) -> Optional[List[str]]:
        try:
            parsed = urlparse(unquote(url))
            qs = parse_qs(parsed.query, keep_blank_values=True)
            nvpm_vals = qs.get("nvpm")
            if not nvpm_vals:
                return None
            return nvpm_vals[0].split("|")
        except Exception:
            return None