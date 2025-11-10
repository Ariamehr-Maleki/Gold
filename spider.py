from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    StaleElementReferenceException,
    ElementClickInterceptedException,
    NoSuchElementException,
)
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import Select
from selenium.webdriver import ActionChains
from selenium.webdriver.common.keys import Keys
import pandas as pd
from bs4 import BeautifulSoup as bs
import time
import random
import logging
import os
import json
from datetime import datetime

# The 'setlog' module is a custom module, assumed to be in the same directory.
# If it doesn't exist, you can replace 'setlog()' with a basic logging configuration.
try:
    from setlog import setlog
except ImportError:
    def setlog():
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        return logging.getLogger(__name__)

# Initialize logging
logging = setlog()


class TradeSpider(object):
    """
    A web scraper for trademap.org using Selenium.
    Handles login, navigation, data selection, and extraction for a Quantitative Export Factsheet.
    """
    DEFAULT_WAIT = 15

    def __init__(self, headless=False, driver_path='./geckodriver', wait_seconds=None):
        logging.info("TradeSpider: initializing")
        self.driver = None
        self.wait = None
        self.headless = headless
        self.driver_path = driver_path
        self.wait_seconds = wait_seconds or self.DEFAULT_WAIT

    def set_driver(self):
        """Configures and launches the Firefox WebDriver."""
        logging.info("Starting Firefox WebDriver")
        options = Options()
        if self.headless:
            options.add_argument("--headless")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        
        options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0")
        options.set_preference("dom.webdriver.enabled", False)
        options.set_preference("useAutomationExtension", False)
        
        service = Service(self.driver_path)
        self.driver = webdriver.Firefox(service=service, options=options)
        
        self.driver.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
        
        self.driver.set_page_load_timeout(60)
        self.driver.set_script_timeout(60)
        self.wait = WebDriverWait(self.driver, self.wait_seconds)

    def _save_snapshot(self, label="snapshot"):
        os.makedirs('debug_snapshots', exist_ok=True)
        timestamp = int(time.time())
        html_file = f"debug_snapshots/{label}_{timestamp}.html"
        png_file = f"debug_snapshots/{label}_{timestamp}.png"
        try:
            with open(html_file, 'w', encoding='utf-8') as f:
                f.write(self.driver.page_source)
            self.driver.save_screenshot(png_file)
            logging.debug(f"Saved snapshot: {html_file}, {png_file}")
        except Exception as e:
            logging.warning(f"Failed to save snapshot: {e}")

    def _wait_for_ready_state(self, timeout=20):
        logging.debug("Waiting for document.readyState == 'complete'")
        try:
            WebDriverWait(self.driver, timeout).until(
                lambda d: d.execute_script('return document.readyState') == 'complete'
            )
            return True
        except TimeoutException:
            logging.debug("Document readyState did not become 'complete' within timeout")
            return False

    def _safe_click(self, by, locator, attempts=3, sleep_between=0.5):
        last_exception = None
        for attempt in range(1, attempts + 1):
            try:
                logging.debug(f"Attempt {attempt}: Locating element {by}={locator} to click")
                el = self.wait.until(EC.element_to_be_clickable((by, locator)))
                el.click()
                logging.debug("Clicked element via Selenium .click()")
                return True
            except (StaleElementReferenceException, ElementClickInterceptedException) as e:
                logging.debug(f"Click failed ({type(e).__name__}), trying JS click.")
                try:
                    self.driver.execute_script('arguments[0].click();', el)
                    logging.debug("Clicked element via JS click")
                    return True
                except Exception as e2:
                    last_exception = e2
            except Exception as e:
                last_exception = e
                logging.debug(f"Unexpected exception on click attempt {attempt}: {e}")

            time.sleep(sleep_between)
        logging.error(f"_safe_click failed for {by}={locator} after {attempts} attempts. Last exception: {last_exception}")
        return False

    def goto(self, url):
        logging.info(f"Navigating to {url}")
        try:
            self.driver.get(url)
            self._wait_for_ready_state(timeout=30)
            logging.debug(f"Navigation successful. Current URL: {self.driver.current_url}")
            return True
        except Exception as e:
            logging.error(f"Error while navigating to {url}: {e}")
            self._save_snapshot('nav_error')
            return False

    def login(self, ac, pw):
        url = "https://www.trademap.org/Country_SelProduct_TS.aspx"
        if not self.goto(url):
            logging.error("Could not open initial page. Aborting login.")
            return False

        logging.info("Waiting for the initial page to settle before clicking login...")
        time.sleep(random.uniform(5.0, 8.0))

        try:
            logging.debug("Attempting to click the initial login button.")
            login_btn_id = 'ctl00_MenuControl_marmenu_login'
            if not self._safe_click(By.ID, login_btn_id, attempts=3):
                 raise Exception("Could not click initial login button")
            time.sleep(random.uniform(2, 4))
        except Exception as e:
            logging.error(f"Failed to interact with initial login button: {e}")
            self._save_snapshot('login_button_missing')
            return False

        try:
            logging.debug("Waiting for login page to load.")
            self.wait.until(EC.presence_of_element_located((By.ID, 'Username')))
        except TimeoutException:
            logging.error(f"Login page did not load. Current URL: {self.driver.current_url}")
            self._save_snapshot('login_page_not_loaded')
            return False

        try:
            logging.debug("Filling username and password.")
            usr = self.driver.find_element(By.ID, 'Username')
            pwd = self.driver.find_element(By.ID, 'Password')
            usr.clear()
            for char in ac:
                usr.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
            time.sleep(random.uniform(0.5, 1.0))
            pwd.clear()
            for char in pw:
                pwd.send_keys(char)
                time.sleep(random.uniform(0.05, 0.15))
        except Exception as e:
            logging.error(f"Error while filling credentials: {e}")
            self._save_snapshot('login_fill_error')
            return False

        time.sleep(random.uniform(1.0, 3.0))

        submit_button_xpath = "//button[@name='button' and @value='login']"
        if not self._safe_click(By.XPATH, submit_button_xpath, attempts=3):
            logging.error("All methods to submit login form failed.")
            self._save_snapshot('login_submit_failed')
            return False

        try:
            logging.debug("Waiting for redirection after login or for a CAPTCHA page.")
            wait_long = WebDriverWait(self.driver, 30)
            wait_long.until(
                EC.any_of(
                    EC.url_contains("Country_SelProduct_TS.aspx"),
                    EC.url_contains("stCaptcha.aspx")
                )
            )

            if "stCaptcha.aspx" in self.driver.current_url:
                logging.warning("CAPTCHA page detected. Please solve it in the browser.")
                print("\n" + "="*60)
                print("ACTION REQUIRED: Please solve the CAPTCHA in the browser window.")
                print("The script will automatically resume once you are redirected.")
                print("="*60 + "\n")

                wait_for_captcha_solve = WebDriverWait(self.driver, 300)
                wait_for_captcha_solve.until_not(
                    EC.url_contains("stCaptcha.aspx"),
                    message="Timed out waiting for CAPTCHA to be solved."
                )
                logging.info("CAPTCHA appears to be solved. Resuming script.")

            self._wait_for_ready_state(timeout=30)
            logging.info("Successfully redirected after login.")

        except TimeoutException as e:
            logging.error(f"Failed to redirect after login or CAPTCHA timed out. Last URL: {self.driver.current_url}. Error: {e.msg}")
            self._save_snapshot('post_login_redirect_failed')
            return False
        
        try:
            page_title = self.driver.title
            logging.info(f"Page title after login: {page_title}")
            if "trade map" in page_title.lower():
                logging.info("Login successful!")
                return True
            else:
                logging.error("Login may have failed (page title check).")
                self._save_snapshot('login_verification_failed')
                return False
        except Exception as e:
            logging.error(f"Error verifying login success: {e}")
            self._save_snapshot('login_verify_error')
            return False

    def navigate_to_main_page(self, product_code, country, partner=""):
        """Navigates to the main data selection page."""
        logging.info(f"Navigating to main page for product {product_code}")
        # This is the updated URL structure
        url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm=1|{country}||||{product_code}|||4|1|1|2|2|1|2|1|1|1"
        if partner:
            url += f"&partner={partner}"
        return self.goto(url)

    def get_data_as_dataframe(self):
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, 'ctl00_PageContent_GridViewPanelControl_DDL_PageSize')))
            Select(self.driver.find_element(By.ID, 'ctl00_PageContent_GridViewPanelControl_DDL_PageSize')).select_by_value('100')
            time.sleep(2) 
            self._wait_for_ready_state(15)

            table_element = self.wait.until(
                EC.presence_of_element_located((By.ID, 'ctl00_PageContent_GridView_grd'))
            )
            df_list = pd.read_html(self.driver.page_source, attrs={'id': 'ctl00_PageContent_GridView_grd'})
            if df_list:
                return df_list[0]
            return None
        except Exception as e:
            logging.error(f"Failed to extract data table: {e}")
            self._save_snapshot('get_data_failed')
            return None

    def get_market_size_data(self, config):
        """Scrapes data for the 'Size of the Market' section."""
        logging.info("Fetching data for 'Size of the Market'")
        data = {}
        
        self.navigate_to_main_page(config['hs_code'], config['target_market_id'], partner="")
        
        try:
            # --- MODIFIED SECTION ---
            # Add an explicit wait to ensure the dropdown menu is loaded before we interact with it.
            logging.debug("Waiting for the trade type dropdown to be present...")
            trade_type_dropdown_element = self.wait.until(
                EC.presence_of_element_located((By.ID, 'ctl00_PageContent_DDL_TradeType'))
            )
            
            # Ensure we are on the imports page
            Select(trade_type_dropdown_element).select_by_value('1')  # 1 for Imports
            logging.debug("Selected 'Imports' from the dropdown.")
            
            time.sleep(2)
            self._wait_for_ready_state(15)

        except TimeoutException:
            logging.error("The trade type dropdown (ctl00_PageContent_DDL_TradeType) was not found on the page.")
            self._save_snapshot('dropdown_not_found')
            return None
        except Exception as e:
            logging.error(f"An error occurred while selecting the trade type: {e}")
            self._save_snapshot('dropdown_selection_error')
            return None

        df = self.get_data_as_dataframe()
        if df is None or df.empty:
            logging.error("Could not retrieve market size data.")
            return None
        
        world_row = df[df.iloc[:, 0] == 'World']
        if not world_row.empty:
            data['target_market_imports_from_world_usd'] = world_row.iloc[0, 1]
            data['target_market_share_in_world_imports_pct'] = world_row.iloc[0, 2]

        country_row = df[df.iloc[:, 0] == config['your_country']]
        if not country_row.empty:
            data['target_market_imports_from_your_country_usd'] = country_row.iloc[0, 1]
            data['your_country_share_in_target_market_imports_pct'] = country_row.iloc[0, 2]
        else:
            data['target_market_imports_from_your_country_usd'] = 0
            data['your_country_share_in_target_market_imports_pct'] = 0

        return data
        
    def get_market_growth_data(self, config):
        logging.info("Fetching data for 'Growth of the Market'")
        data = {}
        df = self.get_data_as_dataframe() 
        if df is None or df.empty:
             return None

        world_row = df[df.iloc[:, 0] == 'World']
        if not world_row.empty:
            data['target_market_import_growth_5y_pct'] = world_row.iloc[0, 3]
            data['target_market_import_growth_1y_pct'] = world_row.iloc[0, 4]
        
        country_row = df[df.iloc[:, 0] == config['your_country']]
        if not country_row.empty:
            data['your_country_import_growth_5y_pct'] = country_row.iloc[0, 3]
        else:
            data['your_country_import_growth_5y_pct'] = "N/A"
            
        return data

    def get_competition_data(self, config):
        logging.info("Fetching data for 'Competition'")
        df = self.get_data_as_dataframe()
        if df is None or df.empty:
            return None
            
        competitors_df = df[df.iloc[:, 0] != 'World'].head(10)
        
        top_3_suppliers = []
        for index, row in competitors_df.head(3).iterrows():
            supplier_data = {
                "name": row.iloc[0],
                "market_share_pct": row.iloc[2]
            }
            top_3_suppliers.append(supplier_data)
        
        suppliers_gaining_share = []
        for index, row in competitors_df.iterrows():
            try:
                if float(row.iloc[3]) > float(df[df.iloc[:, 0] == 'World'].iloc[0, 3]):
                    suppliers_gaining_share.append(row.iloc[0])
            except (ValueError, IndexError):
                continue
                
        return {
            "top_3_suppliers": top_3_suppliers,
            "suppliers_gaining_share_last_5y": suppliers_gaining_share
        }

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
                logging.info('Driver closed successfully.')
        except Exception as e:
            logging.warning(f"Error closing driver: {e}")

def save_to_json(data, filename="factsheet_data.json"):
    try:
        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=4)
        logging.info(f"Successfully saved data to {filename}")
    except Exception as e:
        logging.error(f"Failed to save data to JSON file: {e}")

if __name__ == '__main__':
    # --- CONFIGURATION ---
    CONFIG = {
        "product_name": "Fresh Apples",
        "hs_code": "080810",
        "your_country": "South Africa",
        "your_country_id": "710",
        "target_market": "United Kingdom",
        "target_market_id": "826",
        "year": "2023"
    }

    factsheet_data = {
        "header": {
            "product": CONFIG["product_name"],
            "hs_code": CONFIG["hs_code"],
            "target_market": CONFIG["target_market"],
            "your_country": CONFIG["your_country"],
            "date": datetime.now().strftime("%B %Y")
        },
        "country_profile": {
            "capital_city": "manual input required",
            "population": "manual input required",
            "gdp_per_capita": "manual input required",
            "currency": "manual input required",
            "languages": "manual input required",
            "country_profile_link": "manual input required"
        },
        "market_size": {},
        "market_growth": {},
        "competition": {},
        "market_access": {
            "tariffs_and_agreements": "manual input required from macmap.org",
            "non_tariff_measures": "manual input required from macmap.org",
            "potential_ntms": "manual input required from epingalert.org"
        },
        "business_partners": "manual input required from TradeMap's company section",
        "other_promising_markets": "manual input required from exportpotential.intracen.org"
    }
    
    ac = os.environ.get('TM_USERNAME') or input('Enter TradeMap username: ')
    pw = os.environ.get('TM_PASSWORD') or input('Enter TradeMap password: ')

    s = TradeSpider(headless=False)
    
    try:
        s.set_driver()
        if s.login(ac, pw):
            logging.info("Login successful. Starting data extraction process.")
            
            market_size = s.get_market_size_data(CONFIG)
            if market_size:
                factsheet_data["market_size"] = market_size
            
            market_growth = s.get_market_growth_data(CONFIG)
            if market_growth:
                factsheet_data["market_growth"] = market_growth
                
            competition = s.get_competition_data(CONFIG)
            if competition:
                factsheet_data["competition"] = competition
            
            save_to_json(factsheet_data)

        else:
            logging.error('Login failed. Stopping execution.')

    except Exception as e:
        logging.critical(f"An unexpected error occurred: {e}")
    finally:
        input("Press Enter to exit and close the browser...")
        s.close()