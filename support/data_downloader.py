# support/data_downloader.py (Corrected with Strict Parameter Validation)
"""
DataDownloader — extends TradeSpider with robust navigation and download helpers
Features:
- deterministic enforcement of 'nvpm' view code (force + verify)
- robust download detection (handles .txt, .part, .crdownload, etc.)
- resilient handling of redirect-to-clarification for companies page
- generous logging and snapshots on failure
"""
from typing import Optional, Set, List
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse, unquote
import time
import random
import os
import glob
import logging as stdlogging

from support.spider_core import TradeSpider, logging  # logging from spider_core
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait 
from selenium.webdriver.common.by import By
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    MoveTargetOutOfBoundsException,
)

# constant used across methods
_MAIN_TABLE_ID = "ctl00_PageContent_MyGridView1"


class DataDownloader(TradeSpider):
    """Downloader that navigates TradeMap pages and reliably downloads exports."""

    def navigate_to_world_view_page(self, config: dict, view: str = "value") -> bool:
        """Navigate to the world-timeseries page with strict parameter verification."""
        max_attempts = 4
        hs_code = config.get("hs_code")
        
        # TradeMap View Codes: 1=Value, 2=Quantity, 3=Unit Value
        view_codes = {"value": "1", "quantity": "2", "unit_value": "3"}
        target_view_code = view_codes.get((view or "").lower(), "1")

        for attempt in range(1, max_attempts + 1):
            logging.info(f"--- WORLD VIEW ATTEMPT {attempt}/{max_attempts} for '{view}' ---")
            
            # Construct URL
            url = (
                f"https://www.trademap.org/Country_SelProduct_TS.aspx?"
                f"nvpm=1|||||{hs_code}|||6|1|1|1|2|1|2|{target_view_code}|1|1"
            )
            
            if not self.goto(url):
                continue

            # --- VERIFICATION LOGIC ---
            # TradeMap sometimes ignores parameters and loads the default view. 
            # We parse the current URL to ensure we are actually on the requested view.
            
            time.sleep(2) # Give the URL a moment to settle if it's redirecting
            
            current_nvpm = self._get_nvpm_parts_from_url(self.driver.current_url)
            
            # Check 1: HS Code (Index 5 in World View)
            if not current_nvpm or len(current_nvpm) <= 5 or current_nvpm[5] != str(hs_code):
                logging.warning(f"Mismatch: HS Code in URL ({current_nvpm[5] if current_nvpm and len(current_nvpm)>5 else 'N/A'}) != Target ({hs_code}). Retrying...")
                continue

            # Check 2: View Code (Index 14 in World View)
            # Note: Indices can vary slightly, so we search the last few segments for the code
            if target_view_code not in current_nvpm[-5:]: 
                logging.warning(f"Mismatch: View Code '{target_view_code}' ({view}) not found in active URL parameters. Retrying...")
                continue

            try:
                # Final check: Wait for the main table to definitely be there
                self.wait.until(EC.presence_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
                logging.info(f"SUCCESS: Verified World page is on view '{view}'.")
                return True
            except TimeoutException:
                logging.warning("Table did not load. Retrying.")

        return False

    def navigate_to_country_view_page(
        self, config: dict, country_id: str, trade_flow: str = "I", view: str = "value"
    ) -> bool:
        """
        Navigate to the country-timeseries page (Step 2) with strict verification.
        Prevents 'rushing in' and downloading unit value when value was requested.
        """
        max_attempts = 4
        hs_code = config.get("hs_code")
        trade_flow_code = "1" if trade_flow == "I" else "2"
        
        # TradeMap View Codes: 1=Value, 2=Quantity, 3=Unit Value
        view_codes = {"value": "1", "quantity": "2", "unit_value": "3"}
        target_view_code = view_codes.get((view or "").lower(), "1")

        for attempt in range(1, max_attempts + 1):
            logging.info(
                f"--- COUNTRY VIEW ATTEMPT {attempt}/{max_attempts} for view '{view}' (Target: {country_id}) ---"
            )
            
            # Construct URL
            url = (
                f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?"
                f"nvpm=1|{country_id}||||{hs_code}|||2|1|1|{trade_flow_code}|2|1|2|{target_view_code}|1|1"
            )
            
            if not self.goto(url):
                continue

            # --- STRICT VERIFICATION LOGIC ---
            # Wait explicitly for 3 seconds to allow TradeMap's internal redirection to settle
            # This prevents the "downloading wrong data" issue where it loads default (Value) 
            # for a split second before switching to Unit Value, or vice versa.
            time.sleep(6)

            current_nvpm = self._get_nvpm_parts_from_url(self.driver.current_url)
            
            # Check 1: Country ID (Index 1)
            if not current_nvpm or len(current_nvpm) <= 1:
                logging.warning("URL params missing or malformed. Retrying...")
                continue
                
            if current_nvpm[1] != str(country_id):
                logging.warning(f"Redirect detected! Page loaded Country {current_nvpm[1]} instead of {country_id}. Retrying...")
                continue

            # Check 2: View Code (Usually Index 14 for Country View)
            # We check if the target code exists in the last 6 parameters to be safe
            if target_view_code not in current_nvpm[-6:]:
                logging.warning(f"View mismatch! URL does not contain View Code '{target_view_code}' ({view}). Page likely reverted to default. Retrying...")
                # Force a refresh logic or just continue to loop which re-navigates
                continue

            try:
                self.wait.until(EC.presence_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
                logging.info(f"SUCCESS: Verified Country page is locked on ID {country_id} and View '{view}'.")
                return True
            except TimeoutException:
                logging.warning("Table element missing. Retrying.")

        logging.error(f"All {max_attempts} attempts failed for country view '{view}'.")
        return False

    # --- Helper Methods (Ensure these exist in your class) ---

    def _get_nvpm_parts_from_url(self, url: str) -> Optional[List[str]]:
        """Parses the 'nvpm' parameter from a TradeMap URL into a list."""
        try:
            parsed = urlparse(unquote(url))
            qs = parse_qs(parsed.query, keep_blank_values=True)
            nvpm_vals = qs.get("nvpm")
            if not nvpm_vals:
                return None
            return nvpm_vals[0].split("|")
        except Exception:
            return None
    # ... (rest of the file, including navigate_to_companies_page, _download_file, etc. remains unchanged) ...
    def navigate_to_companies_page(self, config: dict, country_id: str = None, trade_flow: str = 'I') -> bool:
        """
        Navigate to the Companies page.
        Fix: Bypasses strict parameter checks if a redirect click was performed successfully.
        """
        target_id = country_id if country_id else config.get('target_market_id')
        product_code = config.get('hs_code')
        trade_flow_code = '1' if trade_flow == 'I' else '2'
        max_attempts = 4
        
        # Flag to track if we manually clicked a link
        redirect_handled = False 

        logging.info(f"Navigating to Companies page for Product {product_code}, Country {target_id}...")

        for attempt in range(1, max_attempts + 1):
            # Reset flag on new attempt
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
                    self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
                    
                    # CSS Selector for the specific data link (Avoiding headers)
                    specific_link_selector = "a[id*='LinkButton_CompanyProduct']"
                    target_link = self.wait.until(EC.element_to_be_clickable((By.CSS_SELECTOR, specific_link_selector)))
                    
                    logging.info(f"Found product link: '{target_link.text}'. Clicking...")
                    self.driver.execute_script("arguments[0].click();", target_link)
                    
                    # Wait for the page to switch
                    WebDriverWait(self.driver, 15).until(EC.url_contains("CompaniesList.aspx"))
                    time.sleep(2)
                    
                    # MARK AS HANDLED so we don't fail the strict check below
                    redirect_handled = True 

                except Exception as e:
                    logging.error(f"Failed to handle clarification redirect: {e}")
                    continue

            # --- VERIFICATION ---
            # 1. Check if we are on the right page
            if "CompaniesList.aspx" not in self.driver.current_url:
                logging.warning(f"Current URL is not CompaniesList.aspx (URL: {self.driver.current_url}). Retrying...")
                continue

            # 2. Strict Parameter Check (ONLY if we didn't just handle a redirect)
            # If we just clicked the link, we trust the website sent us to the right place.
            if not redirect_handled:
                current_nvpm = self._get_nvpm_parts_from_url(self.driver.current_url)
                if current_nvpm and len(current_nvpm) > 1:
                    if current_nvpm[1] != str(target_id):
                        logging.warning(f"Wrong Country ID {current_nvpm[1]} detected (wanted {target_id}). Retrying...")
                        continue

            # --- FINAL SUCCESS CONFIRMATION ---
            try:
                # Wait for the main table
                self.wait.until(EC.presence_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
                
                # Pre-check: Ensure the DOWNLOAD button is present before returning True
                # This ensures the next step (downloading) will succeed immediately
                download_btn = self.driver.find_elements(By.XPATH, "//input[@type='image' and @title='Text file']")
                if download_btn:
                    logging.info(f"SUCCESS: Landed on Companies List (Country {target_id}) and Download button is visible.")
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
        Returns the final path (renamed if rename_to provided) or None on failure.
        """
        # patterns to consider for existing/temporary files
        patterns = ["*.txt*", "*.part", "*.crdownload", "*.tmp", "*.download"]

        if clean_dir:
            logging.info(f"Preparing for single download. Cleaning old files from '{self.download_dir}'...")
            for pat in patterns:
                for f in glob.glob(os.path.join(self.download_dir, pat)):
                    try:
                        os.remove(f)
                        logging.debug(f"Removed old file: {f}")
                    except OSError:
                        logging.debug(f"Could not remove {f}, skipping.")

        # collect snapshot of existing files (for all relevant patterns)
        existing_files: Set[str] = set()
        for pat in patterns:
            existing_files.update(set(glob.glob(os.path.join(self.download_dir, pat))))

        click_xpath = "//input[@type='image' and @title='Text file']"
        logging.info(f"Attempting download for '{rename_to or 'file'}'...")
        if not self._safe_click(By.XPATH, click_xpath):
            logging.error("Failed to click download button.")
            return None

        timeout = 90
        end_time = time.time() + timeout
        downloaded_file_path: Optional[str] = None

        try:
            # wait for any new file (matching patterns) to appear
            while time.time() < end_time:
                current_files = set()
                for pat in patterns:
                    current_files.update(set(glob.glob(os.path.join(self.download_dir, pat))))
                new_files = current_files - existing_files
                if new_files:
                    # pick the most recently modified new file
                    newest = max(new_files, key=lambda p: os.path.getmtime(p))
                    downloaded_file_path = newest
                    logging.info(f"New file detected: {os.path.basename(downloaded_file_path)}")
                    break
                time.sleep(0.5)

            if not downloaded_file_path:
                logging.error("Download timed out: no new file detected.")
                self._save_snapshot("download_timeout_no_new_file")
                return None

            # wait for file size to stabilize (indicates download finished)
            last_size = -1
            stable_count = 0
            required_stable = 3
            while time.time() < end_time and stable_count < required_stable:
                try:
                    current_size = os.path.getsize(downloaded_file_path)
                    # if size didn't change and is > 0, increase stable_count
                    if current_size == last_size and current_size > 0:
                        stable_count += 1
                    else:
                        stable_count = 0
                    last_size = current_size
                except OSError:
                    stable_count = 0
                time.sleep(0.7)

            if stable_count < required_stable:
                logging.error("Downloaded file did not stabilize in time.")
                self._save_snapshot("download_unstable_file")
                return None

            logging.info(f"File stabilized at {last_size} bytes.")

            if rename_to:
                new_path = os.path.join(self.download_dir, rename_to)
                try:
                    os.replace(downloaded_file_path, new_path)
                    logging.info(f"Renamed downloaded file to {rename_to}")
                    return new_path
                except Exception as e:
                    logging.exception(f"Failed to rename downloaded file: {e}")
                    return downloaded_file_path

            return downloaded_file_path

        except Exception as e:
            logging.exception(f"Exception during download detection: {e}")
            self._save_snapshot("download_exception")
            return None

    # -------------------- nvpm helpers --------------------

    def _get_nvpm_parts_from_url(self, url: str) -> Optional[List[str]]:
        """Parse the current URL and return the nvpm parts list or None."""
        try:
            parsed = urlparse(unquote(url))
            qs = parse_qs(parsed.query, keep_blank_values=True)
            nvpm_vals = qs.get("nvpm")
            if not nvpm_vals:
                return None
            nvpm = nvpm_vals[0]
            return nvpm.split("|")
        except Exception:
            return None

    def _ensure_nvpm_view(self, desired_view_code: str) -> bool:
        """
        Ensure the current page's nvpm parameter contains the desired view code.
        Strategy:
          1. Inspect nvpm parts. If one of the reasonable indices already matches, succeed.
          2. Otherwise, try rewriting nvpm at candidate indices and reload.
          3. Verify the desired view code was set.
        """
        try:
            cur_url = self.driver.current_url
            parts = self._get_nvpm_parts_from_url(cur_url)
            if not parts:
                logging.debug("No 'nvpm' found in current URL; cannot enforce view.")
                return False

            # quick-check: is desired code already present in a plausible position?
            if any(p == str(desired_view_code) for p in parts[-6:]):  # check last few segments
                logging.debug("Desired view code already present in nvpm parts.")
                return True

            # candidate indices to try (prefer a likely index, then relative offsets)
            candidate_indices = [14, len(parts) - 3, len(parts) - 4, len(parts) - 5]
            # dedupe and keep valid indices
            candidate_indices = [i for i in dict.fromkeys(candidate_indices) if 0 <= i < len(parts)]

            parsed = urlparse(unquote(cur_url))
            qs = parse_qs(parsed.query, keep_blank_values=True)

            for idx in candidate_indices:
                original = parts.copy()
                if parts[idx] == str(desired_view_code):
                    logging.debug(f"nvpm already had desired view at index {idx}.")
                    return True
                parts[idx] = str(desired_view_code)
                qs["nvpm"] = ["|".join(parts)]
                new_query = urlencode(qs, doseq=True)
                new_url = urlunparse((parsed.scheme, parsed.netloc, parsed.path, parsed.params, new_query, parsed.fragment))
                logging.info(f"Attempting to enforce nvpm view by navigating to corrected URL (index {idx}).")
                self.driver.get(new_url)
                # wait a small amount and confirm page ready
                if not self._wait_for_ready_state(timeout=15):
                    logging.debug("Forced nvpm reload did not reach readyState complete quickly (continuing).")
                # re-inspect
                new_parts = self._get_nvpm_parts_from_url(self.driver.current_url) or []
                if any(p == str(desired_view_code) for p in new_parts[-6:]):
                    logging.info("nvpm view enforcement succeeded.")
                    return True
                # restore parts for next candidate
                parts = original

            logging.warning("Tried candidate nvpm indices but could not set desired view code.")
            return False
        except Exception as e:
            logging.exception(f"_ensure_nvpm_view failed: {e}")
            return False