# main.py (Complete Final Version)

from data_downloader import DataDownloader, logging
# --- FIX #1 APPLIED HERE: Import the correctly named function ---
from data_parser import parse_full_timeseries, parse_company_txt, parse_world_importers_txt
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.by import By
import os
import json
from datetime import datetime
import time
import random
import glob

def save_to_json(data, filename="final_factsheet_data.json"):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logging.info(f"Successfully saved all combined data to {filename}")

def download_and_parse_all_views(scraper, config, task_name, trade_flow='I'):
    logging.info(f"--- Starting Multi-View Download and Parse for: {task_name} ---")
    
    logging.info(f"Preparing for multi-file download. Cleaning '{scraper.download_dir}'...")
    for f in glob.glob(os.path.join(scraper.download_dir, "*.txt*")):
        try: os.remove(f)
        except Exception: pass

    country_id = config['target_market_id'] if trade_flow == 'I' else config['your_country_id']
    hs_code = config['hs_code']
    download_paths = {}
    views_to_download = ['value', 'quantity', 'unit_value']

    for view in views_to_download:
        if not scraper.navigate_to_timeseries_page(hs_code, country_id, trade_flow, view=view):
            logging.error(f"Failed to navigate to {view} page for {task_name}. Skipping.")
            continue
        try:
            scraper.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
        except TimeoutException:
            logging.error(f"Data table did not load for {task_name} ({view} view).")
            scraper._save_snapshot(f"no_table_{task_name}_{view}")
            continue

        file_name = f"{task_name}_{view}.txt"
        downloaded_file = scraper._download_file(rename_to=file_name, clean_dir=False)
        if downloaded_file:
            download_paths[f"{view}_file"] = downloaded_file
        else:
            logging.error(f"Failed to download file for {view} view.")
    
    if "value_file" not in download_paths:
        logging.error("Essential 'value' data file was not downloaded. Cannot proceed with parsing.")
        return None

    return parse_full_timeseries(
        value_file=download_paths.get("value_file"),
        quantity_file=download_paths.get("quantity_file"),
        unit_value_file=download_paths.get("unit_value_file"),
        config=config
    )

class ScraperWorkflow(DataDownloader):
    def navigate_to_world_importers_page(self, product_code):
        logging.info(f"Navigating to World Importers page for product {product_code}")
        url = f"https://www.trademap.org/Product_SelCountry_TS.aspx?nvpm=1|000|||{product_code}|||1|1|1|1|2|1|1|1|1"
        if not self.goto(url): return False
        time.sleep(3)
        return True

    def download_and_parse_world_importers_data(self, config):
        logging.info(f"--- Starting Download and Parse for World Importers ---")
        if not self.navigate_to_world_importers_page(config['hs_code']): return None
        try:
            self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
        except TimeoutException:
            logging.error("Data table did not load for World Importers data.")
            self._save_snapshot("no_world_importers_table")
            return None
        downloaded_file_path = self._download_file(rename_to="world_importers.txt")
        return parse_world_importers_txt(downloaded_file_path, config) if downloaded_file_path else None

    def download_and_parse_company_sample_data(self, config, trade_flow='I'):
        logging.info(f"--- Starting Download for a SAMPLE of Company Data ---")
        if not self.navigate_to_companies_page(config['hs_code'], config['target_market_id'], trade_flow):
            return []
        try:
            # --- FIX #2 APPLIED HERE: Wait for the main table to be visible first ---
            logging.info("Waiting for company table to load before proceeding...")
            self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
            logging.info("Company table loaded.")
            # --- END OF FIX ---

            category_links_xpath = "//table[@id='ctl00_PageContent_MyGridView1']//a[contains(@id, 'LinkButton_CompanyProduct')]"
            try:
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
            downloaded_file_path = self._download_file(expected_keywords=[k for k in expected_keywords if k], max_attempts=4, click_xpath=download_button_xpath, rename_to="company_sample.txt")
            
            # --- FIX #1 APPLIED HERE: Call the correctly named function ---
            return parse_company_txt(downloaded_file_path) or []
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
            logging.info("Login successful. Ensuring browser is on the correct starting page for data extraction.")
            s.goto("https://www.trademap.org/Country_SelProduct_TS.aspx")
            time.sleep(2)

            logging.info("===== TASK 1 of 4: SCRAPING WORLD MARKET OVERVIEW =====")
            if world_data := s.download_and_parse_world_importers_data(CONFIG):
                final_data["world_market_overview"] = world_data

            logging.info("===== TASK 2 of 4: SCRAPING TARGET MARKET IMPORTS (MULTI-VIEW) =====")
            if target_market_data := download_and_parse_all_views(s, CONFIG, "target_market_imports", trade_flow='I'):
                final_data["target_market_analysis"] = target_market_data
            
            logging.info("===== TASK 3 of 4: SCRAPING YOUR COUNTRY'S GLOBAL EXPORTS =====")
            if export_data := download_and_parse_all_views(s, CONFIG, "your_country_exports", trade_flow='E'):
                final_data["your_country_global_exports"] = { "total_exports_to_world_usd": export_data.get("total_value_usd")}

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