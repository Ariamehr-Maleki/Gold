from typing import Optional
from urllib.parse import urlparse, parse_qs, quote, unquote
import time
import os
import glob
import difflib  # Needed for name matching

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
# IMPORTANT: Add WebDriverWait here 👇
from selenium.webdriver.support.ui import Select, WebDriverWait 
from selenium.common.exceptions import (
    TimeoutException,
    NoSuchElementException,
    StaleElementReferenceException
)

from support.spider_core import TradeSpider, logging

# Constants
_MAIN_TABLE_ID = "ctl00_PageContent_MyGridView1"
_NEXT_BTN_ID = "ctl00_PageContent_GridViewPanelControl_ImageButton_Next"
_DROPDOWN_ID = "ctl00_NavigationControl_DropDownList_OutputOption"
_EXCEL_BTN_ID = "ctl00_PageContent_GridViewPanelControl_ImageButton_ExportExcel"
_COUNTRY_DROPDOWN_ID = "ctl00_NavigationControl_DropDownList_Country"

class DataDownloader(TradeSpider):
    """
    Downloader that navigates TradeMap pages and reliably downloads exports.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Capture the official product name when a clarification/selection page provides it
        self.official_product_name = None

    def get_selected_country_name(self) -> str:
        """
        Extracts the currently selected country name from the dropdown.
        Useful for dynamic configuration updates.
        """
        try:
            # Method 1: Try the Country Dropdown
            dropdown = self.driver.find_element(By.ID, _COUNTRY_DROPDOWN_ID)
            select = Select(dropdown)
            name = select.first_selected_option.text.strip()
            # Remove revision notes often found in names like "China (excludes HK...)"
            if "(" in name:
                name = name.split("(")[0].strip()
            logging.info(f"Detected country name from page: {name}")
            return name
        except Exception:
            # Method 2: Fallback to page title parsing
            try:
                header = self.driver.find_element(By.XPATH, "//center/b").text
                if "imported by" in header:
                    return header.split("imported by")[1].split("in")[0].strip()
                if "exported by" in header:
                    return header.split("exported by")[1].split("in")[0].strip()
            except Exception:
                pass
            
            logging.warning("Could not detect country name from page.")
            return None

    def _resolve_product_revision(self, hs_code: str) -> bool:
        """
        Handles the 'ProductRev_SelProduct' page (Clarification page).
        """
        if "ProductRev" not in self.driver.current_url:
            return False

        logging.info(f"⚠️ Landed on Product Revision page. Attempting to select HS {hs_code}...")
        try:
            xpath = f"//a[contains(text(), '{hs_code}')]"
            links = self.driver.find_elements(By.XPATH, xpath)
            
            if links:
                logging.info(f"Found link for {hs_code}. Clicking...")
                self.driver.execute_script("arguments[0].click();", links[0])
                time.sleep(3)
                self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                return True
            return False
        except Exception as e:
            logging.error(f"Failed to resolve product revision: {e}")
            return False

    def _fix_url_state(self, hs_code: str, expected_path_fragment: str, country_id: str = None) -> bool:
        """
        Checks URL parameters for both Product Code and Country ID validity.
        """
        try:
            current_url = unquote(self.driver.current_url)
            if "ProductRev" in current_url:
                return False

            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            
            # 1. Check Path
            if expected_path_fragment.lower() not in parsed.path.lower():
                logging.warning(f"Path Mismatch: Current '{parsed.path}' != Target '{expected_path_fragment}'")
                # We return True to force a reload if path is wrong
                # But actual redirection logic happens if needs_fix is True below
            
            nvpm_val = params.get('nvpm', [''])[0]
            if not nvpm_val: return False

            parts = nvpm_val.split('|')
            needs_fix = False
            
            # 2. Check Parameters (Country ID and HS Code)
            if len(parts) > 8:
                # -- Check Country ID (Index 1) --
                if country_id:
                    current_country_id = parts[1]
                    if current_country_id != country_id:
                        logging.warning(f"⚠️ Country ID Mismatch: Found '{current_country_id}'. Expected '{country_id}'. Fixing...")
                        parts[1] = country_id
                        needs_fix = True

                # -- Check Product Code (Index 5) and Depth (Index 8) --
                current_product = parts[5]
                current_depth = parts[8]
                if current_product == 'TOTAL' or current_product != hs_code or current_depth != '6':
                    logging.warning(f"⚠️ Product/Depth Mismatch: Found {current_product}/{current_depth}. Expected {hs_code}/6. Fixing...")
                    parts[5] = hs_code
                    parts[8] = '6'
                    needs_fix = True

            # 3. Redirect if needed
            if needs_fix or (expected_path_fragment.lower() not in parsed.path.lower()):
                new_nvpm = "|".join(parts)
                base_domain = f"{parsed.scheme}://{parsed.netloc}/"
                # Handle .aspx extension logic
                target_page = expected_path_fragment if expected_path_fragment.endswith(".aspx") else f"{expected_path_fragment}.aspx"
                new_url = f"{base_domain}{target_page}?nvpm={quote(new_nvpm, safe='')}"
                
                logging.info(f"🔄 Redirecting to correct page state: {new_url}")
                self.driver.get(new_url)
                return True
            
            return False
        except Exception as e:
            logging.warning(f"URL fix check failed: {e}")
            return False

    def _ensure_view_by_country(self) -> bool:
        try:
            try:
                dropdown = self.driver.find_element(By.ID, _DROPDOWN_ID)
            except NoSuchElementException:
                return True

            select_obj = Select(dropdown)
            if select_obj.first_selected_option.get_attribute("value") == "ByCountry":
                return True

            logging.info("Switching to 'ByCountry'...")
            select_obj.select_by_value("ByCountry")
            time.sleep(1.5)
            self.wait.until(EC.visibility_of_element_located((By.ID, _MAIN_TABLE_ID)))
            return True
        except:
            return False

    def _ensure_latest_period(self):
        try:
            next_btn = self.driver.find_element(By.ID, _NEXT_BTN_ID)
            if "NextArrow_off" in next_btn.get_attribute("src") or next_btn.get_attribute("disabled"):
                return
            logging.info("Clicking 'Next Period'...")
            self.driver.execute_script("arguments[0].click();", next_btn)
            time.sleep(2)
            self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
        except: pass

    def _run_navigation_pipeline(self, url: str, hs_code: str, expected_path: str, step_name: str, country_id: str = None) -> bool:
        logging.info(f"--- {step_name} ---")
        try:
            self.driver.get(url)
            time.sleep(2)
        except: pass

        if self._resolve_product_revision(hs_code):
            time.sleep(2)

        # Pass country_id to _fix_url_state to enforce strict country checking
        if self._fix_url_state(hs_code, expected_path, country_id=country_id):
            time.sleep(2)
            self._resolve_product_revision(hs_code)

        try:
            self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
        except:
            logging.error(f"❌ Grid failed to load for: {step_name}")
            return False

        self._ensure_view_by_country()
        self._ensure_latest_period()
        logging.info(f"✅ Loaded: {step_name}")
        return True

    # =========================================================================
    # PUBLIC NAVIGATION METHODS
    # =========================================================================

    def navigate_to_global_exports(self, config: dict) -> bool:
        """
        Formerly 'navigate_to_world_snapshot_page'.
        Ensures we are downloading the List of Exporters (Global Exports).
        """
        hs_code = config.get("hs_code")
        path = "Country_SelProduct.aspx"
        # NVPM Breakdown: ...|6|1|1|1|2|1|2|1|1|1
        # Index 10 is '2' for Exports
        nvpm = f"1|||||{hs_code}|||6|1|1|1|2|1|2|1|1|1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs_code, "Country_SelProduct", "Step 1: Global Exports")

    def navigate_to_global_imports(self, config: dict) -> bool:
        """
        New step for Global Imports (List of Importers).
        """
        hs_code = config.get("hs_code")
        path = "Country_SelProduct.aspx"
        # User provided URL NVPM: ...|6|1|1|1|1|1|2|1|1|1
        # Index 10 is '1' for Imports
        nvpm = f"1|||||{hs_code}|||6|1|1|1|1|1|2|1|1|1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs_code, "Country_SelProduct", "Step 1.5: Global Imports")
    
    def navigate_to_base_country_global_exports(self, config: dict) -> bool:
        hs_code = config.get("hs_code")
        country_id = config.get("your_country_id")
        path = "Country_SelProductCountry.aspx"
        nvpm = f"1|{country_id}||||{hs_code}|||6|1|2|2|1|1|2|1|1|1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs_code, "Country_SelProductCountry", f"Step 3: Base Country {country_id} Exports", country_id=country_id)
    
    def navigate_to_global_imports(self, config: dict) -> bool:
        hs_code = config.get("hs_code")
        path = "Country_SelProduct.aspx"
        # User provided specific NVPM for Global Imports
        nvpm = f"1|||||{hs_code}|||6|1|1|1|1|1|2|1|1|1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs_code, "Country_SelProduct", "Step 1.5: Global Imports")

    def navigate_to_companies_page(self, config: dict, country_id: str = None, trade_flow: str = 'I') -> bool:
        target_id = country_id if country_id else config.get('target_market_id')
        product_code = config.get('hs_code')
        trade_flow_code = '1' if trade_flow == 'I' else '2' 
        max_attempts = 4
        
        logging.info(f"Navigating to Companies page ({'Importers' if trade_flow=='I' else 'Exporters'}) for {target_id}...")

        for attempt in range(1, max_attempts + 1):
            redirect_handled = False 
            nvpm = f"1|{target_id}||||{product_code}|||4|1|1|{trade_flow_code}|3|1|1|1|1|4"
            url = f"https://www.trademap.org/CompaniesList.aspx?nvpm={quote(nvpm, safe='')}"
            
            self.driver.get(url)
            time.sleep(3) 

            # --- REDIRECT HANDLING (CLARIFICATION PAGE) ---
            if "CorrespondingProductsCompanies.aspx" in self.driver.current_url:
                logging.warning("Redirected to clarification page. Resolving best product match...")
                try:
                    self.wait.until(EC.visibility_of_element_located((By.ID, _MAIN_TABLE_ID)))
                    
                    # 1. Identify Official Product Name from Dropdown
                    official_name = ""
                    try:
                        # Direct XPath is faster than iterating options
                        opt_xpath = f"//select[@id='ctl00_NavigationControl_DropDownList_Product']/option[@value='{product_code}']"
                        option_elem = self.driver.find_element(By.XPATH, opt_xpath)
                        raw_text = option_elem.text # e.g. "... ... 080410 - Fresh or dried dates"
                        
                        # Clean the text (Remove dots and code)
                        # Split by " - " and take the last part usually
                        if " - " in raw_text:
                            official_name = raw_text.split(" - ", 1)[1].strip()
                        else:
                            official_name = raw_text.strip()
                        
                        # Store for later use by other parts of the pipeline
                        self.official_product_name = official_name
                        logging.info(f"Identified official product name: '{official_name}'")
                    except Exception:
                        logging.warning(f"Could not find official name for HS {product_code} in dropdown.")

                    # 2. Find all candidate links
                    links = self.driver.find_elements(By.CSS_SELECTOR, "a[id*='LinkButton_CompanyProduct']")
                    best_link = None
                    highest_score = 0.0

                    if links:
                        # 3. Score links based on similarity to official name
                        for link in links:
                            link_text = link.text.strip()
                            score = 0.0
                            
                            # A. Exact HS code match gets a huge boost
                            if product_code in link_text:
                                score += 0.5
                            
                            # B. String similarity match
                            if official_name:
                                sim_ratio = difflib.SequenceMatcher(None, official_name.lower(), link_text.lower()).ratio()
                                score += sim_ratio
                            
                            logging.info(f"Candidate: '{link_text}' | Score: {score:.2f}")
                            
                            if score > highest_score:
                                highest_score = score
                                best_link = link
                        
                        # Fallback: If no scoring worked, take the first one
                        if not best_link:
                            best_link = links[0]

                        logging.info(f"Clicking best match: '{best_link.text}'")
                        self.driver.execute_script("arguments[0].click();", best_link)
                        
                        WebDriverWait(self.driver, 15).until(EC.url_contains("CompaniesList.aspx"))
                        time.sleep(2)
                        redirect_handled = True 
                    else:
                        logging.error("No product links found to click.")

                except Exception as e:
                    logging.error(f"Failed to handle clarification redirect: {e}")
                    continue

            # --- VERIFICATION ---
            if "CompaniesList.aspx" not in self.driver.current_url:
                logging.warning(f"Attempt {attempt}: Not on CompaniesList.aspx. Retrying...")
                continue

            if not redirect_handled:
                current_nvpm = self._get_nvpm_parts_from_url(self.driver.current_url)
                if current_nvpm and len(current_nvpm) > 1:
                    # Note: TradeMap sometimes bugs out on country ID persistence, check strictly
                    if current_nvpm[1] != str(target_id):
                        logging.warning(f"Wrong Country ID {current_nvpm[1]} detected. Retrying...")
                        continue

            # --- SUCCESS CHECK ---
            try:
                self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                logging.info(f"✅ Landed on Companies List (Country {target_id}).")
                return True
            except TimeoutException:
                logging.warning("Companies table did not load yet.")

        return False
    
    # =========================================================================
    # IMPROVED DOWNLOAD LOGIC
    # =========================================================================

    def _get_nvpm_parts_from_url(self, url: str) -> list:
        try:
            parsed = urlparse(unquote(url))
            params = parse_qs(parsed.query)
            nvpm = params.get('nvpm', [''])[0]
            return nvpm.split('|') if nvpm else []
        except:
            return []
        
    # support/data_downloader.py

    def download_companies_file(self, rename_to: str) -> str:
        """
        Downloads the companies list, prioritizing the Excel button.
        """
        # 1. Clear old files to prevent confusion
        for pat in ["*.xls*", "*.txt", "*.csv"]:
            for f in glob.glob(os.path.join(self.download_dir, pat)):
                try: os.remove(f)
                except: pass

        # 2. Define Button Selectors (Prioritizing the user's provided Excel ID)
        excel_btn_id = "ctl00_PageContent_GridViewPanelControl_ImageButton_ExportExcel"
        text_btn_id = "ctl00_PageContent_GridViewPanelControl_ImageButton_ExportText"
        
        btn = None
        try:
            # Try finding the Excel button first
            logging.info("Looking for Excel download button...")
            btn = self.wait.until(EC.element_to_be_clickable((By.ID, excel_btn_id)))
        except:
            try:
                # Fallback to Text button if Excel isn't there
                logging.warning("Excel button not found. Looking for Text button...")
                btn = self.wait.until(EC.element_to_be_clickable((By.ID, text_btn_id)))
            except:
                logging.error("❌ No download button found.")
                return None

        # 3. Click the button
        try:
            logging.info("Clicking download...")
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        except Exception as e:
            logging.error(f"Click failed: {e}")
            return None

        # 4. Wait for the file (Supporting both .xls and .txt)
        timeout = 60
        start_time = time.time()
        while time.time() - start_time < timeout:
            files = []
            for pat in ["*.xls*", "*.txt", "*.csv"]:
                files.extend(glob.glob(os.path.join(self.download_dir, pat)))
            
            if files:
                latest = max(files, key=os.path.getmtime)
                # Ignore partial downloads
                if not any(x in latest for x in ['.part', '.crdownload', '.tmp']):
                    if os.path.getsize(latest) > 0:
                        # Determine correct extension for rename
                        ext = os.path.splitext(latest)[1]
                        final_name = os.path.splitext(rename_to)[0] + ext
                        
                        new_path = os.path.join(self.download_dir, final_name)
                        if os.path.exists(new_path): os.remove(new_path)
                        os.rename(latest, new_path)
                        
                        logging.info(f"✅ Downloaded Company Data: {final_name}")
                        return new_path
            time.sleep(1)
        
        logging.error("❌ Download timed out.")
        return None
    
      # [RESTORE THIS METHOD]
    def navigate_to_country_snapshot_page(self, config: dict, country_id: str) -> bool:
        hs_code = config.get("hs_code")
        path = "Country_SelProductCountry.aspx"
        # NVPM for Target Market Imports
        nvpm = f"1|{country_id}||||{hs_code}|||6|1|1|1|2|1|2|1|1|1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs_code, "Country_SelProductCountry", f"Step 2: Target Country {country_id}", country_id=country_id)

    # [RESTORE THIS METHOD]
    def navigate_to_base_country_global_exports(self, config: dict) -> bool:
        hs_code = config.get("hs_code")
        country_id = config.get("your_country_id")
        path = "Country_SelProductCountry.aspx"
        # NVPM for Base Country Exports
        nvpm = f"1|{country_id}||||{hs_code}|||6|1|2|2|1|1|2|1|1|1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs_code, "Country_SelProductCountry", f"Step 3: Base Country {country_id} Exports", country_id=country_id)
    
    def download_excel_file(self, rename_to: str, hs_code: str = None, country_id: str = None) -> str:
        """
        Final check and download. 
        Supports checking both HS Code and Country ID before clicking download.
        """
        # One last check before clicking download to ensure we didn't drift
        if hs_code:
            # We assume Country_SelProductCountry if a country_id is present, else Country_SelProduct
            expected_page = "Country_SelProductCountry" if country_id else "Country_SelProduct"
            self._fix_url_state(hs_code, expected_page, country_id=country_id)
            
        try:
            self.wait.until(EC.visibility_of_element_located((By.ID, _MAIN_TABLE_ID)))
        except:
            logging.warning("Grid not visible, attempting download anyway...")

        return self._download_file(rename_to=rename_to, clean_dir=False, file_type="excel")

    def _download_file(self, rename_to: str = None, clean_dir: bool = True, file_type: str = "excel") -> str:
        if clean_dir:
            for pat in ["*.xls*", "*.xlsx*", "*.txt*"]:
                for f in glob.glob(os.path.join(self.download_dir, pat)):
                    try: os.remove(f)
                    except: pass

        selector = (By.ID, "ctl00_PageContent_GridViewPanelControl_ImageButton_ExportExcel")

        try:
            self.driver.execute_script("window.scrollTo(0, 0);")
            time.sleep(1)
            btn = self.wait.until(EC.element_to_be_clickable(selector))
            logging.info(f"Clicking Download...")
            self.driver.execute_script("arguments[0].click();", btn)
            time.sleep(3)
        except Exception as e:
            logging.error(f"Download click failed: {e}")
            return None

        # Wait for file
        timeout = 120
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            files = []
            for pat in ["*.xls*", "*.xlsx*"]:
                files.extend(glob.glob(os.path.join(self.download_dir, pat)))
            
            if files:
                latest_file = max(files, key=os.path.getmtime)
                if not any(x in latest_file for x in ['.part', '.crdownload', '.tmp']):
                    try:
                        if os.path.getsize(latest_file) > 0:
                            if rename_to:
                                time.sleep(1)
                                new_path = os.path.join(self.download_dir, rename_to)
                                if os.path.exists(new_path): os.remove(new_path)
                                os.rename(latest_file, new_path)
                                logging.info(f"✅ Downloaded: {rename_to}")
                                return new_path
                            return latest_file
                    except: pass
            time.sleep(2)
        
        logging.error("❌ Download timed out.")
        return None