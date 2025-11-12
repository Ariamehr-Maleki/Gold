# export_potential_analyzer.py (Standalone Version)

import json
import logging
import os
import time
from datetime import datetime

# --- Selenium and Webdriver Imports ---
from selenium import webdriver
from selenium.common.exceptions import TimeoutException, NoSuchElementException
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.common.by import By
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.wait import WebDriverWait

# --- Basic Logging Configuration ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

class ExportPotentialAnalyzer:
    """
    A standalone scraper for exportpotential.intracen.org.
    It combines browser management and scraping logic into a single class.
    """
    DEFAULT_WAIT = 20

    # --- Methods from spider_core.py are now integrated here ---

    def __init__(self, headless=False, driver_path='./geckodriver.exe', wait_seconds=None):
        logging.info("Standalone Scraper: initializing")
        self.driver = None
        self.wait = None
        self.actions = None
        self.headless = headless
        self.driver_path = driver_path
        self.wait_seconds = wait_seconds or self.DEFAULT_WAIT

    def set_driver(self):
        logging.info("Starting Firefox WebDriver")
        options = Options()
        try:
            firefox_path = r"C:\Program Files\Mozilla Firefox\firefox.exe"
            if os.path.exists(firefox_path):
                options.binary_location = firefox_path
        except Exception:
            logging.warning("Could not set Firefox binary location. Using default.")

        if self.headless:
            options.add_argument("--headless")

        options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0")
        service = Service(executable_path=self.driver_path)

        try:
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, self.wait_seconds)
            self.actions = ActionChains(self.driver)  # Initialize ActionChains here
            return True
        except Exception as e:
            logging.error(f"WebDriver failed to start. Check geckodriver/Firefox. Error: {e}")
            return False

    def _save_snapshot(self, label="snapshot"):
        debug_dir = 'debug_snapshots'
        os.makedirs(debug_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        filename_base = os.path.join(debug_dir, f"{label}_{timestamp}")
        try:
            self.driver.save_screenshot(f"{filename_base}.png")
            logging.info(f"Saved screenshot to {filename_base}.png")
            with open(f"{filename_base}.html", 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
            logging.info(f"Saved page source to {filename_base}.html")
        except Exception as e:
            logging.error(f"Failed to save snapshot: {e}")

    def goto(self, url):
        logging.info(f"Navigating to {url}")
        try:
            self.driver.get(url)
            # Wait for the main app container to be present
            WebDriverWait(self.driver, self.wait_seconds).until(
                EC.presence_of_element_located((By.TAG_NAME, "app-root"))
            )
            logging.info("Successfully loaded URL.")
            return True
        except Exception as e:
            logging.error(f"Error while navigating to {url}: {e}")
            return False

    # --- Scraper-specific logic starts here ---

    def handle_popup(self):
        try:
            wait = WebDriverWait(self.driver, 7)
            checkbox_input_locator = (By.ID, "mat-mdc-checkbox-1-input")
            logging.info("Checking for 'What's New' popup...")
            
            checkbox = wait.until(EC.presence_of_element_located(checkbox_input_locator))
            close_button_locator = (By.XPATH, "//button[contains(@class, 'mat-mdc-dialog-close-button')]")

            if not checkbox.is_selected():
                self.driver.execute_script("arguments[0].click();", checkbox)
                logging.info("Clicked 'Do not show again' checkbox.")
            
            self.driver.find_element(*close_button_locator).click()
            logging.info("Closed the popup.")
            wait.until(EC.invisibility_of_element_located((By.CLASS_NAME, "cdk-overlay-backdrop")))
        except TimeoutException:
            logging.info("No popup was detected.")
        except Exception as e:
            logging.error(f"An error occurred while handling the popup: {e}")

    def select_product(self, hs_code):
        """
        Uses the search bar to find and select the specific product with improved timing
        to prevent "rushing".
        """
        try:
            logging.info(f"Attempting to select product with HS code: {hs_code}")
            
            # 1. Enter search text
            search_input = self.wait.until(EC.element_to_be_clickable((By.ID, "mat-input-0")))
            search_input.clear()
            search_input.send_keys(hs_code)
            logging.info(f"Entered '{hs_code}' into the product search bar.")
            
            # --- FIX: Add a hard wait to let the UI filter and settle down ---
            logging.info("Waiting for product list to filter...")
            time.sleep(2.5) # Increased wait time

            # 2. Deselect all with a retry mechanism
            try:
                deselect_all_locator = (By.XPATH, "//span[contains(text(), 'Deselect all')]")
                # Wait for the button to be fully clickable
                deselect_button = self.wait.until(EC.element_to_be_clickable(deselect_all_locator))
                
                # Try clicking, and if it fails, wait and try again
                try:
                    deselect_button.click()
                except Exception as e:
                    logging.warning(f"First click on 'Deselect all' failed ({e}), retrying...")
                    time.sleep(1)
                    deselect_button.click() # Retry the click

                logging.info("Deselected all default products.")
                time.sleep(0.5) # Small pause after successful click
            except TimeoutException:
                logging.warning("'Deselect all' button not clickable or found. This might be okay if nothing was selected.")
            
            # 3. Select the target product
            product_checkbox_label = self.wait.until(EC.element_to_be_clickable((By.XPATH, f"//mat-checkbox[contains(., '{hs_code}')]//label")))
            product_checkbox_label.click()
            logging.info(f"Selected product '{hs_code}'.")
            
            # 4. Wait for the chart to visually update before proceeding
            logging.info("Waiting for treemap to update...")
            time.sleep(4) # Increased wait to ensure visualization is fully rendered
            return True

        except Exception as e:
            logging.error(f"Failed to select the product: {e}", exc_info=True)
            self._save_snapshot("product_selection_failed")
            return False

    def scrape_product_potential(self):
        """Hovers over the single product rectangle and scrapes its tooltip data."""
        try:
            logging.info("Scraping data from the updated treemap...")
            product_rect = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "g.node")))
            
            # Hover to activate the tooltip
            self.actions.move_to_element(product_rect).perform()
            time.sleep(0.5) # Wait for tooltip to appear

            tooltip = self.driver.find_element(By.CSS_SELECTOR, "div.d3-tip.treemap[style*='opacity: 1']")
            
            # --- FIX: The XPath for 'Baseline exports' is different ---
            def get_tooltip_value(text_label, is_strong=True):
                try:
                    # The value is in the next sibling span of the span containing the label
                    base_xpath = f".//span[contains(., '{text_label}')]/following-sibling::span"
                    if is_strong:
                        # For 'Export potential' and 'Unrealized potential', the value is in a nested <strong> tag
                        return tooltip.find_element(By.XPATH, f"{base_xpath}/strong").text
                    else:
                        # For 'Baseline exports', the value is directly in the span
                        return tooltip.find_element(By.XPATH, base_xpath).text
                except NoSuchElementException:
                    return None

            analysis = {
                "product": tooltip.find_element(By.CSS_SELECTOR, "h4.tooltip-title").text,
                "export_potential": get_tooltip_value("Export potential"),
                "unrealized_potential": get_tooltip_value("Unrealized potential"),
                # Call the helper with is_strong=False for this specific case
                "baseline_exports": get_tooltip_value("Baseline exports", is_strong=False)
            }
            
            logging.info("Successfully scraped product potential data.")
            return analysis

        except Exception as e:
            logging.error(f"Failed during treemap scraping: {e}", exc_info=True)
            self._save_snapshot("treemap_scrape_failed")
            return {}

    def analyze_export_potential(self, config):
        exporter_id = config['your_country_id']
        market_id = config['target_market_id']
        product_id = config['hs_code']
        url = f"https://exportpotential.intracen.org/en/products/tree-map?fromMarker=i&exporter={exporter_id}&toMarker=j&market={market_id}&whatMarker=k"
        
        if not self.goto(url):
            return None
        
        self.handle_popup()
        if not self.select_product(product_id):
            return None
            
        analysis_data = self.scrape_product_potential()
        
        return {
            "source": "Export Potential Map (exportpotential.intracen.org)",
            "analysis": analysis_data
        }

if __name__ == '__main__':
    CONFIG = {
        "hs_code": "847130",
        "your_country_id": "156",
        "target_market_id": "842",
    }

    s = ExportPotentialAnalyzer(headless=True, driver_path=r".\geckodriver.exe")
    
    try:
        if s.set_driver():
            export_potential_data = s.analyze_export_potential(CONFIG)
            if export_potential_data and export_potential_data.get('analysis'):
                with open("export_potential_analysis.json", 'w', encoding='utf-8') as f:
                    json.dump(export_potential_data, f, ensure_ascii=False, indent=4)
                logging.info("Successfully saved analysis to export_potential_analysis.json")
            else:
                logging.error("Analysis failed, no data was returned or scraped.")
    except Exception as e:
        logging.critical(f"A critical error occurred: {e}", exc_info=True)
    finally:
        if s and s.driver:
            input("Press Enter to close the browser...")
            s.driver.quit()