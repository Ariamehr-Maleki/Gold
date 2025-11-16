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
        """Navigate to the world-timeseries page for an HS code and ensure the requested view is active."""
        max_attempts = 4
        hs_code = config.get("hs_code")
        view_codes = {"value": "1", "quantity": "2", "unit_value": "3"}
        view_code = view_codes.get((view or "").lower(), "1")

        for attempt in range(1, max_attempts + 1):
            logging.info(f"--- WORLD VIEW ATTEMPT {attempt}/{max_attempts} for '{view}' ---")
            url = (
                f"https://www.trademap.org/Country_SelProduct_TS.aspx?"
                f"nvpm=1|||||{hs_code}|||6|1|1|1|2|1|2|{view_code}|1|1"
            )
            
            if not self.goto(url):
                logging.warning(f"goto() failed on attempt {attempt}. Retrying.")
                continue

            ### --- THIS IS THE CRITICAL FIX --- ###
            # After navigating, parse the ACTUAL URL in the browser and verify the HS code is correct.
            nvpm_parts = self._get_nvpm_parts_from_url(self.driver.current_url)
            # For the world view URL, the HS code is at index 5 in the 'nvpm' parameter.
            if not (nvpm_parts and len(nvpm_parts) > 5 and nvpm_parts[5] == str(hs_code)):
                found_code = nvpm_parts[5] if (nvpm_parts and len(nvpm_parts) > 5) else "not found or incorrect"
                logging.warning(
                    f"URL parameter mismatch on attempt {attempt}. Expected HS code '{hs_code}', but found '{found_code}'. This means the server returned the wrong page. Retrying."
                )
                self._save_snapshot(f"world_hs_code_mismatch_attempt_{attempt}")
                # A brief pause before retrying can help if the server is just slow
                time.sleep(2) 
                continue # Force a retry
            logging.info("HS Code in URL is verified.")
            ### --- END OF FIX --- ###

            enforced = self._ensure_nvpm_view(desired_view_code=view_code)
            if not enforced:
                logging.warning("Could not enforce desired nvpm view. Retrying.")
                self._save_snapshot(f"world_nvpm_enforce_failed_attempt_{attempt}")
                continue
            
            try:
                self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                logging.info(f"SUCCESS: World page for view '{view}' is loaded and verified.")
                return True
            except TimeoutException:
                current = unquote(self.driver.current_url)
                logging.warning(f"Table not present yet. Current URL: {current}. Retrying.")
                self._save_snapshot(f"world_table_missing_attempt_{attempt}")

        logging.error(f"All {max_attempts} attempts failed for world view '{view}'.")
        return False

    def navigate_to_country_view_page(
        self, config: dict, country_id: str, trade_flow: str = "I", view: str = "value"
    ) -> bool:
        """Navigate to the country-timeseries page and strictly verify the country ID in the final URL."""
        max_attempts = 4
        hs_code = config.get("hs_code")
        trade_flow_code = "1" if trade_flow == "I" else "2"
        view_codes = {"value": "1", "quantity": "2", "unit_value": "3"}
        view_code = view_codes.get((view or "").lower(), "1")

        for attempt in range(1, max_attempts + 1):
            logging.info(
                f"--- COUNTRY VIEW ATTEMPT {attempt}/{max_attempts} for view '{view}' (Country ID: {country_id}) ---"
            )
            url = (
                f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?"
                f"nvpm=1|{country_id}||||{hs_code}|||2|1|1|{trade_flow_code}|2|1|2|{view_code}|1|1"
            )
            
            if not self.goto(url):
                logging.warning(f"goto() failed on attempt {attempt}. Retrying.")
                continue

            ### --- APPLYING THE SAME FIX HERE FOR CONSISTENCY --- ###
            nvpm_parts = self._get_nvpm_parts_from_url(self.driver.current_url)
            # For this URL, the country ID is at index 1.
            if not (nvpm_parts and len(nvpm_parts) > 1 and nvpm_parts[1] == str(country_id)):
                found_id = nvpm_parts[1] if (nvpm_parts and len(nvpm_parts) > 1) else "not found"
                logging.warning(
                    f"URL parameter mismatch on attempt {attempt}. Expected country ID '{country_id}', but found '{found_id}'. Retrying."
                )
                self._save_snapshot(f"country_id_mismatch_attempt_{attempt}")
                time.sleep(2)
                continue # Force a retry
            logging.info("Country ID in URL is verified.")
            ### --- END OF FIX --- ###

            enforced = self._ensure_nvpm_view(desired_view_code=view_code)
            if not enforced:
                logging.warning("Could not enforce desired nvpm view for country page. Retrying.")
                self._save_snapshot(f"country_nvpm_enforce_failed_attempt_{attempt}")
                continue
            
            try:
                self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                logging.info(f"SUCCESS: Country page for view '{view}' (Country ID: {country_id}) is loaded and verified.")
                return True
            except TimeoutException:
                current = unquote(self.driver.current_url)
                logging.warning(f"Table not present yet. Current URL: {current}. Retrying.")
                self._save_snapshot(f"country_table_missing_attempt_{attempt}")

        logging.error(f"All {max_attempts} attempts failed for country view '{view}' (Country ID: {country_id}).")
        return False

    # ... (rest of the file, including navigate_to_companies_page, _download_file, etc. remains unchanged) ...
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