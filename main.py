# main.py (Final Corrected File Handling)

from data_downloader import DataDownloader, logging
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
import shutil

def save_to_json(data, filename="final_factsheet_data.json"):
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logging.info(f"Successfully saved all combined data to {filename}")

def archive_downloaded_files(paths_dict, archive_dir):
    if not paths_dict: return
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.info(f"Archiving {len(paths_dict)} downloaded files...")
    for key, file_path in paths_dict.items():
        if file_path and os.path.exists(file_path):
            try:
                base_name = os.path.basename(file_path)
                archive_name = f"{timestamp}_{key}_{base_name}"
                destination_path = os.path.join(archive_dir, archive_name)
                shutil.move(file_path, destination_path)
                logging.info(f"Moved '{base_name}' to archive as '{archive_name}'")
            except Exception as e:
                logging.error(f"Failed to archive file {file_path}. Error: {e}")

def download_and_parse_all_views(scraper, config, task_name, trade_flow='I'):
    logging.info(f"--- Starting Multi-View Download and Parse for: {task_name} ---")
    
    # --- FIX #1 APPLIED HERE: Clean the directory ONCE before the entire multi-view task ---
    logging.info(f"Preparing for multi-file download. Cleaning '{scraper.download_dir}'...")
    for f in glob.glob(os.path.join(scraper.download_dir, "*.txt*")):
        try: os.remove(f)
        except Exception: pass

    country_id = config['target_market_id'] if trade_flow == 'I' else config['your_country_id']
    download_paths = {}
    views_to_download = ['value', 'quantity', 'unit_value']

    for view in views_to_download:
        if not scraper.navigate_to_country_view_page(config, country_id, trade_flow, view=view):
            logging.error(f"Navigation/Verification failed for {view} page for {task_name}. Skipping.")
            continue
        
        file_name = f"{task_name}_{view}.txt"
        # --- FIX #2 APPLIED HERE: Ensure we DO NOT clean the directory between downloads ---
        downloaded_file = scraper._download_file(rename_to=file_name, clean_dir=False)
        if downloaded_file:
            download_paths[f"{view}_file"] = downloaded_file
        else:
            logging.error(f"Failed to download file for {view} view.")
    
    if "value_file" not in download_paths:
        logging.error("Essential 'value' data file was not downloaded. Cannot proceed with parsing.")
        return None, download_paths

    parsed_data = parse_full_timeseries(
        value_file=download_paths.get("value_file"),
        quantity_file=download_paths.get("quantity_file"),
        unit_value_file=download_paths.get("unit_value_file"),
        config=config
    )
    return parsed_data, download_paths

class ScraperWorkflow(DataDownloader):
    
    def download_and_parse_world_importers_data(self, config):
        logging.info(f"--- Starting Download and Parse for World Importers (multi-view) ---")
        
        # --- FIX #1 APPLIED HERE: Clean the directory ONCE before the entire multi-view task ---
        logging.info(f"Preparing '{self.download_dir}' for fresh world downloads...")
        for f in glob.glob(os.path.join(self.download_dir, "*.txt*")):
            try: os.remove(f)
            except Exception: pass

        download_paths = {}
        views_to_download = ['value', 'quantity', 'unit_value']

        for view in views_to_download:
            if not self.navigate_to_world_view_page(config, view=view):
                logging.error(f"Navigation/Verification failed for world page for view={view}. Skipping.")
                continue
            
            file_name = f"world_{view}.txt"
            # --- FIX #2 APPLIED HERE: Ensure we DO NOT clean the directory between downloads ---
            downloaded_file = self._download_file(rename_to=file_name, clean_dir=False)
            if downloaded_file:
                download_paths[f"{view}_file"] = downloaded_file
            else:
                logging.error(f"Failed to download world file for view={view}.")

        if "value_file" not in download_paths:
            logging.error("Essential 'value' data file for WORLD was not downloaded.")
            return None, download_paths

        parsed = parse_full_timeseries(
            value_file=download_paths.get("value_file"),
            quantity_file=download_paths.get("quantity_file"),
            unit_value_file=download_paths.get("unit_value_file"),
            config=config
        )
        if parsed: logging.info("Successfully downloaded and parsed WORLD multi-view timeseries.")
        else: logging.error("Failed to parse merged WORLD timeseries.")
        
        return parsed, download_paths

    def download_and_parse_company_sample_data(self, config, trade_flow='I'):
        logging.info(f"--- Starting Download for a SAMPLE of Company Data ---")
        if not self.navigate_to_companies_page(config, trade_flow):
            logging.error("Navigation failed for companies page.")
            return [], None
        try:
            logging.info("Waiting for company data table to load...")
            self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
            
            download_button_xpath = "//input[@type='image' and @title='Text file']"
            self.wait.until(EC.element_to_be_clickable((By.XPATH, download_button_xpath)))
            
            # For this single-file download, cleaning the directory first is correct.
            downloaded_file_path = self._download_file(rename_to="company_sample.txt", clean_dir=True)
            
            if downloaded_file_path:
                return parse_company_txt(downloaded_file_path) or [], {'company_file': downloaded_file_path}
            else:
                return [], None
        except Exception as e:
            logging.error(f"An error occurred while getting the company data sample: {e}")
            self._save_snapshot("company_sample_error")
            return [], None


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
            logging.info("Login successful. Beginning data extraction tasks.")
            
            logging.info("="*70)
            logging.info("===== TASK 1 of 4: SCRAPING WORLD MARKET OVERVIEW                  =====")
            logging.info("="*70)
            world_data, world_files = s.download_and_parse_world_importers_data(CONFIG)
            if world_data: final_data["world_market_overview"] = world_data
            archive_downloaded_files(world_files, s.archive_dir)

            logging.info("="*70)
            logging.info("===== TASK 2 of 4: SCRAPING TARGET MARKET IMPORTS (GERMANY)        =====")
            logging.info("="*70)
            target_market_data, target_market_files = download_and_parse_all_views(s, CONFIG, "target_market_imports", trade_flow='I')
            if target_market_data: final_data["target_market_analysis"] = target_market_data
            archive_downloaded_files(target_market_files, s.archive_dir)
            
            logging.info("="*70)
            logging.info("===== TASK 3 of 4: SCRAPING YOUR COUNTRY'S GLOBAL EXPORTS (S.A.)   =====")
            logging.info("="*70)
            export_data, export_files = download_and_parse_all_views(s, CONFIG, "your_country_exports", trade_flow='E')
            if export_data: final_data["your_country_global_exports"] = { "total_exports_to_world_usd": export_data.get("total_value_usd")}
            archive_downloaded_files(export_files, s.archive_dir)

            logging.info("="*70)
            logging.info("===== TASK 4 of 4: SCRAPING COMPANY DATA SAMPLE                    =====")
            logging.info("="*70)
            company_data, company_files = s.download_and_parse_company_sample_data(CONFIG, trade_flow='I')
            if company_data: final_data["business_partners_sample"] = company_data
            archive_downloaded_files(company_files, s.archive_dir)

            save_to_json(final_data)
            logging.info("SCRIPT FINISHED SUCCESSFULLY.")
    except Exception as e:
        logging.critical(f"A CRITICAL ERROR OCCURRED: {e}", exc_info=True)
    finally:
        if 's' in locals() and s and s.driver:
            input("Press Enter to exit and close the browser...")
            try: s.driver.quit()
            except Exception: pass
        else:
            print("Script finished or encountered an error before browser started.")