# scrapers/macmap_scraper.py
import argparse
import json
import logging
import os
import sys
import time
import pandas as pd

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from support.spider_core import TradeSpider, logging
from selenium.webdriver.common.by import By
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException

class MacMapScraper(TradeSpider):
    """A dedicated scraper for macmap.org."""
    # ... (All class methods from the original file remain here, unchanged)
    def handle_popup(self):
        """Checks for and closes the initial promotional popup."""
        try:
            wait = self.wait.__class__(self.driver, 5) 
            popup_button_locator = (By.ID, "hidePopup")
            logging.info("Checking for welcome popup...")
            popup_button = wait.until(EC.element_to_be_clickable(popup_button_locator))
            logging.info("Popup detected. Clicking 'Do not ask me anymore'.")
            popup_button.click()
            wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "modal-backdrop")))
        except TimeoutException:
            logging.info("No popup was detected.")
        except Exception as e:
            logging.error(f"An error occurred while handling the popup: {e}")

    def _parse_overview(self):
        """Parses the top overview section with summary data based on the new DOM."""
        overview_data = {}
        try:
            # Main container for overview info
            overview_content = self.driver.find_element(By.CLASS_NAME, "overview-content")

            # Scrape country and product info
            overview_data['exporting_country'] = overview_content.find_element(By.XPATH, ".//div[div[contains(., 'EXPORTING COUNTRY')]]/div[@class='summary-text']").text.strip()
            overview_data['importing_country'] = overview_content.find_element(By.XPATH, ".//div[div[contains(., 'IMPORTING COUNTRY')]]/div[@class='summary-text']").text.strip()
            overview_data['product_description'] = overview_content.find_element(By.ID, "collapseExample").text.strip()
            
            # Scrape the three summary boxes
            boxes = overview_content.find_element(By.ID, "overview-box-customs-tariffs")
            overview_data['import_duty'] = boxes.find_element(By.CSS_SELECTOR, ".customs-tariff-rate-details").text.strip()
            overview_data['import_duty_type'] = boxes.find_element(By.CSS_SELECTOR, ".customs-tariff-rate-label").text.strip()

            remedies_box = overview_content.find_element(By.ID, "overview-box-trade-remedies")
            overview_data['trade_remedies_summary'] = remedies_box.find_element(By.XPATH, ".//div[@class='item']/h2").text.strip()

            req_box = overview_content.find_element(By.ID, "overview-box-regulatory-requirements")
            overview_data['total_regulatory_measures'] = req_box.find_element(By.XPATH, ".//div[@class='item']/h2").text.strip()
            
            logging.info("Successfully parsed overview block.")
        except Exception as e:
            logging.error(f"Could not parse overview block: {e}")
        return overview_data

    def _parse_customs_tariffs(self):
        """Uses Pandas to parse the main Customs Tariffs table."""
        try:
            tariffs_table_element = self.driver.find_element(By.ID, "custom-duties-results")
            df = pd.read_html(tariffs_table_element.get_attribute('outerHTML'))[0]
            logging.info("Successfully parsed Customs Tariffs table.")
            # Replace all NaN values with an empty string for clean JSON output
            df = df.fillna('')
            # Return cleaned records as list of dicts
            return df.to_dict('records')
        except Exception as e:
            logging.error(f"Failed to parse Customs Tariffs table: {e}")
        return []

    def _parse_trade_remedies(self):
        """Interactively parses the Trade Remedies table, including expandable content."""
        remedies = []
        try:
            table = self.driver.find_element(By.CSS_SELECTOR, "#trade-remedy > .table")
            rows = table.find_elements(By.XPATH, "./tbody/tr[not(contains(@class, 'expand-content'))]")
            
            for row in rows:
                remedy_data = {
                    "subject": row.find_element(By.XPATH, "./td[1]").text,
                    "remedy_type": row.find_element(By.XPATH, "./td[2]").text,
                    "remedy_status": row.find_element(By.XPATH, "./td[3]").text,
                    "start_date": row.find_element(By.XPATH, "./td[4]").text,
                    "end_date": row.find_element(By.XPATH, "./td[5]").text,
                    "details": {}
                }
                
                # Click to expand the details
                try:
                    expand_button = row.find_element(By.CSS_SELECTOR, "span.expand")
                    self.driver.execute_script("arguments[0].click();", expand_button)
                    time.sleep(0.5) # Wait for expansion

                    # Find the newly visible details row
                    details_row = row.find_element(By.XPATH, "./following-sibling::tr[1]")
                    inner_table = details_row.find_element(By.CSS_SELECTOR, ".table.inside-table")
                    
                    # Parse the inner table
                    details_rows = inner_table.find_elements(By.XPATH, ".//tbody/tr")
                    inner_details = []
                    for detail_row in details_rows:
                        inner_details.append({
                            "exporting_firm": detail_row.find_element(By.XPATH, "./td[1]").text,
                            "measure": detail_row.find_element(By.XPATH, "./td[2]").text,
                            "note": detail_row.find_element(By.XPATH, "./td[3]").text,
                        })
                    remedy_data["details"] = inner_details
                    
                    # Click again to collapse (optional, but good for stability)
                    self.driver.execute_script("arguments[0].click();", expand_button)
                except Exception as detail_error:
                    logging.warning(f"Could not expand or parse details for a remedy: {detail_error}")

                remedies.append(remedy_data)
            logging.info("Successfully parsed Trade Remedies table with details.")
        except Exception as e:
            logging.error(f"Failed to parse Trade Remedies: {e}")
        return remedies

    def _parse_regulatory_requirements(self):
        """Interactively parses the NTMs, expanding each one to get details."""
        ntms = {}
        try:
            ntm_sections = self.driver.find_elements(By.CSS_SELECTOR, "#ntm-summary-results > h5.tab-title")
            for section in ntm_sections:
                section_title = section.find_element(By.XPATH, "./span[1]").text
                ntms[section_title] = []
                
                table = section.find_element(By.XPATH, "./following-sibling::div[1]/table")
                rows = table.find_elements(By.CSS_SELECTOR, "tr.toggle-trigger")
                
                for row in rows:
                    ntm_data = {
                        "code_and_desc": row.find_element(By.CSS_SELECTOR, ".measure-summary-wrapper").text.replace('\n', ' '),
                        "count": row.find_element(By.CSS_SELECTOR, ".measure-count").text,
                        "details": []
                    }

                    # Click to load and show details
                    self.driver.execute_script("arguments[0].click();", row)
                    time.sleep(1) # Wait for AJAX content to load and render
                    
                    details_row = row.find_element(By.XPATH, "./following-sibling::tr[1]")
                    detail_items = details_row.find_elements(By.CSS_SELECTOR, ".req-detail > li")
                    
                    for item in detail_items:
                        ntm_data["details"].append(item.text)
                    
                    ntms[section_title].append(ntm_data)

            logging.info("Successfully parsed Regulatory Requirements (NTMs) with details.")
        except Exception as e:
            logging.error(f"Could not parse NTMs: {e}")
        return ntms

    def scrape_market_access(self, config):
        reporter_id = config['target_market_id']
        partner_id = config['your_country_id']
        product_id = config['hs_code']
        url = f"https://www.macmap.org/en/query/results?reporter={reporter_id}&partner={partner_id}&product={product_id}&level=6"
        
        logging.info("Loading MacMap page...")
        if not self.goto(url):
            return None
        time.sleep(3) # Wait for dynamic content
        
        self.handle_popup()
        
        try:
            self.wait.until(EC.visibility_of_element_located((By.CLASS_NAME, "overview-content")))
            logging.info("MacMap results page content detected.")
        except TimeoutException:
            logging.error("Timed out waiting for overview content.")
            self._save_snapshot("macmap_load_fail")
            return None

        return {
            "source": "Market Access Map (macmap.org)",
            "overview": self._parse_overview(),
            "customs_tariffs": self._parse_customs_tariffs(),
            "trade_remedies": self._parse_trade_remedies(),
            "regulatory_requirements": self._parse_regulatory_requirements()
        }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape market access data from MacMap.")
    parser.add_argument("--output", required=True, help="Path to save the output JSON file.")
    parser.add_argument("--headless", action='store_true', help="Run in headless mode.")
    args = parser.parse_args()

    CONFIG = {
        "hs_code": "847130", "your_country_id": "156", "target_market_id": "842",
    }
    
    s = MacMapScraper(headless=args.headless, driver_path=r".\geckodriver.exe")
    try:
        if s.set_driver():
            macmap_data = s.scrape_market_access(CONFIG)
            if macmap_data:
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(macmap_data, f, ensure_ascii=False, indent=4)
                logging.info(f"Successfully saved data to {args.output}")
            else:
                logging.error("Scraping failed, no data returned.")
                sys.exit(1)
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if s and s.driver:
            s.driver.quit()