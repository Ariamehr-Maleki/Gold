# scrapers/trademap_scraper.py
import argparse
import json
import logging
import os
import sys
import time
import math

sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
# Ensure we import the updated Downloader class
from support.data_downloader import DataDownloader
from support.data_parser import parse_snapshot_excel, parse_time_series, parse_companies_list
from scrapers.factsheet_generator import FactsheetGenerator

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger("TradeMapRunner")

class TradeMapScraperRunner:
    def __init__(self, args):
        self.args = args
        self.out_dir = os.path.dirname(self.args.output)
        self.config = self._initialize_config()
        driver_path = getattr(args, 'driver_path', r"./geckodriver.exe")
        self.scraper = DataDownloader(headless=args.headless, driver_path=driver_path)
        self.output_data = {
            "source": "Trade Map (trademap.org)",
            "snapshots": {},
            "meta": {}
        }

    def _initialize_config(self):
        return {
            "hs_code": self.args.hs_code or "847130",
            "product_name": self.args.hs_code or "Selected Product",
            "your_country_id": self.args.your_country_id or "156",
            "your_country_name": None,
            "target_market_id": self.args.target_market_id or "276",
            "target_market_name": None,
            "login_user": os.environ.get("TRADEMAP_USER", "mst.magpi@gmail.com"),
            "login_pass": os.environ.get("TRADEMAP_PASS", "1996")
        }

    def setup(self):
        if not self.scraper.set_driver(): raise Exception("Driver failed.")
        if not self.scraper.login(self.config['login_user'], self.config['login_pass']): raise Exception("Login failed.")

    def teardown(self):
        if self.scraper.driver: self.scraper.driver.quit()

    def _fetch_snapshot(self, nav_func, filename, key, desc, **kwargs):
        """Helper for standard snapshot downloads"""
        if nav_func(self.config, **kwargs):
            path = self.scraper.download_excel_file(filename)
            if path:
                raw_data = parse_snapshot_excel(path, self.out_dir)
                # Simple formatting
                cleaned = []
                for i, r in enumerate(raw_data, 1):
                    r['generated_rank'] = i
                    cleaned.append({k: (None if isinstance(v, float) and (math.isnan(v) or math.isinf(v)) else v) for k, v in r.items()})
                self.output_data["snapshots"][key] = {"snapshot_name": desc, "count": len(cleaned), "data": cleaned}
                
                # Dynamic Name Update
                detected = self.scraper.get_selected_country_name()
                if detected:
                    if "target" in key: self.config['target_market_name'] = detected
                    if "base" in key: self.config['your_country_name'] = detected

    def run(self):
        try:
            self.setup()
            
            # --- 1. Global Snapshots ---
            self._fetch_snapshot(self.scraper.navigate_to_global_exports, "global_exports.xls", "global_exports", "Global Exports")
            self._fetch_snapshot(self.scraper.navigate_to_global_imports, "global_imports.xls", "global_imports", "Global Imports")
            
            # --- 2. World Time Series ---
            # (Keeping this simplified as requested to focus on Base/Target)
            if self.scraper.navigate_to_world_view_page(self.config, "value"):
                p = self.scraper.download_excel_file("world_value_ts.xls")
                if p: self.output_data["snapshots"]["world_value_ts"] = {"type": "time_series", "data": parse_time_series(p, self.out_dir)}

            if self.scraper.navigate_to_world_view_page(self.config, "unit_value"):
                p = self.scraper.download_excel_file("world_unit_value_ts.xls")
                if p: self.output_data["snapshots"]["world_unit_value_ts"] = {"type": "time_series", "data": parse_time_series(p, self.out_dir)}

            # --- 3. Country Snapshots ---
            self._fetch_snapshot(
                self.scraper.navigate_to_country_snapshot_page, 
                "target_market_suppliers.xls", 
                "target_market_suppliers", 
                "Suppliers to Target", 
                country_id=self.config['target_market_id']
            )
            
            self._fetch_snapshot(
                self.scraper.navigate_to_base_country_global_exports, 
                "base_country_exports.xls", 
                "base_country_global_exports", 
                "Exports from Base", 
            )

            # =================================================================
            # STEP 6: TIME SERIES (Refactored strict order)
            # =================================================================
            
            def fetch_country_ts(country_id, role_prefix, flow_type):
                """
                Strict sequence: 
                1. Navigate (with flow type)
                2. Switch to Value -> Download
                3. Switch to Unit Value -> Download
                """
                logger.info(f"--- Processing Time Series for {role_prefix} (ID: {country_id}, Flow: {flow_type}) ---")
                
                # A. VALUE VIEW
                # We navigate specifically requesting 'value' first
                if self.scraper.navigate_to_country_view_page(
                    self.config, 
                    country_id=country_id, 
                    view="value", 
                    trade_flow=flow_type
                ):
                    # Check if navigation succeeded implicitly via the if
                    file_name = f"{role_prefix}_value_ts.xls"
                    path = self.scraper.download_excel_file(file_name)
                    if path:
                        self.output_data["snapshots"][f"{role_prefix}_value_ts"] = {
                            "type": "time_series",
                            "data": parse_time_series(path, self.out_dir)
                        }
                    else:
                        logger.error(f"Failed to download {file_name}")

                    # B. UNIT VALUE VIEW
                    # We are already on the correct page (Country + Flow). 
                    # We just need to switch the dropdown using the downloader's internal helper.
                    # Note: We call navigate again to be safe (it handles state checks), 
                    # OR we can trust the method to just flip the switch if URL matches.
                    # Calling navigate is safer to ensure metric switch logic runs.
                    if self.scraper.navigate_to_country_view_page(
                        self.config, 
                        country_id=country_id, 
                        view="unit_value", 
                        trade_flow=flow_type
                    ):
                        file_name = f"{role_prefix}_unit_value_ts.xls"
                        path = self.scraper.download_excel_file(file_name)
                        if path:
                            self.output_data["snapshots"][f"{role_prefix}_unit_value_ts"] = {
                                "type": "time_series",
                                "data": parse_time_series(path, self.out_dir)
                            }
                        else:
                            logger.error(f"Failed to download {file_name}")
                else:
                    logger.error(f"Could not load Time Series page for {role_prefix}")

            # 6A. FIRST: Base Country (Exports)
            # "load the time series for the base country ... check if everything is correct"
            self.scraper.driver.get("about:blank") # Clear state
            time.sleep(1)
            fetch_country_ts(
                self.config['your_country_id'], 
                "base_country", 
                "export" # <--- Crucial: Ensures we get Export data
            )

            # 6B. SECOND: Target Country (Imports)
            # "then go for target country"
            self.scraper.driver.get("about:blank") # Clear state
            time.sleep(1)
            fetch_country_ts(
                self.config['target_market_id'], 
                "target_market", 
                "import" # <--- Crucial: Ensures we get Import data
            )

            # --- 5. Companies (Last) ---
            if self.scraper.navigate_to_companies_page(self.config, country_id=self.config['target_market_id']):
                path = self.scraper.download_companies_file("target_market_companies.xls")
                if path:
                    self.output_data["snapshots"]["target_market_companies"] = {
                        "count": 0, # Parser calculates specific count
                        "data": parse_companies_list(path, self.out_dir)
                    }
                    self.output_data["snapshots"]["target_market_companies"]["count"] = len(self.output_data["snapshots"]["target_market_companies"]["data"])

            # Save Meta
            if self.scraper.official_product_name:
                self.output_data["meta"]["official_product_name"] = self.scraper.official_product_name

            # Generate Factsheet
            generator = FactsheetGenerator(self.output_data, self.config, output_dir=self.out_dir)
            self.output_data["factsheet"] = generator.generate()

            with open(self.args.output, 'w', encoding='utf-8') as f:
                json.dump(self.output_data, f, indent=4, ensure_ascii=False)
            
            logger.info(f"Process complete. Data saved to {self.args.output}")

        except Exception as e:
            logger.critical(f"Runner failed: {e}", exc_info=True)
            sys.exit(1)
        finally:
            self.teardown()

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", required=True)
    parser.add_argument("--headless", action='store_true')
    parser.add_argument("--hs-code")
    parser.add_argument("--your-country-id")
    parser.add_argument("--target-market-id")
    # Compatibility args
    parser.add_argument("--your-country-name")
    parser.add_argument("--target-market-name")
    
    args = parser.parse_args()
    TradeMapScraperRunner(args).run()