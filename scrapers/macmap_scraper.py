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
            # Wait briefly for overlay to appear
            WebDriverWait(self.driver, 3).until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".blockUI, .loading, .spinner"))
            )
            # If it appeared, wait longer for it to vanish
            WebDriverWait(self.driver, 20).until(
                EC.invisibility_of_element_located((By.CSS_SELECTOR, ".blockUI, .loading, .spinner"))
            )
        except TimeoutException:
            pass 
        except Exception:
            pass

    def _wait_for_table(self):
        """
        Robustly waits for the data table rows to populate with real data.
        Includes a grace period before accepting 'No data' as final.
        """
        start_time = time.time()
        timeout = 90  
        grace_period = 8 # Increased grace period to 8s
        
        logging.info("Waiting for table data to populate...")
        
        while time.time() - start_time < timeout: 
            elapsed = time.time() - start_time
            try:
                rows = self.driver.find_elements(By.CSS_SELECTOR, "#custom-duties-results table tbody tr")
                
                if len(rows) > 0:
                    first_row_text = rows[0].text.strip()
                    
                    if first_row_text != "":
                        if "oading" in first_row_text:
                            if int(time.time()) % 5 == 0:
                                logging.debug("Table contains 'Loading...' text. Waiting...")
                        else:
                            logging.info(f"Table populated with {len(rows)} rows. First row starts with: '{first_row_text[:30]}...'")
                            return True
                
                # Check for explicit "No data" message
                # ONLY fail if we are past the grace period
                if "No data available" in self.driver.page_source:
                    if elapsed > grace_period:
                        time.sleep(2)
                        if "No data available" in self.driver.page_source:
                            logging.warning("Explicit 'No data available' message confirmed after grace period.")
                            return False
                    else:
                        pass # Still in grace period

            except StaleElementReferenceException:
                continue
            except Exception as e: 
                pass
            
            time.sleep(0.5)
            
        logging.error(f"Timeout ({timeout}s) reached waiting for table data.")
        return False

    def _wait_for_initial_page_load(self):
        logging.info("Waiting for page stabilization...")
        try:
            WebDriverWait(self.driver, 30).until(
                lambda d: d.execute_script("return document.readyState") == "complete"
            )

            WebDriverWait(self.driver, 20).until(
                EC.presence_of_element_located((By.TAG_NAME, "body"))
            )

            self._wait_for_loading_overlay()

            try:
                WebDriverWait(self.driver, 20).until(
                    EC.presence_of_element_located((By.ID, "ntlc-product-list"))
                )
            except TimeoutException:
                logging.warning("Warning: Product dropdown (ntlc-product-list) not detected. Proceeding cautiously...")

            self.handle_popup()
            
            logging.info("Page fully loaded (readyState=complete). Waiting 10s buffer...")
            time.sleep(10) 
            return True

        except TimeoutException:
            logging.error("Timed out waiting for document.readyState to be complete.")
            return False
        except Exception as e:
            logging.warning(f"Error during initial load wait: {e}")
            return False

    def _expand_agreement_details(self):
        try:
            links = self.driver.find_elements(By.XPATH, "//a[contains(text(), 'Trade agreement details')]")
            
            clicked_something = False
            for link in links:
                try:
                    if link.is_displayed():
                        self.driver.execute_script("arguments[0].click();", link)
                        clicked_something = True
                except Exception:
                    continue
            
            if clicked_something:
                try:
                    WebDriverWait(self.driver, 8).until(
                        EC.visibility_of_any_elements_located((By.CSS_SELECTOR, "#fta-result, .result-fta, .agreement-detail"))
                    )
                except TimeoutException:
                    pass
                
                time.sleep(5) 
                
        except Exception as e:
            logging.warning(f"Error expanding details: {e}")

    def _get_ntl_options(self):
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
        try:
            logging.info(f"Attempting to select NTL: {ntl_code}")
            
            old_rows = self.driver.find_elements(By.CSS_SELECTOR, "#custom-duties-results table tbody tr")
            old_ref = old_rows[0] if old_rows else None

            # Trigger change
            script = f"""
                var $select = $('#ntlc-product-list');
                $select.val('{ntl_code}');
                $select.trigger('chosen:updated'); 
                $select.trigger('change');
            """
            self.driver.execute_script(script)
            
            # Increased buffer to 5s to allow JS to fire fully
            time.sleep(5) 
            
            self._wait_for_loading_overlay()

            if old_ref:
                try:
                    WebDriverWait(self.driver, 15).until(EC.staleness_of(old_ref))
                    logging.info("Old table rows successfully detached.")
                except TimeoutException:
                    logging.warning(f"NTL {ntl_code}: Old table rows did not detach within 15s. DOM update might be stuck.")

            if not self._wait_for_table():
                logging.warning(f"NTL {ntl_code}: New table did not load within timeout.")
                return False

            logging.info("NTL selected and table verified. Waiting 5s buffer...")
            time.sleep(5) 
            
            return True
        except Exception as e:
            logging.error(f"Failed to select NTL {ntl_code}: {e}")
            return False

    def scrape_all_lines_for_country(self, reporter_id, partner_id, hs_code, master_ntl_list=None, single_line_only=False, max_lines=6):
        base_url = f"https://www.macmap.org/en/query/results?reporter={reporter_id}&partner={partner_id}&product={hs_code}&level=6"
        
        logging.info(f"Navigating to {base_url}")
        if not self.goto(base_url): 
            logging.error(f"Failed to load URL for Partner {partner_id}")
            return {}, []
            
        if not self._wait_for_initial_page_load():
            return {}, []
        
        if not master_ntl_list:
            try:
                self.wait.until(EC.presence_of_element_located((By.ID, "ntlc-product-list")))
                time.sleep(3)
                master_ntl_list = self._get_ntl_options()
            except Exception:
                master_ntl_list = self._get_ntl_options()
                if not master_ntl_list: return {}, []

        results_by_line = {} 
        
        total = len(master_ntl_list)
        for i, item in enumerate(master_ntl_list):
            
            if single_line_only and i > 0:
                logging.info(f"[{partner_id}] Single line mode active. Stopping after first line.")
                break
            
            if i >= max_lines:
                logging.info(f"[{partner_id}] Max lines limit ({max_lines}) reached. Stopping.")
                break

            code = item['code']
            logging.info(f"   [{partner_id}] Processing line {i+1}/{total}: {code}")
            
            # --- TRY 1 ---
            success = self._select_ntl_code(code)
            
            # --- RETRY LOGIC (Refresh) ---
            if not success:
                logging.warning(f"Failed to load data for {code}. Refreshing page and retrying...")
                try:
                    self.driver.refresh()
                    if self._wait_for_initial_page_load():
                        logging.info("Page refreshed. Retrying selection...")
                        success = self._select_ntl_code(code)
                    else:
                        logging.error("Page reload failed.")
                except Exception as e:
                    logging.error(f"Error during refresh retry: {e}")

            if not success:
                logging.warning(f"Skipping line {code} after retry failure.")
                continue
            
            self._expand_agreement_details()

            try:
                full_html = self.driver.find_element(By.TAG_NAME, "body").get_attribute("innerHTML")
                results_by_line[code] = parse_macmap_html(full_html)
            except Exception as e:
                logging.error(f"Error parsing line {code}: {e}")

        return results_by_line, master_ntl_list

    def run_comparison_logic(self, config):
        target_id = config['target_market_id']
        your_id = config['your_country_id']
        comp_ids = config.get('competitor_ids', [])
        other_ids = config.get('other_supplier_ids', [])
        hs_code = config['hs_code']

        # 1. Scrape YOUR COUNTRY
        logging.info(f"--- Scraping Base Country: {your_id} ---")
        your_data_map, master_ntl_list = self.scrape_all_lines_for_country(target_id, your_id, hs_code)
        
        if not master_ntl_list:
            logging.error("No NTL lines found for base country. Aborting.")
            return None

        # 2. Scrape COMPETITORS
        competitor_data_maps = {}
        for cid in comp_ids:
            logging.info(f"--- Scraping Competitor: {cid} ---")
            c_data, _ = self.scrape_all_lines_for_country(target_id, cid, hs_code, master_ntl_list)
            competitor_data_maps[cid] = c_data

        # 3. Scrape OTHER SUPPLIERS
        other_suppliers_maps = {}
        for oid in other_ids:
            logging.info(f"--- Scraping Other Supplier (Summary Mode): {oid} ---")
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
    parser.add_argument("--other-supplier-ids", nargs='+', default=[])
    parser.add_argument("--competitor-names-map", default='{}', help="JSON string mapping competitor IDs to names")
    parser.add_argument("--output", default="market_access_filled.json")
    parser.add_argument("--headless", action='store_true')
    parser.add_argument("--your-country-name", help="Ignored.")
    parser.add_argument("--target-market-name", help="Ignored.")

    args = parser.parse_args()

    # Parse the competitor_names_map from JSON string
    try:
        competitor_names_map = json.loads(args.competitor_names_map)
    except (json.JSONDecodeError, TypeError):
        competitor_names_map = {}

    config = {
        "hs_code": args.hs_code,
        "your_country_id": args.your_country_id,
        "target_market_id": args.target_market_id,
        "competitor_ids": args.competitor_ids,
        "other_supplier_ids": args.other_supplier_ids,
        "country_names_map": competitor_names_map
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