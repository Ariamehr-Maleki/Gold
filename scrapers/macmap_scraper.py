# scrapers/macmap_scraper.py

import argparse
import json
import logging
import os
import sys
import time

# Selenium Imports
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, StaleElementReferenceException

# Path setup
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

# Import support modules
from support.spider_core import TradeSpider
from support.macmap_parser import parse_macmap_html
from support.macmap_formatter import MacMapReportBuilder 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - MACMAP - %(levelname)s - %(message)s')

class MacMapScraper(TradeSpider):
    
    def handle_popup(self):
        """Closes the subscription popup if it appears."""
        try:
            # Wait specifically for the popup or continue if not found
            popup_btn = WebDriverWait(self.driver, 5).until(EC.element_to_be_clickable((By.ID, "hidePopup")))
            popup_btn.click()
            time.sleep(1)
        except TimeoutException:
            pass
        except Exception:
            pass

    def _wait_for_loading_overlay(self):
        """Waits for the 'processing' overlay (spinner) to appear and then disappear."""
        try:
            # Wait briefly for overlay to appear (it might happen instantly)
            WebDriverWait(self.driver, 2).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".blockUI, .loading, .spinner"))
            )
            # If it appeared, wait up to 15s for it to vanish
            WebDriverWait(self.driver, 15).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, ".blockUI, .loading, .spinner"))
            )
        except TimeoutException:
            pass # Overlay didn't appear or didn't disappear (rely on subsequent DOM checks)
        except Exception:
            pass

    def _wait_for_table(self):
        """Robustly waits for the data table rows to populate with real data."""
        start_time = time.time()
        timeout = 60
        
        while time.time() - start_time < timeout: 
            try:
                rows = self.driver.find_elements(By.CSS_SELECTOR, "#custom-duties-results table tbody tr")
                # Ensure we have rows and they aren't empty placeholders
                if len(rows) > 0 and rows[0].text.strip() != "":
                    # Double check that we don't have a "Loading..." text row
                    if "oading" not in rows[0].text:
                        return True
                
                # Fast fail if explicit "No data" message exists
                if "No data available" in self.driver.page_source:
                    return False
            except StaleElementReferenceException:
                # DOM updated mid-check, retry
                continue
            except Exception: 
                pass
            time.sleep(0.5)
        return False

    def _wait_for_initial_page_load(self):
        """
        Blocks execution until the browser confirms the page is 'complete'.
        Then attempts to verify critical elements without crashing.
        """
        logging.info("Waiting for page stabilization...")
        try:
            # 1. Generic Browser Load Check (The "Is page still loading?" check)
            # This waits for the browser's own 'stop' signal (spinner in tab stops)
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            # 2. Wait for Body
            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            # 3. Wait for any overlay to vanish
            self._wait_for_loading_overlay()

            # 4. "Soft" Check for Dropdown (Critical but we won't crash here)
            try:
                WebDriverWait(self.driver, 15).until(
                    EC.presence_of_element_located((By.ID, "ntlc-product-list"))
                )
            except TimeoutException:
                logging.warning("Warning: Product dropdown (ntlc-product-list) not detected yet. Proceeding anyway...")

            # 5. Handle Popup
            self.handle_popup()
            
            logging.info("Page fully loaded (readyState=complete). Waiting 10s buffer...")
            time.sleep(10) # <--- ADDED FIX WAIT
            return True

        except TimeoutException:
            logging.error("Timed out waiting for document.readyState to be complete.")
            return False
        except Exception as e:
            logging.warning(f"Error during initial load wait: {e}")
            return False

    def _expand_agreement_details(self):
        """
        Clicks all 'Trade agreement details' links to reveal hidden Rows/Divs.
        Forces click regardless of class state and waits for '#fta-result' or similar to appear.
        """
        try:
            # 1. Find all toggle links based on text content
            links = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'Trade agreement details')]")
            
            clicked_something = False
            for link in links:
                try:
                    if link.is_displayed():
                        # Force click via JS to bypass potential overlays/class checks
                        self.driver.execute_script("arguments[0].click();", link)
                        clicked_something = True
                except Exception:
                    continue
            
            # 2. If we clicked, WAIT for the content to visibly load in the DOM
            if clicked_something:
                try:
                    # Wait for the specific container IDs you identified (fta-result or result-fta)
                    WebDriverWait(self.driver, 5).until(
                        EC.visibility_of_any_elements_located((By.CSS_SELECTOR, "#fta-result, .result-fta, .agreement-detail"))
                    )
                except TimeoutException:
                    logging.warning("Expanded details link clicked, but content did not appear.")
                
                # Small buffer for animation completion
                logging.info("Details expanded. Waiting 10s buffer...")
                time.sleep(10) # <--- ADDED FIX WAIT
                
        except Exception as e:
            logging.warning(f"Error expanding details: {e}")

    def _get_ntl_options(self):
        """Parses the dropdown to get the list of sub-products (National Tariff Lines)."""
        try:
            select_elem = self.driver.find_element(By.ID, "ntlc-product-list")
            options = select_elem.find_elements(By.TAG_NAME, "option")
            ntl_list = []
            for opt in options:
                code = opt.get_attribute("value")
                text = opt.text
                if code and code != "0": 
                    desc = text.split('–', 1)[1].strip() if '–' in text else text
                    ntl_list.append({"code": code, "desc": desc})
            return ntl_list
        except NoSuchElementException:
            return []

    def _select_ntl_code(self, ntl_code):
        """
        Selects the NTL code and explicitly waits for the DOM to update (old rows to disappear).
        Replaces the buggy jQuery wait with a visual Staleness check.
        """
        try:
            # 1. Capture the state of the CURRENT table rows before we trigger change
            # This helps us verify that the table actually refreshes
            old_rows = self.driver.find_elements(By.CSS_SELECTOR, "#custom-duties-results table tbody tr")
            old_ref = old_rows[0] if old_rows else None

            # 2. Trigger the change via JavaScript
            script = f"""
                var $select = $('#ntlc-product-list');
                $select.val('{ntl_code}');
                $select.trigger('chosen:updated'); 
                $select.trigger('change');
            """
            self.driver.execute_script(script)
            
            # 3. Wait for the 'Processing' overlay
            self._wait_for_loading_overlay()

            # 4. Critical: Wait for the OLD row to detach (Staleness)
            # This ensures we don't accidentally scrape the previous screen's data
            if old_ref:
                try:
                    # Wait up to 5 seconds for the old row to be removed
                    WebDriverWait(self.driver, 5).until(EC.staleness_of(old_ref))
                except TimeoutException:
                    logging.warning(f"NTL {ntl_code}: Table rows did not detach (DOM update might be stuck).")

            # 5. Wait for the NEW table to populate
            if not self._wait_for_table():
                logging.warning(f"NTL {ntl_code}: New table did not load within timeout.")
                return False

            # 6. Safety Buffer for rendering text/animations
            logging.info("NTL selected. Waiting 10s buffer...")
            time.sleep(10) # <--- ADDED FIX WAIT
            
            return True
        except Exception as e:
            logging.error(f"Failed to select NTL {ntl_code}: {e}")
            return False

    # scrapers/macmap_scraper.py

    # 1. Update the scraping method to accept a limit flag
    def scrape_all_lines_for_country(self, reporter_id, partner_id, hs_code, master_ntl_list=None, single_line_only=False):
        base_url = f"https://www.macmap.org/en/query/results?reporter={reporter_id}&partner={partner_id}&product={hs_code}&level=6"
        
        logging.info(f"Navigating to {base_url}")
        if not self.goto(base_url): 
            logging.error(f"Failed to load URL for Partner {partner_id}")
            return {}, []
            
        # ... [Initial Load Barrier Code remains the same] ...
        if not self._wait_for_initial_page_load():
            return {}, []
        
        # ... [Dropdown Population Code remains the same] ...
        if not master_ntl_list:
            # (Keep existing logic to get master_ntl_list)
            try:
                self.wait.until(EC.presence_of_element_located((By.ID, "ntlc-product-list")))
                self.wait.until(lambda driver: len(driver.find_elements(By.CSS_SELECTOR, "#ntlc-product-list option")) > 0)
                time.sleep(3)
                master_ntl_list = self._get_ntl_options()
            except Exception:
                master_ntl_list = self._get_ntl_options()
                if not master_ntl_list: return {}, []

        results_by_line = {} 
        
        # Optimized Loop
        total = len(master_ntl_list)
        for i, item in enumerate(master_ntl_list):
            
            # --- NEW OPTIMIZATION ---
            if single_line_only and i > 0:
                logging.info(f"[{partner_id}] Single line mode active. Stopping after first line.")
                break
            # ------------------------

            code = item['code']
            logging.info(f"   [{partner_id}] Processing line {i+1}/{total}: {code}")
            
            if not self._select_ntl_code(code): continue
            
            if self._wait_for_table():
                self._expand_agreement_details()

            try:
                full_html = self.driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
                results_by_line[code] = parse_macmap_html(full_html)
            except Exception as e:
                logging.error(f"Error parsing line {code}: {e}")

        return results_by_line, master_ntl_list

    # 2. Update the logic to use this flag for the 'other' suppliers
    def run_comparison_logic(self, config):
        target_id = config['target_market_id']
        your_id = config['your_country_id']
        comp_ids = config.get('competitor_ids', [])
        other_ids = config.get('other_supplier_ids', []) # Get the new IDs
        hs_code = config['hs_code']

        # 1. Scrape YOUR COUNTRY (All lines)
        logging.info(f"--- Scraping Base Country: {your_id} ---")
        your_data_map, master_ntl_list = self.scrape_all_lines_for_country(target_id, your_id, hs_code)
        
        if not master_ntl_list:
            return None

        # 2. Scrape COMPETITORS (Top 3 -> All lines)
        competitor_data_maps = {}
        for cid in comp_ids:
            logging.info(f"--- Scraping Competitor: {cid} ---")
            c_data, _ = self.scrape_all_lines_for_country(target_id, cid, hs_code, master_ntl_list)
            competitor_data_maps[cid] = c_data

        # 3. Scrape OTHER SUPPLIERS (Next 5 -> First line only)
        other_suppliers_maps = {}
        for oid in other_ids:
            logging.info(f"--- Scraping Other Supplier (Summary Mode): {oid} ---")
            # Pass single_line_only=True here
            o_data, _ = self.scrape_all_lines_for_country(target_id, oid, hs_code, master_ntl_list, single_line_only=True)
            other_suppliers_maps[oid] = o_data

        # 4. BUILD REPORT
        builder = MacMapReportBuilder(config, your_data_map, competitor_data_maps, master_ntl_list, other_suppliers_maps)
        return builder.build()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="MacMap Scraper")
    parser.add_argument("--hs-code", required=True)
    parser.add_argument("--your-country-id", required=True)
    parser.add_argument("--target-market-id", required=True)
    parser.add_argument("--competitor-ids", nargs='+', default=[])
    parser.add_argument("--other-supplier-ids", nargs='+', default=[], help="IDs of the next 5 top suppliers")
    parser.add_argument("--output", default="market_access_filled.json")
    parser.add_argument("--headless", action='store_true')
    # Name arguments (Added for compatibility with orchestrator)
    parser.add_argument("--your-country-name", help="Ignored.")
    parser.add_argument("--target-market-name", help="Ignored.")

    args = parser.parse_args()

    config = {
        "hs_code": args.hs_code,
        "your_country_id": args.your_country_id,
        "target_market_id": args.target_market_id,
        "competitor_ids": args.competitor_ids,
        "other_supplier_ids": args.other_supplier_ids # <--- NEW
    }

    print("Initializing MacMap Scraper...")
    scraper = MacMapScraper(headless=args.headless, driver_path=r".\geckodriver.exe")
    
    try:
        if scraper.set_driver():
            data = scraper.run_comparison_logic(config)
            
            if data:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                print(f"\nSUCCESS! Data saved to: {os.path.abspath(args.output)}")
            else:
                print("\nFAILED. No data extracted.")
    except Exception as e:
        logging.critical(f"Critical Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if scraper.driver:
            scraper.driver.quit()