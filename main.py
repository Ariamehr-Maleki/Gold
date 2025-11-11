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
    """Saves the final combined data to a JSON file."""
    with open(filename, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=4)
    logging.info(f"Successfully saved all combined data to {filename}")

def archive_downloaded_files(paths_dict, archive_dir):
    """Moves successfully processed files to the archive directory with a timestamp."""
    if not paths_dict:
        logging.debug("No files to archive (empty paths_dict).")
        return
    
    # Filter out None values and non-existent files
    valid_paths = {k: v for k, v in paths_dict.items() if v and isinstance(v, str)}
    if not valid_paths:
        logging.warning("No valid file paths found in paths_dict for archiving.")
        return
    
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    logging.info(f"Archiving {len(valid_paths)} downloaded files to '{archive_dir}'...")
    
    # Ensure archive directory exists
    os.makedirs(archive_dir, exist_ok=True)
    
    for key, file_path in valid_paths.items():
        if file_path and os.path.exists(file_path):
            try:
                base_name = os.path.basename(file_path)
                archive_name = f"{timestamp}_{base_name}"
                destination_path = os.path.join(archive_dir, archive_name)
                shutil.move(file_path, destination_path)
                logging.info(f"✓ Archived '{base_name}' -> '{archive_name}'")
            except Exception as e:
                logging.error(f"✗ Failed to archive file {file_path}. Error: {e}")
        else:
            logging.warning(f"File path does not exist or is invalid: {file_path}")

# In main.py, REPLACE the existing download_and_parse_all_views function

def download_and_parse_all_views(scraper, config, task_name, trade_flow='I'):
    """
    Handles the multi-view download (value, quantity, unit_value) for a specific market.
    FIX: Correctly handles file paths and ensures parsing and archiving are robust.
    """
    logging.info(f"--- Starting Sequential Download and Parse for: {task_name} ---")
    
    country_id = config['target_market_id'] if trade_flow == 'I' else config['your_country_id']
    download_paths = {}
    views_to_download = ['value', 'quantity', 'unit_value']
    parsed_data = None # Initialize parsed_data to None

    for view in views_to_download:
        if not scraper.navigate_to_country_view_page(config, country_id, trade_flow, view=view):
            logging.error(f"Navigation/Verification failed for {view} page for {task_name}. Skipping.")
            continue
        
        file_name = f"{task_name}_{view}.txt"
        # Only clean the downloads directory before the first download in the sequence.
        clean_dir = True if view == 'value' else False
        downloaded_file = scraper._download_file(rename_to=file_name, clean_dir=clean_dir)
        
        if downloaded_file:
            # --- FIX: Store the full path to the downloaded file ---
            download_paths[f"{view}_file"] = downloaded_file
        else:
            logging.error(f"Failed to download file for {view} view.")
            # If a download fails, we should not proceed to parsing.
            archive_downloaded_files(download_paths, scraper.archive_dir) # Archive what we have so far
            return None, download_paths
    
    # --- FIX: Check for the essential value file BEFORE calling the parser ---
    value_file_path = download_paths.get("value_file")
    if not value_file_path or not os.path.exists(value_file_path):
        logging.error("Essential 'value' data file was not downloaded or found. Cannot proceed with parsing.")
        # We still return the download_paths so that any other downloaded files can be archived.
        return None, download_paths

    # Now, parse the files using their full paths
    parsed_data = parse_full_timeseries(
        value_file=value_file_path,
        quantity_file=download_paths.get("quantity_file"),
        unit_value_file=download_paths.get("unit_value_file"),
        config=config
    )

    if not parsed_data:
        logging.error(f"Parsing failed for {task_name}. Check logs for details.")
        # Even if parsing fails, we return the download_paths for archiving.
        return None, download_paths

    return parsed_data, download_paths

class ScraperWorkflow(DataDownloader):
    """Extends the base downloader with high-level workflow methods."""
    
    def download_and_parse_world_importers_data(self, config):
        """
        FIXED: Downloads only the necessary 'value' view for the world importers
        and calls the correct parser 'parse_world_importers_txt'.
        """
        logging.info(f"--- Starting Download and Parse for World Importers (single-view) ---")
        
        # We only need the 'value' view to get the world importers list and rank
        if not self.navigate_to_world_view_page(config, view='value'):
            logging.error("Navigation/Verification failed for world page for view=value.")
            return None, {}
        
        file_name = "world_importers_list.txt"
        downloaded_file = self._download_file(rename_to=file_name, clean_dir=True)
        
        if not downloaded_file:
            logging.error(f"Failed to download world importers file.")
            return None, {}
        
        # --- FIX: Call the correct parser for this specific file type ---
        parsed_data = parse_world_importers_txt(downloaded_file, config)
        
        if parsed_data:
            logging.info("Successfully downloaded and parsed WORLD importers list.")
        else:
            logging.error("Failed to parse WORLD importers list.")
            return None, {'world_importers_file': downloaded_file}

        return parsed_data, {'world_importers_file': downloaded_file}

    def download_and_parse_company_sample_data(self, config, trade_flow='I'):
        """Navigates to the company page (handling redirects) and downloads a sample list."""
        logging.info(f"--- Starting Download for a SAMPLE of Company Data ---")
        files_dict = {}  # Initialize to empty dict instead of None
        
        if not self.navigate_to_companies_page(config, trade_flow):
            logging.error("Navigation failed for companies page.")
            return [], files_dict
        try:
            logging.info("Waiting for company data table to load...")
            self.wait.until(EC.visibility_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")))
            
            download_button_xpath = "//input[@type='image' and @title='Text file']"
            self.wait.until(EC.element_to_be_clickable((By.XPATH, download_button_xpath)))
            
            # For this single-file download, cleaning the directory first is correct.
            downloaded_file_path = self._download_file(rename_to="company_sample.txt", clean_dir=True)
            
            if downloaded_file_path:
                parsed_data, files_dict = parse_company_txt(downloaded_file_path), {'company_file': downloaded_file_path}
                return parsed_data or [], files_dict
            else:
                return [], files_dict
        except Exception as e:
            logging.error(f"An error occurred while getting the company data sample: {e}")
            self._save_snapshot("company_sample_error")
            return [], files_dict


def enrich_factsheet_metrics(final_data, config):
    """
    Add / normalize fields expected by the Quantitative Export Factsheet template.
    Mutates final_data in-place and returns it.
    """
    your_country = config['your_country']

    tm = final_data.get('target_market_analysis', {})
    world_overview = final_data.get('world_market_overview', {})
    exports = final_data.get('your_country_global_exports', {})

    final_data.setdefault('factsheet_metrics', {})
    M = final_data['factsheet_metrics']

    # -- safe integer converter --
    def safe_int(x):
        try:
            return int(x)
        except Exception:
            try:
                return int(float(x))
            except Exception:
                return 0

    # --------------------------
    # TOTAL IMPORTS INTO TARGET MARKET
    # --------------------------
    total_imports = None

    if tm.get('total_value_usd'):
        total_imports = tm['total_value_usd']
    elif tm.get('world_values_usd'):
        total_imports = tm['world_values_usd'][-1]
    else:
        total_imports = world_overview.get('world_total_imports_usd', 0)

    M['target_market_total_imports_usd'] = safe_int(total_imports)

    # --------------------------
    # IMPORTS FROM YOUR COUNTRY
    # --------------------------
    your_country_entry = None
    for s in tm.get('suppliers_full_list', []):
        if s.get('name', '').strip().lower() == your_country.strip().lower():
            your_country_entry = s
            break

    your_country_imports = your_country_entry.get('value_usd', 0) if your_country_entry else 0
    M['target_market_imports_from_your_country_usd'] = safe_int(your_country_imports)

    # --------------------------
    # MARKET SHARE %
    # --------------------------
    if total_imports and total_imports > 0:
        M['your_country_share_of_target_imports_pct'] = round((your_country_imports / total_imports) * 100, 2)
    else:
        M['your_country_share_of_target_imports_pct'] = 0.0

    # --------------------------
    # WORLD RANK OF TARGET MARKET
    # --------------------------
    if 'target_market_world_rank' in world_overview:
        M['target_market_rank_in_world_imports'] = world_overview['target_market_world_rank']
    else:
        M['target_market_rank_in_world_imports'] = 'Unknown'

    # --------------------------
    # UNIT VALUES
    # --------------------------
    # Target market world unit value (value/qty)
    if tm.get('world_unit_values'):
        M['target_market_unit_value_latest'] = tm['world_unit_values'][-1]
    else:
        M['target_market_unit_value_latest'] = None

    # Your country unit value
    if your_country_entry and your_country_entry.get('unit_value_latest'):
        M['your_country_unit_value_latest'] = your_country_entry['unit_value_latest']
    else:
        M['your_country_unit_value_latest'] = None

    # World average unit value (derived from target's world values)
    if tm.get('world_unit_values'):
        M['world_unit_value_latest'] = tm['world_unit_values'][-1]
    else:
        M['world_unit_value_latest'] = None

    # --------------------------
    # TOP SUPPLIERS (TOP 5)
    # --------------------------
    top = tm.get('top_suppliers_sample', [])[:5]
    M['top_suppliers_top5'] = [
        {
            'name': s['name'],
            'share_pct': s.get('market_share_pct', 0)
        }
        for s in top
    ]

    # --------------------------
    # CONCENTRATION & HHI
    # --------------------------
    M['hhi'] = tm.get('hhi')
    M['concentration'] = tm.get('concentration')

    return final_data


if __name__ == '__main__':
    CONFIG = {
        "product_name": "Electric motors of an output not exceeding 37.5 W",
        "hs_code": "850110",
        "your_country": "South Africa", "your_country_id": "710",
        "target_market": "Germany", "target_market_id": "276",
    }

    final_data = {"header": {**CONFIG, "date": datetime.now().strftime("%B %Y")}}
    ac = os.environ.get('TM_USERNAME')
    pw = os.environ.get('TM_PASSWORD')
    
    if not ac or not pw:
        print("Please set TM_USERNAME and TM_PASSWORD environment variables.")
    else:
        # --- FIX: Instantiate the Scraper outside the try block ---
        s = None 
        try:
            s = ScraperWorkflow(headless=False, driver_path=r".\geckodriver.exe")
            if s.set_driver() and s.login(ac, pw):
                logging.info("Login successful. Beginning data extraction tasks.")
                
                # --- TASK 1: WORLD MARKET ---
                logging.info("="*70)
                logging.info("===== TASK 1 of 4: SCRAPING WORLD MARKET OVERVIEW                  =====")
                logging.info("="*70)
                # The 's' object is the ScraperWorkflow instance
                world_data, world_files = s.download_and_parse_world_importers_data(CONFIG)
                if world_data:
                    final_data["world_market_overview"] = world_data
                # Archive files regardless of parsing success
                archive_downloaded_files(world_files, s.archive_dir)

                # --- TASK 2: TARGET MARKET ---
                logging.info("="*70)
                logging.info("===== TASK 2 of 4: SCRAPING TARGET MARKET IMPORTS (GERMANY)        =====")
                logging.info("="*70)
                target_market_data, target_market_files = download_and_parse_all_views(s, CONFIG, "target_market_imports", trade_flow='I')
                if target_market_data:
                    final_data["target_market_analysis"] = target_market_data
                archive_downloaded_files(target_market_files, s.archive_dir)
                
                # --- TASK 3: YOUR COUNTRY EXPORTS ---
                logging.info("="*70)
                logging.info("===== TASK 3 of 4: SCRAPING YOUR COUNTRY'S GLOBAL EXPORTS (S.A.)   =====")
                logging.info("="*70)
                export_data, export_files = download_and_parse_all_views(s, CONFIG, "your_country_exports", trade_flow='E')
                if export_data:
                    final_data["your_country_global_exports"] = { "total_exports_to_world_usd": export_data.get("total_value_usd")}
                archive_downloaded_files(export_files, s.archive_dir)

                # --- TASK 4: COMPANY DATA ---
                logging.info("="*70)
                logging.info("===== TASK 4 of 4: SCRAPING COMPANY DATA SAMPLE                    =====")
                logging.info("="*70)
                company_data, company_files = s.download_and_parse_company_sample_data(CONFIG, trade_flow='I')
                if company_data:
                    final_data["business_partners_sample"] = company_data
                archive_downloaded_files(company_files, s.archive_dir)

                # --- FINAL STEPS ---
                logging.info("Enriching data with factsheet metrics...")
                final_data = enrich_factsheet_metrics(final_data, CONFIG)
                save_to_json(final_data)
                logging.info("SCRIPT FINISHED SUCCESSFULLY.")
        except Exception as e:
            logging.critical(f"A CRITICAL ERROR OCCURRED: {e}", exc_info=True)
        finally:
            if s and s.driver:
                input("Press Enter to exit and close the browser...")
                try:
                    s.driver.quit()
                except Exception:
                    pass
            else:
                print("Script finished or encountered an error before browser started.")