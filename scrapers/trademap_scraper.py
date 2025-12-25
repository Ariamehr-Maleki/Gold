# scrapers/trademap_scraper.py
import argparse
import json
import logging
import os
import sys
import math

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
from support.data_downloader import DataDownloader
from support.data_parser import parse_snapshot_excel
from scrapers.factsheet_generator import FactsheetGenerator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradeMapRunner")

class TradeMapScraperRunner:
    def __init__(self, args):
        self.args = args
        self.config = self._initialize_config()
        self.scraper = DataDownloader(headless=args.headless, driver_path=r"./geckodriver.exe")
        self.output_data = {
            "source": "Trade Map (trademap.org)",
            "snapshots": {}
        }

    def _initialize_config(self):
        return {
            "hs_code": self.args.hs_code or "847130",
            # We don't know the names yet, will detect them at runtime
            "product_name": self.args.hs_code or "Selected Product",
            "your_country_id": self.args.your_country_id or "156",
            "your_country_name": None,  # Will be populated dynamically
            "target_market_id": self.args.target_market_id or "276",
            "target_market_name": None, # Will be populated dynamically
            "login_user": os.environ.get("TRADEMAP_USER", "mst.magpi@gmail.com"),
            "login_pass": os.environ.get("TRADEMAP_PASS", "1996")
        }

    def _process_parsed_data(self, raw_data, snapshot_name):
        if not raw_data:
            return {
                "snapshot_name": snapshot_name,
                "count": 0,
                "data": []
            }

        cleaned_list = []
        for index, record in enumerate(raw_data, start=1):
            cleaned_record = {}
            # Add explicit rank
            cleaned_record['generated_rank'] = index

            for key, value in record.items():
                # Handle NaN / Inf
                if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
                    cleaned_record[key] = None
                else:
                    cleaned_record[key] = value
            
            cleaned_list.append(cleaned_record)

        return {
            "snapshot_name": snapshot_name,
            "count": len(cleaned_list),
            "data": cleaned_list
        }

    def setup(self):
        if not self.scraper.set_driver(): raise Exception("Driver failed.")
        if not self.scraper.login(self.config['login_user'], self.config['login_pass']): raise Exception("Login failed.")

    def run(self):
        try:
            self.setup()
            out_dir = os.path.dirname(self.args.output)
            
            # 1. Global Exports (Snapshot)
            # Formerly World Snapshot
            if self.scraper.navigate_to_global_exports(self.config):
                path = self.scraper.download_excel_file("global_exports.xls")
                if path:
                    raw_data = parse_snapshot_excel(path, out_dir)
                    self.output_data["snapshots"]["global_exports"] = self._process_parsed_data(
                        raw_data, "Global Exports"
                    )

            # 1.5 Global Imports (New)
            if self.scraper.navigate_to_global_imports(self.config):
                path = self.scraper.download_excel_file("global_imports.xls")
                if path:
                    raw_data = parse_snapshot_excel(path, out_dir)
                    self.output_data["snapshots"]["global_imports"] = self._process_parsed_data(
                        raw_data, "Global Imports"
                    )

            # 2. Target Market Suppliers
            if self.scraper.navigate_to_country_snapshot_page(self.config, self.config['target_market_id']):
                # --- DYNAMICALLY GET TARGET NAME ---
                target_name = self.scraper.get_selected_country_name()
                if target_name:
                    logger.info(f"Dynamically detected Target Market Name: {target_name}")
                    self.config['target_market_name'] = target_name
                # -----------------------------------

                path = self.scraper.download_excel_file("target_market_suppliers.xls")
                if path:
                    raw_data = parse_snapshot_excel(path, out_dir)
                    self.output_data["snapshots"]["target_market_suppliers"] = self._process_parsed_data(
                        raw_data, 
                        f"List of supplying markets for product imported by {self.config.get('target_market_name', 'ID ' + self.config['target_market_id'])}"
                    )

            # 3. Base Country Exports
            if self.scraper.navigate_to_base_country_global_exports(self.config):
                # --- DYNAMICALLY GET YOUR COUNTRY NAME ---
                yc_name = self.scraper.get_selected_country_name()
                if yc_name:
                    logger.info(f"Dynamically detected Your Country Name: {yc_name}")
                    self.config['your_country_name'] = yc_name
                # -----------------------------------------

                path = self.scraper.download_excel_file("base_country_exports.xls")
                if path:
                    raw_data = parse_snapshot_excel(path, out_dir)
                    self.output_data["snapshots"]["base_country_global_exports"] = self._process_parsed_data(
                        raw_data, 
                        f"List of importing markets for product exported by {self.config.get('your_country_name', 'ID ' + self.config['your_country_id'])}"
                    )

            # 4. Generate Factsheet
            logger.info("Generating Quantitative Factsheet JSON...")
            # Pass the Config which now has correct names
            generator = FactsheetGenerator(self.output_data, self.config)
            factsheet_json = generator.generate()
            
            self.output_data["factsheet"] = factsheet_json

            with open(self.args.output, 'w', encoding='utf-8') as f:
                json.dump(self.output_data, f, indent=4, ensure_ascii=False)
            
            logger.info(f"Process complete. Data saved to {self.args.output}")

        except Exception as e:
            logger.critical(f"Runner failed: {e}", exc_info=True)
            sys.exit(1)
        finally:
            if self.scraper.driver: self.scraper.driver.quit()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--headless", action='store_true')
    parser.add_argument("--hs-code")
    parser.add_argument("--your-country-id")
    parser.add_argument("--target-market-id")
    args = parser.parse_args()
    TradeMapScraperRunner(args).run()