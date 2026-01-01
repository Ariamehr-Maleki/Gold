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
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

# Add parent directories to path to allow importing from 'support' if needed
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

# --- Basic Logging Configuration ---
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

class ExportPotentialAnalyzer:
    """
    A standalone scraper for exportpotential.intracen.org.
    """
    DEFAULT_WAIT = 30  # Increased default wait time

    def __init__(self, headless=False, driver_path='./geckodriver.exe', wait_seconds=None):
        self.driver = None
        self.wait = None
        self.actions = None
        self.headless = headless
        self.driver_path = driver_path
        self.wait_seconds = wait_seconds or self.DEFAULT_WAIT

    def set_driver(self):
        logging.info("Starting Firefox WebDriver")
        options = Options()
        # Auto-detect Firefox path if on Windows
        if os.path.exists(r"C:\Program Files\Mozilla Firefox\firefox.exe"):
            options.binary_location = r"C:\Program Files\Mozilla Firefox\firefox.exe"
        if self.headless: options.add_argument("--headless")
        
        service = Service(executable_path=self.driver_path)
        try:
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, self.wait_seconds)
            self.actions = ActionChains(self.driver)
            self.driver.maximize_window()
            return True
        except Exception as e:
            logging.error(f"WebDriver failed to start: {e}")
            return False

    def _save_snapshot(self, label="snapshot"):
        debug_dir = 'debug_snapshots'
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = os.path.join(debug_dir, f"{label}_{timestamp}")
        try:
            self.driver.save_screenshot(f"{filename_base}.png")
        except Exception:
            pass

    def goto(self, url):
        logging.info(f"Navigating to {url}")
        try:
            self.driver.get(url)
            # Wait for the main app root to ensure page load started
            self.wait.until(EC.presence_of_element_located((By.TAG_NAME, "app-root")))
            time.sleep(3) # Initial stability wait
            return True
        except Exception as e:
            logging.error(f"Error while navigating to {url}: {e}")
            return False

    def handle_popup(self):
        """
        Detects the survey popup and clicks the close icon using a robust CSS selector.
        """
        logging.info("Checking for popup...")
        try:
            # 1. Wait briefly for the dialog container to appear
            # We use a shorter wait so we don't waste time if it doesn't appear
            short_wait = WebDriverWait(self.driver, 10)
            
            dialog = short_wait.until(
                EC.presence_of_element_located((By.TAG_NAME, "mat-dialog-container"))
            )
            logging.info("Popup detected. Waiting for animation...")
            time.sleep(2) # Wait for popup animation to settle

            # 2. Find the close icon using CSS Selector (Safe from Namespace Errors)
            # The structure is <div class="survey-dialog-title"><svg class="icon">...</svg></div>
            close_btn = self.driver.find_element(By.CSS_SELECTOR, ".survey-dialog-title svg.icon")
            
            # 3. Click the icon
            logging.info("Clicking close icon...")
            self.actions.move_to_element(close_btn).click().perform()
            
            # 4. Wait for it to disappear
            self.wait.until(EC.invisibility_of(dialog))
            logging.info("Popup closed successfully.")
            time.sleep(2) # Extra wait after closing to ensure overlay is gone

        except TimeoutException:
            logging.info("No popup detected (timeout). Proceeding...")
        except NoSuchElementException:
            logging.warning("Popup container found, but close icon not found. Trying ESC key.")
            ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
            time.sleep(2)
        except Exception as e:
            logging.warning(f"Error handling popup: {e}. Trying ESC key fallback.")
            try:
                ActionChains(self.driver).send_keys(Keys.ESCAPE).perform()
                time.sleep(2)
            except:
                pass

    def select_product(self, hs_code):
        try:
            logging.info("Attempting to select product...")
            
            # Extra wait before interacting with input
            time.sleep(2)

            # Wait for input to be interactive
            search_input = self.wait.until(EC.element_to_be_clickable((By.ID, "mat-input-0")))
            search_input.clear()
            logging.info(f"Typing HS Code: {hs_code}")
            search_input.send_keys(hs_code)
            
            # WAIT for suggestions to load
            time.sleep(8) 

            # Try to deselect all first (if button exists)
            try:
                deselect_button = self.driver.find_element(By.XPATH, "//span[contains(text(), 'Deselect all')]")
                if deselect_button.is_displayed():
                    deselect_button.click()
                    logging.info("Clicked 'Deselect all'.")
                    time.sleep(3)
            except (NoSuchElementException, TimeoutException):
                logging.warning("'Deselect all' button not found or hidden. Skipping.")
            
            # Click the specific checkbox label
            logging.info("Selecting specific HS code checkbox...")
            product_xpath = f"//mat-checkbox[contains(., '{hs_code}')]//label"
            product_checkbox_label = self.wait.until(EC.element_to_be_clickable((By.XPATH, product_xpath)))
            
            # Scroll to element to ensure it's in view
            self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", product_checkbox_label)
            time.sleep(1)
            
            product_checkbox_label.click()
            logging.info("Product selected. Waiting for chart to update...")
            
            # Generous wait for the visualization to render
            time.sleep(10) 
            return True
        except Exception as e:
            logging.error(f"Failed to select the product: {e}", exc_info=True)
            self._save_snapshot("product_selection_failed")
            return False

    def scrape_product_potential(self):
        try:
            logging.info("Locating treemap node...")
            # Locate the treemap node
            product_rect = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "g.node")))
            
            # Hover to trigger tooltip
            self.actions.move_to_element(product_rect).perform()
            time.sleep(1) # Wait for tooltip to fade in
            
            # Find the tooltip
            tooltip = self.driver.find_element(By.CSS_SELECTOR, "div.d3-tip.treemap[style*='opacity: 1']")
            
            def get_tooltip_value(text_label, is_strong=True):
                try:
                    # XPath to find value relative to label
                    base_xpath = f".//span[contains(., '{text_label}')]/following-sibling::span"
                    val_elem = tooltip.find_element(By.XPATH, f"{base_xpath}{'/strong' if is_strong else ''}")
                    return val_elem.text.strip()
                except NoSuchElementException:
                    return None
            
            data = {
                "product": tooltip.find_element(By.CSS_SELECTOR, "h4.tooltip-title").text.strip(),
                "export_potential": get_tooltip_value("Export potential"),
                "unrealized_potential": get_tooltip_value("Unrealized potential"),
                "baseline_exports": get_tooltip_value("Baseline exports", is_strong=False)
            }
            logging.info(f"Scraped Data: {data}")
            return data

        except Exception as e:
            logging.error(f"Failed during treemap scraping: {e}", exc_info=True)
            self._save_snapshot("treemap_scrape_failed")
            return {}

    def analyze_export_potential(self, config):
        url = (f"https://exportpotential.intracen.org/en/products/tree-map?"
               f"fromMarker=i&exporter={config['your_country_id']}&"
               f"toMarker=j&market={config['target_market_id']}&whatMarker=k")
        
        if not self.goto(url): return None
        
        # --- Handle the Survey Popup FIRST ---
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
    
    parser.add_argument("--hs-code", help="HS code for the product.")
    parser.add_argument("--your-country-id", help="Numeric ID for the exporting country.")
    parser.add_argument("--target-market-id", help="Numeric ID for the target market.")
    parser.add_argument("--your-country-name", help="Unused.")
    parser.add_argument("--target-market-name", help="Unused.")
    
    args = parser.parse_args()
    
    CONFIG = {
        "hs_code": "847130",
        "your_country_id": "156",
        "target_market_id": "842",
    }

    if args.hs_code: CONFIG['hs_code'] = args.hs_code
    if args.your_country_id: CONFIG['your_country_id'] = args.your_country_id
    if args.target_market_id: CONFIG['target_market_id'] = args.target_market_id

    s = ExportPotentialAnalyzer(headless=args.headless, driver_path=r".\geckodriver.exe")
    
    try:
        if s.set_driver():
            export_potential_data = s.analyze_export_potential(CONFIG)
            
            # Construct final payload
            if export_potential_data and export_potential_data.get('analysis'):
                final_output = export_potential_data
            else:
                # If scraping failed or returned empty analysis
                final_output = {
                    "source": "Export Potential Map",
                    "error": "No data found or scraping failed",
                    "analysis": {}
                }

            # Write to file
            with open(args.output, 'w', encoding='utf-8') as f:
                json.dump(final_output, f, ensure_ascii=False, indent=4)
            
            logging.info(f"Successfully saved analysis to {args.output}")
            print(json.dumps(final_output, indent=4))
            
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
        sys.exit(1)
    finally:
        if s and s.driver:
            s.driver.quit()