# scrapers/trademap_scraper.py
import argparse
import json
import logging
import os
import sys

# Add parent directories to path to allow importing from 'support'
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from support.data_downloader import DataDownloader
from support.data_parser import parse_full_timeseries, parse_world_importers_txt, parse_company_txt

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def scrape_trademap(args):
    """Main execution function for the TradeMap scraping process."""
    CONFIG = {
        "hs_code": "847130", "your_country": "China", "your_country_id": "156",
        "target_market": "United States of America", "target_market_id": "842",
        "login_user": os.environ.get("TRADEMAP_USER", "mst.magpi@gmail.com"),
        "login_pass": os.environ.get("TRADEMAP_PASS", "1996")
    }

    scraper = DataDownloader(headless=args.headless, driver_path=r"./geckodriver.exe")
    downloaded_files = {}
    final_data = {
        "source": "Trade Map (trademap.org)",
        "config": {k: v for k, v in CONFIG.items() if 'pass' not in k}
    }

    try:
        if not scraper.set_driver(): raise Exception("Failed to initialize WebDriver.")
        if not scraper.login(CONFIG['login_user'], CONFIG['login_pass']): raise Exception("Login failed.")

        logging.info("--- Starting File Downloads ---")
        if scraper.navigate_to_world_view_page(CONFIG, view='value'):
            downloaded_files['value'] = scraper._download_file(rename_to="world_values.txt")
        if scraper.navigate_to_world_view_page(CONFIG, view='quantity'):
            downloaded_files['quantity'] = scraper._download_file(rename_to="world_quantities.txt")
        if scraper.navigate_to_country_view_page(CONFIG, CONFIG['target_market_id'], trade_flow='I'):
            downloaded_files['importers'] = scraper._download_file(rename_to="target_importers.txt")
        if scraper.navigate_to_companies_page(CONFIG, trade_flow='I'):
            downloaded_files['companies'] = scraper._download_file(rename_to="company_list.txt")

        logging.info("--- Starting Data Parsing ---")
        final_data['market_analysis'] = parse_full_timeseries(
            downloaded_files.get('value'), downloaded_files.get('quantity'), None, CONFIG)
        final_data['importer_ranking'] = parse_world_importers_txt(downloaded_files.get('importers'), CONFIG)
        final_data['potential_importers'] = parse_company_txt(downloaded_files.get('companies'))

        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(final_data, f, ensure_ascii=False, indent=4)
        logging.info(f"SUCCESS: TradeMap data saved to {args.output}")

    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
        # Ensure script exits with a non-zero code on failure
        sys.exit(1)
    finally:
        if scraper and scraper.driver:
            scraper.driver.quit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape TradeMap data.")
    parser.add_argument("--output", required=True, help="Path to save the output JSON file.")
    parser.add_argument("--headless", action='store_true', help="Run in headless mode.")
    args = parser.parse_args()
    scrape_trademap(args)