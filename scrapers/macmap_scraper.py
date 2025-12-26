# scrapers/macmap_scraper.py

import argparse
import json
import logging
import os
import sys
import time
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

# Path setup
current_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(current_dir)
sys.path.append(parent_dir)

from support.spider_core import TradeSpider
from support.macmap_parser import parse_macmap_html
from support.macmap_formatter import MacMapReportBuilder 

logging.basicConfig(level=logging.INFO, format='%(asctime)s - MACMAP - %(levelname)s - %(message)s')

class MacMapScraper(TradeSpider):
    
    def handle_popup(self):
        try:
            popup_btn = self.wait.until(EC.element_to_be_clickable((By.ID, "hidePopup")))
            popup_btn.click()
            time.sleep(1)
        except TimeoutException:
            pass

    def _wait_for_table(self):
        """Robustly waits for the data table rows to populate."""
        start_time = time.time()
        while time.time() - start_time < 20: # Increased timeout to 20s
            try:
                rows = self.driver.find_elements(By.CSS_SELECTOR, "#custom-duties-results table tbody tr")
                # Ensure we have rows and they aren't empty placeholders
                if len(rows) > 0 and rows[0].text.strip() != "":
                    return True
                if "No data available" in self.driver.page_source:
                    return False
            except: pass
            time.sleep(0.5)
        return False

    def _expand_agreement_details(self):
        try:
            links = self.driver.find_elements(By.CSS_SELECTOR, "a.detail-link")
            for link in links:
                if "Trade agreement details" in link.text and "less" not in link.get_attribute("class"):
                    self.driver.execute_script("arguments[0].click();", link)
                    time.sleep(0.1)
        except: pass

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
        """Uses JavaScript to select a specific National Tariff Line with robust waiting."""
        try:
            # Trigger the change via JavaScript
            script = f"""
                var $select = $('#ntlc-product-list');
                $select.val('{ntl_code}');
                $select.trigger('chosen:updated'); 
                $select.trigger('change');
            """
            self.driver.execute_script(script)
            
            # 1. Wait for request to start
            time.sleep(1) 

            # 2. Wait for jQuery AJAX to complete (Technical check)
            try:
                # Wait up to 10 seconds for jQuery.active to be 0
                self.wait.until(lambda d: d.execute_script("return (typeof jQuery !== 'undefined') ? jQuery.active == 0 : true"))
            except Exception:
                logging.warning(f"jQuery AJAX wait timed out for NTL {ntl_code}. Proceeding with fixed sleep.")

            # 3. 'Wait More' Buffer (Visual render check)
            # Increased to 4 seconds to ensure the table DOM is fully swapped
            time.sleep(4) 
            
            return True
        except Exception as e:
            logging.error(f"Failed to select NTL {ntl_code}: {e}")
            return False

    def scrape_all_lines_for_country(self, reporter_id, partner_id, hs_code, master_ntl_list=None):
        base_url = f"https://www.macmap.org/en/query/results?reporter={reporter_id}&partner={partner_id}&product={hs_code}&level=6"
        
        if not self.goto(base_url): 
            logging.error(f"Failed to load URL for Partner {partner_id}")
            return {}, []
            
        self.handle_popup()
        
        if not master_ntl_list:
            logging.info("Extracting NTL codes...")
            master_ntl_list = self._get_ntl_options()
            logging.info(f"Found {len(master_ntl_list)} National Tariff Lines.")

        results_by_line = {} 
        
        total = len(master_ntl_list)
        for i, item in enumerate(master_ntl_list):
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

    def run_comparison_logic(self, config):
        """
        Orchestrates the scraping and uses MacMapReportBuilder to format output.
        """
        target_id = config['target_market_id']
        your_id = config['your_country_id']
        comp_ids = config.get('competitor_ids', [])
        hs_code = config['hs_code']

        # 1. Scrape YOUR COUNTRY
        logging.info(f"--- Scraping Base Country: {your_id} ---")
        your_data_map, master_ntl_list = self.scrape_all_lines_for_country(target_id, your_id, hs_code)
        
        if not master_ntl_list:
            logging.error("No National Tariff Lines found. Check HS Code or Country IDs.")
            return None

        # 2. Scrape COMPETITORS
        competitor_data_maps = {}
        for cid in comp_ids:
            logging.info(f"--- Scraping Competitor: {cid} ---")
            c_data, _ = self.scrape_all_lines_for_country(target_id, cid, hs_code, master_ntl_list)
            competitor_data_maps[cid] = c_data

        # 3. BUILD REPORT
        logging.info("--- Generating Report based on Template ---")
        builder = MacMapReportBuilder(config, your_data_map, competitor_data_maps, master_ntl_list)
        return builder.build()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="MacMap Scraper")
    parser.add_argument("--hs-code", required=True)
    parser.add_argument("--your-country-id", required=True)
    parser.add_argument("--target-market-id", required=True)
    parser.add_argument("--competitor-ids", nargs='+', default=[])
    parser.add_argument("--output", default="market_access_filled.json")
    parser.add_argument("--headless", action='store_true')
    args = parser.parse_args()

    config = {
        "hs_code": args.hs_code,
        "your_country_id": args.your_country_id,
        "target_market_id": args.target_market_id,
        "competitor_ids": args.competitor_ids
    }

    print("🚀 Initializing MacMap Scraper...")
    scraper = MacMapScraper(headless=args.headless, driver_path=r".\geckodriver.exe")
    
    try:
        if scraper.set_driver():
            data = scraper.run_comparison_logic(config)
            
            if data:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(data, f, ensure_ascii=False, indent=4)
                print(f"\n✅ SUCCESS! Data saved to: {os.path.abspath(args.output)}")
            else:
                print("\n❌ FAILED. No data extracted.")
    except Exception as e:
        logging.critical(f"Critical Error: {e}")
        import traceback
        traceback.print_exc()
    finally:
        if scraper.driver:
            scraper.driver.quit()