# scrapers/trademap_scraper.py (Corrected Logic v4 - With Total Exports and World Comparison)
import argparse
import json
import logging
import os
import sys
import glob

# Add parent directories to path to allow importing from 'support'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from support.data_downloader import DataDownloader
from support.data_parser import parse_full_timeseries, parse_world_importers_txt, parse_company_txt

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def download_all_views_for_market(scraper, config, market_name, market_id, trade_flow):
    """
    Helper function to download value, quantity, and unit_value for a given market.
    This function NEVER cleans the directory, assuming it's done once at the start.
    """
    downloaded_files = {}
    views_to_download = ['value', 'quantity', 'unit_value']
    
    for view in views_to_download:
        logging.info(f"--- Downloading '{view}' for {market_name} ---")
        
        # Use different navigation functions for 'world' vs. a specific country
        if market_name == 'world_market':
            nav_success = scraper.navigate_to_world_view_page(config, view=view)
        else:
            nav_success = scraper.navigate_to_country_view_page(config, market_id, trade_flow=trade_flow, view=view)

        if nav_success:
            file_name = f"{market_name}_{view}.txt"
            # CRITICAL: Always set clean_dir=False in sequential downloads
            file_path = scraper._download_file(rename_to=file_name, clean_dir=False)
            if file_path:
                downloaded_files[f"{market_name}_{view}"] = file_path
        else:
            logging.warning(f"Could not navigate to page for view '{view}' for {market_name}. Skipping.")
            
    return downloaded_files


def scrape_trademap(args):
    """Main execution function for the TradeMap scraping process with robust file handling."""
    CONFIG = {
        "hs_code": "847130", "your_country": "China", "your_country_id": "156",
        "target_market": "United States of America", "target_market_id": "842",
        "login_user": os.environ.get("TRADEMAP_USER", "mst.magpi@gmail.com"),
        "login_pass": os.environ.get("TRADEMAP_PASS", "1996")
    }

     # Override with command-line arguments if provided
    if args.hs_code: CONFIG['hs_code'] = args.hs_code
    if args.your_country_id: CONFIG['your_country_id'] = args.your_country_id
    if args.your_country_name: CONFIG['your_country'] = args.your_country_name
    if args.target_market_id: CONFIG['target_market_id'] = args.target_market_id
    if args.target_market_name: CONFIG['target_market'] = args.target_market_name

    scraper = DataDownloader(headless=args.headless, driver_path=r"./geckodriver.exe")
    all_downloaded_files = {}
    final_data = {
        "source": "Trade Map (trademap.org)",
        "config": {k: v for k, v in CONFIG.items() if 'pass' not in k}
    }

    try:
        if not scraper.set_driver(): raise Exception("Failed to initialize WebDriver.")
        if not scraper.login(CONFIG['login_user'], CONFIG['login_pass']): raise Exception("Login failed.")

        # --- STEP 1: Perform a SINGLE cleanup of the download directory ---
        logging.info(f"Preparing for downloads. Cleaning directory: {scraper.download_dir}")
        for f in glob.glob(os.path.join(scraper.download_dir, "*.txt*")):
            os.remove(f)

        # --- STEP 2: Download ALL required files sequentially ---

        # Task 1: World Market Overview (List of Importers)
        world_files = download_all_views_for_market(scraper, CONFIG, 'world_market', market_id=None, trade_flow='I')
        all_downloaded_files.update(world_files)
        
        # Task 2: Target Market Detailed Analysis
        target_files = download_all_views_for_market(scraper, CONFIG, 'target_market', CONFIG['target_market_id'], trade_flow='I')
        all_downloaded_files.update(target_files)

        # Task 3: Your Country's Global Exports
        export_files = download_all_views_for_market(scraper, CONFIG, 'your_country_exports', CONFIG['your_country_id'], trade_flow='E')
        all_downloaded_files.update(export_files)

        # Task 4: Company Data
        logging.info("--- Downloading Company List ---")
        if scraper.navigate_to_companies_page(CONFIG, country_id=CONFIG['target_market_id'], trade_flow='I'):
            
            # CRITICAL: clean_dir=False
            company_file = scraper._download_file(rename_to="company_list.txt", clean_dir=False)
            if company_file:
                all_downloaded_files['companies'] = company_file
        else:
            logging.warning("Could not navigate to companies page. Skipping.")

        # --- STEP 3: Parse all downloaded files for the main analysis ---
        logging.info("--- Starting Data Parsing ---")
        
        # The main analysis comes from the Target Market files
        final_data['market_analysis'] = parse_full_timeseries(
            value_file=all_downloaded_files.get('target_market_value'),
            quantity_file=all_downloaded_files.get('target_market_quantity'),
            unit_value_file=all_downloaded_files.get('target_market_unit_value'),
            config=CONFIG
        )
        
        # The world ranking comes from the World Market (value) file
        final_data['importer_ranking'] = parse_world_importers_txt(
            file_path=all_downloaded_files.get('world_market_value'), # Use the world value file for this
            config=CONFIG
        )
        
        # Company list parsing
        final_data['potential_importers'] = parse_company_txt(
            file_path=all_downloaded_files.get('companies')
        )
        
        ### MODIFICATION START ###
        # --- STEP 4: Parse World Market Data for Global Comparison ---
        logging.info("--- Parsing World Market Data for Comparison ---")
        world_market_data = parse_full_timeseries(
            value_file=all_downloaded_files.get('world_market_value'),
            quantity_file=all_downloaded_files.get('world_market_quantity'),
            unit_value_file=all_downloaded_files.get('world_market_unit_value'),
            config=CONFIG
        )

        if world_market_data:
            # The 'market_growth...' fields are calculated from the 'World' row in the file.
            # When parsing the world_market file, this gives us the global growth rate.
            # The 'world_unit_values' list contains the average unit value for each year.
            final_data['world_comparison_data'] = {
                "world_import_growth_cagr_pct": world_market_data.get('market_growth_cagr_pct'),
                "world_import_growth_last_year_pct": world_market_data.get('market_growth_last_year_pct'),
                "world_unit_value_usd": world_market_data.get('world_unit_values', [None])[-1] # Get latest year's value
            }
            logging.info("Successfully parsed world comparison data.")
        else:
            logging.warning("Could not parse world market data for comparison.")
            final_data['world_comparison_data'] = None

        # --- STEP 5: Parse Your Country's Global Export Data ---
        logging.info("--- Parsing Your Country's Total Exports to the World ---")
        your_exports_data = parse_full_timeseries(
            value_file=all_downloaded_files.get('your_country_exports_value'),
            quantity_file=None, # We only need the total value, no need to parse other files
            unit_value_file=None,
            config=CONFIG
        )

        if your_exports_data and 'total_value_usd' in your_exports_data:
            final_data['your_country_total_exports'] = {
                "value_usd": your_exports_data['total_value_usd'],
                "year": your_exports_data['latest_year']
            }
            logging.info(f"Successfully extracted total export value: {your_exports_data['total_value_usd']} for year {your_exports_data['latest_year']}")
        else:
            logging.warning("Could not parse or find total export value for your country.")
            final_data['your_country_total_exports'] = None
        ### MODIFICATION END ###

        # --- SAVE FINAL OUTPUT ---
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=4)
        logging.info(f"SUCCESS: TradeMap data saved to {args.output}")

    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if scraper and scraper.driver:
            scraper.driver.quit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape TradeMap data.")
    parser.add_argument("--output", required=True, help="Path to save the output JSON file.")
    parser.add_argument("--headless", action='store_true', help="Run in headless mode.")
    # --- Add dynamic config arguments ---
    parser.add_argument("--hs-code", help="HS code for the product.")
    parser.add_argument("--your-country-id", help="Numeric ID for the exporting country.")
    parser.add_argument("--your-country-name", help="Name of the exporting country.")
    parser.add_argument("--target-market-id", help="Numeric ID for the target market.")
    parser.add_argument("--target-market-name", help="Name of the target market.")

    args = parser.parse_args()
    scrape_trademap(args)