# data_downloader.py

from spider_core import TradeSpider, logging
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException
from selenium.webdriver.common.by import By
import time
import random
import os
import glob


class DataDownloader(TradeSpider):
    def navigate_to_timeseries_page(self, product_code, country_id, trade_flow='I'):
        logging.info(f"Navigating to Time Series page for product {product_code} (Flow: {trade_flow})")
        trade_flow_code = '1' if trade_flow == 'I' else '2'
        url = f"https://www.trademap.org/Country_SelProductCountry_TS.aspx?nvpm=1|{country_id}||||{product_code}|||2|1|1|{trade_flow_code}|2|1|2|1|1|1"
        if not self.goto(url): return False
        time.sleep(3)
        return True

    def navigate_to_companies_page(self, product_code, country_id, trade_flow='I'):
        logging.info(f"Navigating to Companies page for product {product_code} (Flow: {trade_flow})")
        trade_flow_code = '1' if trade_flow == 'I' else '2'
        url = f"https://www.trademap.org/CompaniesList.aspx?nvpm=1|{country_id}||||{product_code}|||4|1|1|{trade_flow_code}|3|1|1|1|1|4"
        if not self.goto(url): return False
        time.sleep(3)
        return True

    def _download_file(self, expected_keywords: list | None = None, max_attempts: int = 3, click_xpath: str = "//input[@type='image' and @title='Text file']"):
        logging.info(f"Cleaning old text files from '{self.download_dir}'...")
        for f in glob.glob(os.path.join(self.download_dir, "*.txt*")):
            try:
                os.remove(f)
            except Exception:
                pass

        attempt = 0
        while attempt < max_attempts:
            attempt += 1
            logging.info(f"Download attempt {attempt}/{max_attempts}...")
            if not self._safe_click(By.XPATH, click_xpath):
                logging.error("Failed to click download button.")
                return None

            timeout = 60
            end_time = time.time() + timeout
            downloaded_file_path = None
            while time.time() < end_time:
                text_files = glob.glob(os.path.join(self.download_dir, "*.txt"))
                if text_files:
                    latest_file = max(text_files, key=os.path.getctime)
                    time.sleep(1.0)
                    try:
                        if os.path.getsize(latest_file) > 0:
                            downloaded_file_path = latest_file
                            logging.info(f"File download confirmed: {downloaded_file_path}")
                            break
                    except Exception as e:
                        logging.debug(f"Error checking file size: {e}")
                time.sleep(0.5)

            if not downloaded_file_path:
                logging.error("Download timed out. No .txt file was found.")
                continue

            if not expected_keywords:
                return downloaded_file_path

            try:
                with open(downloaded_file_path, 'r', encoding='utf-8', errors='ignore') as fh:
                    content = fh.read(5000)
                found = False
                for kw in expected_keywords:
                    if kw and kw.lower() in content.lower():
                        found = True
                        break
                if found:
                    logging.info("Downloaded file verified contains expected keywords.")
                    return downloaded_file_path
                else:
                    logging.warning(f"Downloaded file did not contain expected keywords {expected_keywords}. Deleting and retrying.")
                    try:
                        os.remove(downloaded_file_path)
                    except Exception:
                        pass
                    time.sleep(random.uniform(1.0, 2.0))
                    continue
            except Exception as e:
                logging.error(f"Error verifying downloaded file: {e}")
                try:
                    os.remove(downloaded_file_path)
                except Exception:
                    pass
                continue

        logging.error("All download attempts failed or verification didn't pass.")
        return None