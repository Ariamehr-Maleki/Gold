# scrapers/potential_scraper.py

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, TimeoutException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

# Add parent directories to path to allow importing from 'support' if needed in the future
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Basic Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ExportPotentialAnalyzer:
    """
    A standalone scraper for exportpotential.intracen.org.
    """
    DEFAULT_WAIT = 20

    def __init__(self, headless=False, driver_path='./geckodriver.exe', wait_seconds=None):
        self.driver = None
        self.wait = None
        self.actions = None
        self.headless = headless
        self.driver_path = driver_path
        self.wait_seconds = wait_seconds or self.DEFAULT_WAIT

    # ... (All internal methods like set_driver, goto, handle_popup, select_product, etc. remain unchanged) ...
    def set_driver(self):
        logging.info("Starting Firefox WebDriver")
        options = Options()
        if os.path.exists(r"C:\Program Files\Mozilla Firefox\firefox.exe"):
            options.binary_location = r"C:\Program Files\Mozilla Firefox\firefox.exe"
        if self.headless: options.add_argument("--headless")
        
        service = Service(executable_path=self.driver_path)
        try:
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, self.wait_seconds)
            self.actions = ActionChains(self.driver)
            return True
        except Exception as e:
            logging.error(f"WebDriver failed to start: {e}")
            return False

    def _save_snapshot(self, label="snapshot"):
        debug_dir = 'debug_snapshots'
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = os.path.join(debug_dir, f"{label}_{timestamp}")
        self.driver.save_screenshot(f"{filename_base}.png")

    def goto(self, url):
        logging.info(f"Navigating to {url}")
        try:
            self.driver.get(url)
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "app-root")))
            return True
        except Exception as e:
            logging.error(f"Error while navigating to {url}: {e}")
            return False

    def handle_popup(self):
        try:
            wait = WebDriverWait(self.driver, 7)

            # Try to detect popup root first
            popup_present = wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, ".mat-mdc-dialog-container"))
            )

            if popup_present:
                try:
                    checkbox = self.driver.find_element(By.ID, "mat-mdc-checkbox-1-input")
                    if not checkbox.is_selected():
                        self.driver.execute_script("arguments[0].click();", checkbox)
                except Exception:
                    logging.info("Checkbox not found inside popup (ignoring).")

                # Now try to close the popup safely
                try:
                    close_btn = self.driver.find_element(
                        By.XPATH,
                        "//button[contains(@class, 'mat-mdc-dialog-close-button')]"
                    )
                    close_btn.click()
                    wait.until(EC.invisibility_of_element_located(
                        (By.CLASS_NAME, "cdk-overlay-backdrop")
                    ))
                    logging.info("Popup closed.")
                except Exception:
                    logging.info("Close button not found — popup may already be absent.")

        except TimeoutException:
            # Fully OK → means popup was not shown at all
            logging.info("No popup was detected (timeout).")

    def select_product(self, hs_code):
        try:
            search_input = self.wait.until(EC.element_to_be_clickable((By.ID, "mat-input-0")))
            search_input.clear()
            search_input.send_keys(hs_code)
            time.sleep(2.5)

            try:
                deselect_button = self.wait.until(EC.element_to_be_clickable((By.XPATH, "//span[contains(text(), 'Deselect all')]")))
                deselect_button.click()
                time.sleep(0.5)
            except TimeoutException:
                logging.warning("'Deselect all' button not found.")
            
            product_checkbox_label = self.wait.until(EC.element_to_be_clickable((By.XPATH, f"//mat-checkbox[contains(., '{hs_code}')]//label")))
            product_checkbox_label.click()
            time.sleep(4)
            return True
        except Exception as e:
            logging.error(f"Failed to select the product: {e}", exc_info=True)
            self._save_snapshot("product_selection_failed")
            return False

    def scrape_product_potential(self):
        try:
            product_rect = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "g.node")))
            self.actions.move_to_element(product_rect).perform()
            time.sleep(0.5)
            tooltip = self.driver.find_element(By.CSS_SELECTOR, "div.d3-tip.treemap[style*='opacity: 1']")
            
            def get_tooltip_value(text_label, is_strong=True):
                try:
                    base_xpath = f".//span[contains(., '{text_label}')]/following-sibling::span"
                    return tooltip.find_element(By.XPATH, f"{base_xpath}{'/strong' if is_strong else ''}").text
                except NoSuchElementException:
                    return None
            
            return {
                "product": tooltip.find_element(By.CSS_SELECTOR, "h4.tooltip-title").text,
                "export_potential": get_tooltip_value("Export potential"),
                "unrealized_potential": get_tooltip_value("Unrealized potential"),
                "baseline_exports": get_tooltip_value("Baseline exports", is_strong=False)
            }
        except Exception as e:
            logging.error(f"Failed during treemap scraping: {e}", exc_info=True)
            self._save_snapshot("treemap_scrape_failed")
            return {}

    def analyze_export_potential(self, config):
        url = (f"https://exportpotential.intracen.org/en/products/tree-map?"
               f"fromMarker=i&exporter={config['your_country_id']}&"
               f"toMarker=j&market={config['target_market_id']}&whatMarker=k")
        
        if not self.goto(url): return None
        
        self.handle_popup()
        if not self.select_product(config['hs_code']): return None
            
        return {
            "source": "Export Potential Map (exportpotential.intracen.org)",
            "analysis": self.scrape_product_potential()
        }

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Scrape Export Potential Map data.")
    parser.add_argument("--output", required=True, help="Path to save the output JSON file.")
    parser.add_argument("--headless", action='store_true', help="Run in headless mode.")
    # --- Add dynamic config arguments ---
    parser.add_argument("--hs-code", help="HS code for the product.")
    parser.add_argument("--your-country-id", help="Numeric ID for the exporting country.")
    parser.add_argument("--target-market-id", help="Numeric ID for the target market.")
    # Unused, but added for consistency with orchestrator
    parser.add_argument("--your-country-name", help="Unused.")
    parser.add_argument("--target-market-name", help="Unused.")
    
    args = parser.parse_args()
    
    # Default CONFIG
    CONFIG = {
        "hs_code": "847130",
        "your_country_id": "156",
        "target_market_id": "842",
    }

    # Override with command-line arguments if provided
    if args.hs_code: CONFIG['hs_code'] = args.hs_code
    if args.your_country_id: CONFIG['your_country_id'] = args.your_country_id
    if args.target_market_id: CONFIG['target_market_id'] = args.target_market_id

    s = ExportPotentialAnalyzer(headless=args.headless, driver_path=r".\geckodriver.exe")
    
    try:
        if s.set_driver():
            export_potential_data = s.analyze_export_potential(CONFIG)
            if export_potential_data and export_potential_data.get('analysis'):
                with open(args.output, 'w', encoding='utf-8') as f:
                    json.dump(export_potential_data, f, ensure_ascii=False, indent=4)
                logging.info(f"Successfully saved analysis to {args.output}")
            else:
                logging.error("Analysis failed, no data was returned or scraped.")
                sys.exit(1)
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if s and s.driver:
            s.driver.quit()