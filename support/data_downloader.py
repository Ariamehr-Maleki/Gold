from typing import Optional
from urllib.parse import urlparse, parse_qs, quote, unquote
import time
import os
import glob
import difflib

from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
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

# New Constant for TS Dropdown based on your snippet
_TS_DROPDOWN_ID = "ctl00_NavigationControl_DropDownList_TS_Indicator"

class DataDownloader(TradeSpider):
    """
    Downloader that navigates TradeMap pages and reliably downloads exports.
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.official_product_name = None

    def get_selected_country_name(self) -> str:
        try:
            dropdown = self.driver.find_element(By.ID, _COUNTRY_DROPDOWN_ID)
            select = Select(dropdown)
            name = select.first_selected_option.text.strip()
            if "(" in name:
                name = name.split("(")[0].strip()
            logging.info(f"Detected country name from page: {name}")
            return name
        except Exception:
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
        Checks URL parameters. If country_id is passed as "" (empty string), 
        it strictly ensures the URL reflects the World view (no country selected).
        """
        # SKIP FIX FOR TS PAGES
        if "_TS" in expected_path_fragment:
            return False

        try:
            current_url = unquote(self.driver.current_url)
            if "ProductRev" in current_url: return False

            parsed = urlparse(current_url)
            params = parse_qs(parsed.query)
            
            nvpm_val = params.get('nvpm', [''])[0]
            if not nvpm_val: return False

            parts = nvpm_val.split('|')
            needs_fix = False
            
            # TradeMap NVPM structure usually has 11+ parts
            if len(parts) > 5:
                
                # --- 1. Check Country ID (Index 1) ---
                # If country_id is NOT None (e.g., it is "156" or ""), we check strict equality.
                if country_id is not None:
                    current_country_id = parts[1]
                    if current_country_id != country_id:
                        logging.warning(f"⚠️ Country ID Mismatch: Found '{current_country_id}' vs Expected '{country_id}'. Fixing...")
                        parts[1] = country_id
                        needs_fix = True
                
                # --- 2. Check Product Code (Index 5) ---
                current_product = parts[5]
                # If product in URL doesn't match config, or is 'TOTAL' (All products), force fix
                if current_product != hs_code:
                    logging.warning(f"⚠️ Product Mismatch: Found '{current_product}' vs Expected '{hs_code}'. Fixing...")
                    parts[5] = hs_code
                    # Ensure depth is 6 (HS6)
                    if len(parts) > 8: parts[8] = '6' 
                    needs_fix = True

            # --- 3. Redirect if needed ---
            path_match = expected_path_fragment.lower() in parsed.path.lower()
            
            if needs_fix or not path_match:
                new_nvpm = "|".join(parts)
                base_domain = f"{parsed.scheme}://{parsed.netloc}/"
                target_page = expected_path_fragment if expected_path_fragment.endswith(".aspx") else f"{expected_path_fragment}.aspx"
                new_url = f"{base_domain}{target_page}?nvpm={quote(new_nvpm, safe='')}"
                
                logging.info(f"🔄 Redirecting to correct page state: {new_url}")
                self.driver.get(new_url)
                return True
            
            return False
        except Exception as e:
            logging.warning(f"URL fix check failed: {e}")
            return False
        
    # --- VIEW HELPERS ---

    def _ensure_view_by_country(self) -> bool:
        """Ensures the breakdown is 'By Country' (Partner)."""
        # IDs that act as "Output Option" or "View Type"
        possible_ids = [
            "ctl00_NavigationControl_DropDownList_OutputOption", 
            "ctl00_NavigationControl_DropDownList_ViewType",
            "ctl00_PageContent_GridViewPanelControl_DropDownList_PageSize" # Sometimes page structure varies
        ]

        try:
            dropdown = None
            for pid in possible_ids:
                try: 
                    el = self.driver.find_element(By.ID, pid)
                    if el.is_displayed():
                        dropdown = el
                        break
                except: continue

            if not dropdown:
                return True # Assuming default is okay

            select = Select(dropdown)
            
            # Check if "ByCountry" exists as an option and select it
            try:
                # First check if we are already selected
                if select.first_selected_option.get_attribute("value") == "ByCountry":
                    return True
                
                select.select_by_value("ByCountry")
                logging.info("Switching View to 'By Country'...")
                time.sleep(1.5)
                self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
            except:
                pass # Option might not exist or already set
            return True
        except: return False

    def _ensure_ts_metric(self, view_mode: str) -> bool:
        """
        Switches the Time Series metric using the ID provided.
        Modes: 'value' -> 'V', 'unit_value' -> 'UV', 'quantity' -> 'Q'
        """
        mapping = {
            "value": "V",
            "quantity": "Q",
            "unit_value": "UV"
        }
        
        target_val = mapping.get(view_mode, "V")
        display_name = "Unit Value" if target_val == "UV" else "Value"

        try:
            # 1. Locate the TS Dropdown
            try:
                dropdown = self.driver.find_element(By.ID, _TS_DROPDOWN_ID)
            except NoSuchElementException:
                logging.warning(f"TS Indicator Dropdown ({_TS_DROPDOWN_ID}) not found.")
                return False

            select = Select(dropdown)
            current_val = select.first_selected_option.get_attribute("value")

            if current_val == target_val:
                logging.info(f"Metric is already '{display_name}' ({target_val}).")
                return True

            logging.info(f"🔄 Switching Metric to '{display_name}' ({target_val})...")
            select.select_by_value(target_val)
            
            # Wait for PostBack/Reload
            time.sleep(2)
            try:
                self.wait.until(EC.staleness_of(dropdown))
            except: pass
            
            self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
            return True

        except Exception as e:
            logging.error(f"Failed to switch metric: {e}")
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

    # --- PIPELINES ---

    def _run_navigation_pipeline(self, url: str, hs_code: str, expected_path: str, step_name: str, country_id: str = None) -> bool:
        logging.info(f"--- {step_name} ---")
        try:
            self.driver.get(url)
            time.sleep(2)
        except: pass

        if self._resolve_product_revision(hs_code):
            time.sleep(2)

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

    def _run_ts_pipeline(self, url: str, step_name: str, view_mode: str) -> bool:
        """
        TS Pipeline: Navigate -> Check Grid -> Switch Dropdown -> Check Country Breakdown
        """
        logging.info(f"--- {step_name} ---")
        try:
            self.driver.get(url)
            time.sleep(2)
        except: pass

        # 1. Grid Check (Wait for load)
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
        except:
            logging.error(f"❌ Grid failed to load initially for: {step_name}")
            return False

        # 2. Force Metric (Value vs Unit Value) using the new TS Dropdown logic
        if not self._ensure_ts_metric(view_mode):
            logging.warning(f"Could not enforce metric '{view_mode}'. Data may be incorrect.")

        # 3. Ensure Breakdown
        self._ensure_view_by_country()

        # 4. Period
        self._ensure_latest_period()
        
        logging.info(f"✅ Loaded: {step_name}")
        return True

    # =========================================================================
    # PUBLIC NAVIGATION METHODS
    # =========================================================================

    def navigate_to_global_exports(self, config: dict) -> bool:
        hs = config.get("hs_code")
        path = "Country_SelProduct.aspx"
        # Index 1 is empty || -> World View
        nvpm = f"1|||||{hs}|||6|1|1|2|1|2|1||1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        
        # CHANGED: Pass country_id="" to force World View validation
        return self._run_navigation_pipeline(url, hs, "Country_SelProduct", "Step 1: Global Exports", country_id="")
    
    def navigate_to_global_imports(self, config: dict) -> bool:
        hs = config.get("hs_code")
        path = "Country_SelProduct.aspx"
        nvpm = f"1|||||{hs}|||6|1|1|1|1|1|2|1||1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs, "Country_SelProduct", "Step 1.5: Global Imports")
    
    def navigate_to_base_country_global_exports(self, config: dict) -> bool:
        hs = config.get("hs_code")
        cid = config.get("your_country_id")
        path = "Country_SelProductCountry.aspx"
        nvpm = f"1|{cid}||||{hs}|||6|1|2|2|1|1|2|1|1|1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs, "Country_SelProductCountry", f"Step 3: Base Country {cid} Exports", country_id=cid)
    
    def navigate_to_country_snapshot_page(self, config: dict, country_id: str) -> bool:
        hs = config.get("hs_code")
        path = "Country_SelProductCountry.aspx"
        nvpm = f"1|{country_id}||||{hs}|||6|1|1|1|2|1|2|1|1|1"
        url = f"https://www.trademap.org/{path}?nvpm={quote(nvpm, safe='')}"
        return self._run_navigation_pipeline(url, hs, "Country_SelProductCountry", f"Step 2: Target Country {country_id}", country_id=country_id)

    # =========================================================================
    # TIME SERIES NAVIGATION (With Dropdown Switch)
    # =========================================================================

    def navigate_to_world_view_page(self, config: dict, view: str = "value") -> bool:
        """
        Global Trends (Product View). 
        Navigate to base page, then switch to 'view'.
        """
        hs = config.get("hs_code")
        # Base NVPM (defaults to value usually, or whatever works to load page)
        # Use a "Value" NVPM by default (Code 1 or V logic internal)
        # URL structure matches 'Product_SelProduct_TS'
        # Note: We rely on _ensure_ts_metric to flip to UV if needed.
        nvpm = f"1|||||{hs}|||6|1|1|2|1||2|1||1" 
        url = f"https://www.trademap.org/Product_SelProduct_TS.aspx?nvpm={quote(nvpm, safe='')}"
        
        return self._run_ts_pipeline(url, f"Step 6A: World TS ({view})", view)

    def navigate_to_country_view_page(self, config: dict, country_id: str, view: str = "value", trade_flow: str = "import") -> bool:
        """
        Country Specific Trends (Time Series).
        Args:
            trade_flow: 'import' (for Target Market) or 'export' (for Base Country).
        """
        hs = config.get("hs_code")
        
        # --- NVPM Construction Logic ---
        # We must change the NVPM string to select Import vs Export
        if trade_flow.lower() == "export":
            # Flow code 2 (Export)
            # Pattern: ...|6|1|2|2|... implies Export
            nvpm = f"1|{country_id}||||{hs}|||6|1|2|2|2|1|2|1|1|1"
            label = "Exports"
        else:
            # Flow code 1 (Import) - Default
            # Pattern: ...|6|1|1|1|... implies Import
            nvpm = f"1|{country_id}||||{hs}|||6|1|1|1|2|1|2|1|1|1"
            label = "Imports"

        url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm={quote(nvpm, safe='')}"
        
        step_desc = f"TS: Country {country_id} ({label}) - {view}"
        return self._run_ts_pipeline(url, step_desc, view)
    
    # =========================================================================
    # HELPERS
    # =========================================================================

    def navigate_to_companies_page(self, config: dict, country_id: str = None, trade_flow: str = 'I') -> bool:
        target_id = country_id if country_id else config.get('target_market_id')
        product_code = config.get('hs_code')
        trade_flow_code = '1' if trade_flow == 'I' else '2' 
        
        logging.info(f"Navigating to Companies page for {target_id}...")
        for _ in range(3):
            nvpm = f"1|{target_id}||||{product_code}|||4|1|1|{trade_flow_code}|3|1|1|1|1|4"
            url = f"https://www.trademap.org/CompaniesList.aspx?nvpm={quote(nvpm, safe='')}"
            self.driver.get(url)
            time.sleep(3) 

            # Fix intermediate mapping page
            if "CorrespondingProductsCompanies.aspx" in self.driver.current_url:
                try:
                    self.wait.until(EC.visibility_of_element_located((By.ID, _MAIN_TABLE_ID)))
                    try:
                        xpath = f"//select[@id='ctl00_NavigationControl_DropDownList_Product']/option[@value='{product_code}']"
                        el = self.driver.find_element(By.XPATH, xpath)
                        raw = el.text
                        self.official_product_name = raw.split("-",1)[1].strip() if "-" in raw else raw.strip()
                    except: pass
                    links = self.driver.find_elements(By.CSS_SELECTOR, "a[id*='LinkButton_CompanyProduct']")
                    if links: links[0].click(); time.sleep(2)
                except: pass
            
            if "CompaniesList.aspx" in self.driver.current_url:
                try:
                    self.wait.until(EC.presence_of_element_located((By.ID, _MAIN_TABLE_ID)))
                    return True
                except: pass
        return False

    def download_companies_file(self, rename_to: str) -> str:
        self._clean_download_dir()
        btns = ["ctl00_PageContent_GridViewPanelControl_ImageButton_ExportExcel", 
                "ctl00_PageContent_GridViewPanelControl_ImageButton_ExportText"]
        found = None
        for b in btns:
            try: found = self.driver.find_element(By.ID, b); break
            except: continue
        
        if found:
            self.driver.execute_script("arguments[0].click();", found)
            return self._wait_for_download(rename_to)
        return None

    def download_excel_file(self, rename_to: str, hs_code=None, country_id=None) -> str:
        self._clean_download_dir()
        try:
            self.driver.execute_script("window.scrollTo(0,0);")
            btn = self.wait.until(EC.element_to_be_clickable((By.ID, _EXCEL_BTN_ID)))
            self.driver.execute_script("arguments[0].click();", btn)
            return self._wait_for_download(rename_to)
        except Exception as e:
            logging.error(f"Download error: {e}")
            return None

    def _clean_download_dir(self):
        for pat in ["*.xls*", "*.xlsx*", "*.txt", "*.csv"]:
            for f in glob.glob(os.path.join(self.download_dir, pat)):
                try: os.remove(f)
                except: pass

    def _wait_for_download(self, rename_to: str) -> str:
        timeout = 60
        start = time.time()
        while time.time() - start < timeout:
            files = []
            for pat in ["*.xls*", "*.xlsx*", "*.txt", "*.csv"]:
                files.extend(glob.glob(os.path.join(self.download_dir, pat)))
            if files:
                latest = max(files, key=os.path.getmtime)
                if not any(x in latest for x in ['.part', '.crdownload']):
                     if os.path.getsize(latest) > 0:
                         base, ext = os.path.splitext(latest)
                         fext = os.path.splitext(rename_to)[1] or ext
                         final = os.path.join(self.download_dir, os.path.splitext(rename_to)[0] + fext)
                         if os.path.exists(final): os.remove(final)
                         os.rename(latest, final)
                         logging.info(f"✅ Downloaded: {os.path.basename(final)}")
                         return final
            time.sleep(1)
        return None