# main.py

from data_downloader import DataDownloader, logging
# Import the new parser function
from data_parser import _parse_timeseries_txt, _parse_company_txt, _parse_world_importers_txt
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import os
import json
from datetime import datetime
import time
import random

def save_to_json(data, filename="final_factsheet_data.json"):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logging.info(f"Successfully saved all combined data to {filename}")


class ScraperWorkflow(DataDownloader):
    # This method is new, to navigate to the list of all importers for a product
    def navigate_to_world_importers_page(self, product_code):
        logging.info(f"Navigating to World Importers page for product {product_code}")
        # URL for: Product, Imports, from World, Time Series
        url = f"https://www.trademap.org/Product_SelCountry_TS.aspx?nvpm=1|000|||{product_code}|||1|1|1|1|2|1|1|1|1"
        if not self.goto(url): return False
        time.sleep(3)
        return True

    # This is the new scraping function for the world overview
    def download_and_parse_world_importers_data(self, config):
        logging.info(f"--- Starting Download and Parse for World Importers ---")
        if not self.navigate_to_world_importers_page(config['hs_code']): return None
        try:
            self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_GridViewPanel")))
        except TimeoutException:
            logging.error("Data table did not load for World Importers data.")
            self._save_snapshot("no_world_importers_table")
            return None
        downloaded_file_path = self._download_file()
        return _parse_world_importers_txt(downloaded_file_path, config) if downloaded_file_path else None

    def download_and_parse_timeseries_data(self, config, trade_flow='I'):
        logging.info(f"--- Starting Download and Parse for Time Series (Flow: {trade_flow}) ---")
        country_id = config['target_market_id'] if trade_flow == 'I' else config['your_country_id']
        if not self.navigate_to_timeseries_page(config['hs_code'], country_id, trade_flow): return None
        try:
            self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
        except TimeoutException:
            logging.error("Data table did not load for Time Series data.")
            self._save_snapshot(f"no_timeseries_table_found_{trade_flow}")
            return None
        downloaded_file_path = self._download_file()
        return _parse_timeseries_txt(downloaded_file_path, config) if downloaded_file_path else None

    def download_and_parse_company_sample_data(self, config, trade_flow='I'):
        logging.info(f"--- Starting Download for a SAMPLE of Company Data ---")
        if not self.navigate_to_companies_page(config['hs_code'], config['target_market_id'], trade_flow):
            return []
        try:
            category_links_xpath = "//table[@id='ctl00_PageContent_MyGridView1']//a[contains(@id, 'LinkButton_CompanyProduct')]"
            try:
                self.wait.until(EC.presence_of_element_located((By.XPATH, category_links_xpath)))
                first_link_el = self.wait.until(EC.element_to_be_clickable((By.XPATH, category_links_xpath)))
                self.driver.execute_script("arguments[0].scrollIntoView(true);", first_link_el)
                time.sleep(random.uniform(0.8, 1.5))
                if not self._safe_click(By.XPATH, category_links_xpath): return []
                time.sleep(random.uniform(1.5, 3.0))
            except TimeoutException:
                logging.info("No sub-categories found. Proceeding to download directly.")
            download_button_xpath = "//input[@type='image' and @title='Text file']"
            self.wait.until(EC.element_to_be_clickable((By.XPATH, download_button_xpath)))
            expected_keywords = [config.get('target_market'), config.get('your_country')]
            downloaded_file_path = self._download_file(expected_keywords=[k for k in expected_keywords if k], max_attempts=4, click_xpath=download_button_xpath)
            return _parse_company_txt(downloaded_file_path) or []
        except Exception as e:
            logging.error(f"An error occurred while getting the company data sample: {e}")
            self._save_snapshot("company_sample_error")
            return []

if __name__ == '__main__':
    CONFIG = {
        "product_name": "Electric motors of an output not exceeding 37.5 W",
        "hs_code": "850110",
        "your_country": "South Africa", "your_country_id": "710",
        "target_market": "Germany", "target_market_id": "276",
    }

    final_data = {"header": {**CONFIG, "date": datetime.now().strftime("%B %Y")}}
    ac = os.environ.get('TM_USERNAME') or input('Enter TM username: ')
    pw = os.environ.get('TM_PASSWORD') or input('Enter TM password: ')
    s = ScraperWorkflow(headless=False, driver_path=r".\geckodriver.exe")

    try:
        if s.set_driver() and s.login(ac, pw):
            # *** NEW TASK 1: Get World Overview Data ***
            logging.info("===== TASK 1 of 4: SCRAPING WORLD MARKET OVERVIEW =====")
            if world_data := s.download_and_parse_world_importers_data(CONFIG):
                final_data["world_market_overview"] = world_data

            # --- Task 2: Target Market Imports ---
            logging.info("===== TASK 2 of 4: SCRAPING TARGET MARKET IMPORTS =====")
            if target_market_data := s.download_and_parse_timeseries_data(CONFIG, trade_flow='I'):
                final_data["target_market_analysis"] = target_market_data
            
            # --- Task 3: Your Country's Exports ---
            logging.info("===== TASK 3 of 4: SCRAPING YOUR COUNTRY'S GLOBAL EXPORTS =====")
            if export_data := s.download_and_parse_timeseries_data(CONFIG, trade_flow='E'):
                final_data["your_country_global_exports"] = { "total_exports_to_world_usd": export_data.get("total_value_usd")}

            # --- Task 4: Company Data Sample ---
            logging.info("===== TASK 4 of 4: SCRAPING COMPANY DATA SAMPLE =====")
            if company_data := s.download_and_parse_company_sample_data(CONFIG, trade_flow='I'):
                final_data["business_partners_sample"] = company_data

            save_to_json(final_data)

    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
    finally:
        if s and s.driver:
            input("Press Enter to exit and close the browser...")
            try: s.driver.quit()
            except Exception: pass
        else:
            print("Script finished or encountered an error before browser started.")