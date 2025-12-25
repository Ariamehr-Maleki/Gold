from selenium import webdriver
from selenium.webdriver.firefox.options import Options
from selenium.webdriver.firefox.service import Service
from selenium.webdriver.support.wait import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import (
    TimeoutException,
    WebDriverException,
    NoSuchElementException,
    ElementNotInteractableException
)
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time
import random
import logging
import os
from datetime import datetime
from io import BytesIO
from collections import Counter  # <--- NEW IMPORT FOR VOTING

# --- IMPORTS FOR IMAGE PROCESSING ---
from PIL import Image, ImageFilter, ImageEnhance, ImageOps
import ddddocr 

import PIL.Image

# --- MONKEY PATCH FOR DDDDOCR COMPATIBILITY ---
if not hasattr(PIL.Image, 'ANTIALIAS'):
    PIL.Image.ANTIALIAS = PIL.Image.LANCZOS
# ----------------------------------------------

try:
    import pytesseract
    # POINT THIS TO YOUR INSTALLATION PATH
    pytesseract.pytesseract.tesseract_cmd = r'C:\Program Files\Tesseract-OCR\tesseract.exe'
except ImportError:
    pytesseract = None
    print("WARNING: 'pytesseract' python package not installed.")

try:
    from setlog import setlog
except ImportError:
    def setlog():
        logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
        return logging.getLogger(__name__)

logging = setlog()


class TradeSpider(object):
    DEFAULT_WAIT = 20

    def __init__(self, headless=False, driver_path='./geckodriver.exe', wait_seconds=None):
        logging.info("TradeSpider: initializing")
        self.driver = None
        self.wait = None
        self.headless = headless
        self.driver_path = driver_path
        self.wait_seconds = wait_seconds or self.DEFAULT_WAIT
        self.download_dir = os.path.join(os.getcwd(), "downloads")
        self.archive_dir = os.path.join(os.getcwd(), "archived_downloads")

    def set_driver(self):
        logging.info("Starting Firefox WebDriver")
        options = Options()
        try:
            firefox_path = r"C:\Program Files\Mozilla Firefox\firefox.exe"
            options.binary_location = firefox_path
        except Exception:
            logging.error("Could not set Firefox binary location. Check the path.")

        if self.headless:
            options.add_argument("--headless")

        os.makedirs(self.download_dir, exist_ok=True)
        os.makedirs(self.archive_dir, exist_ok=True)

        options.set_preference("browser.download.folderList", 2)
        options.set_preference("browser.download.dir", self.download_dir)
        options.set_preference("browser.download.useDownloadDir", True)
        options.set_preference("browser.helperApps.neverAsk.saveToDisk", "text/plain, application/vnd.ms-excel, application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
        options.set_preference("general.useragent.override", "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:121.0) Gecko/20100101 Firefox/121.0")

        service = Service(executable_path=self.driver_path)

        try:
            self.driver = webdriver.Firefox(service=service, options=options)
            self.wait = WebDriverWait(self.driver, self.wait_seconds)
            return True
        except WebDriverException as e:
            logging.error(f"WebDriver failed to start. Check geckodriver/Firefox compatibility.")
            logging.error(f"Original error: {e}")
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

    def _wait_for_ready_state(self, timeout=20):
        try:
            WebDriverWait(self.driver, timeout).until(lambda d: d.execute_script('return document.readyState') == 'complete')
            return True
        except TimeoutException:
            return False

    def _safe_click(self, by, locator, attempts=3, sleep_between=0.5):
        last_exception = None
        for attempt in range(attempts):
            try:
                el = self.wait.until(EC.element_to_be_clickable((by, locator)))
                self.driver.execute_script("arguments[0].scrollIntoView(true);", el)
                time.sleep(0.5)
                el.click()
                return True
            except Exception as e:
                last_exception = e
            time.sleep(sleep_between)
        logging.error(f"_safe_click failed for {by}={locator} after {attempts} attempts. Last exception: {last_exception}")
        return False

    def _generate_image_variants(self, original_image):
        """
        Generates a list of processed images with different settings (Thresholds, Inversion, Filters).
        """
        variants = []
        
        # Convert to Grayscale
        base_gray = original_image.convert('L')
        
        # Upscale 3x (Crucial for Tesseract)
        width, height = base_gray.size
        base_large = base_gray.resize((width * 3, height * 3), Image.Resampling.LANCZOS)
        
        # Strategy 1: Standard Thresholds (120 - 160)
        # We try different "darkness" levels. If the text is faint, low threshold helps. If noisy, high helps.
        thresholds = [125, 140, 155]
        
        for thresh in thresholds:
            # Variant A: Standard
            img = base_large.point(lambda x: 0 if x < thresh else 255, '1')
            variants.append(img)
            
            # Variant B: Median Filter (Removes dots) + Sharpen
            img_med = base_large.filter(ImageFilter.MedianFilter(size=3))
            img_med = img_med.filter(ImageFilter.SHARPEN)
            img_med = img_med.point(lambda x: 0 if x < thresh else 255, '1')
            variants.append(img_med)

        # Strategy 2: Inverted Colors (White text on black background)
        # Often works better for thin lines/strikethroughs
        base_inverted = ImageOps.invert(base_large)
        
        for thresh in [110, 135]:
            # Variant C: Inverted Standard
            img = base_inverted.point(lambda x: 0 if x < thresh else 255, '1')
            variants.append(img)
            
            # Variant D: Inverted Morphological (Erosion to eat lines)
            # Since it's inverted (white text), we use MinFilter to erode white pixels (noise)
            img_erode = base_inverted.filter(ImageFilter.MinFilter(3))
            img_erode = img_erode.point(lambda x: 0 if x < thresh else 255, '1')
            variants.append(img_erode)

        return variants

    def _solve_captcha(self):
        """Attempts to read the CAPTCHA using ddddocr."""
        # Ensure ddddocr is imported at the top of your file, 
        # or import it inside the method if you prefer lazy loading.
        try:
            import ddddocr
        except ImportError:
            logging.error("ddddocr not installed. Run: pip install ddddocr")
            return False

        logging.info("Attempting to solve CAPTCHA with ddddocr...")
        try:
            # 1. Find the CAPTCHA image element
            # TradeMap uses a class 'div_captchaImg' or similar structure
            img_element = self.wait.until(EC.presence_of_element_located(
                (By.XPATH, "//div[@class='div_captchaImg']/img | //img[contains(@src, 'Captcha')]")
            ))
            
            # 2. Get the image as raw bytes directly from the browser
            img_bytes = img_element.screenshot_as_png

            # 3. Initialize ddddocr (FIXED: removed show_ad=False)
            ocr = ddddocr.DdddOcr()
            
            # 4. Solve
            res = ocr.classification(img_bytes)
            
            # 5. Clean the result (TradeMap is alphanumeric, usually 5 chars)
            final_answer = ''.join(e for e in res if e.isalnum())
            logging.info(f"ddddocr Result: '{final_answer}'")

            if not final_answer:
                logging.warning("ddddocr returned empty string.")
                return False

            # 6. Input Text
            input_box = self.driver.find_element(By.ID, "ctl00_PageContent_CaptchaAnswer")
            input_box.clear()
            input_box.send_keys(final_answer)
            
            # Short pause to mimic human speed
            time.sleep(1)

            # 7. Submit
            # Try clicking via JS first as it's often more reliable
            try:
                submit_btn = self.driver.find_element(By.ID, "ctl00_PageContent_ButtonvalidateCaptcha")
                self.driver.execute_script("arguments[0].click();", submit_btn)
            except Exception:
                # Fallback to Enter key
                input_box.send_keys(Keys.RETURN)
            
            return True

        except Exception as e:
            logging.error(f"ddddocr solving process failed: {e}")
            return False

    def goto(self, url):
        max_attempts = 4
        # Get the base filename (e.g., Product_SelProductCountry)
        base_filename = url.split('?')[0].split('/')[-1].replace('.aspx', '')
        
        for attempt in range(1, max_attempts + 1):
            logging.info(f"Navigating to {url} (Attempt {attempt}/{max_attempts})")
            try:
                self.driver.get(url)
                
                # RELAXED CHECK: Check if current URL contains the base name 
                # OR the "Rev" version of that name
                WebDriverWait(self.driver, 15).until(
                    lambda d: base_filename in d.current_url or base_filename.replace('_', 'Rev_') in d.current_url
                )
                
                self._wait_for_ready_state(10)
                # Handle any immediate survey popups
                self._handle_trademap_popup() 
                
                logging.info(f"Successfully loaded and verified page on attempt {attempt}.")
                return True
            except TimeoutException:
                logging.warning(
                    f"Navigation timed out. Target: {base_filename}, Actual: {self.driver.current_url}"
                )
            except Exception as e:
                logging.error(f"Error during navigation: {e}")
        
        return False
    
    def _handle_trademap_popup(self, timeout=30):
        """
        Targeted handler for the ITC survey popup. 
        Specifically clicks id='ctl00_MenuControl_button1'.
        """
        logging.info("Checking for TradeMap survey popup...")
        container_id = "ctl00_MenuControl_Div_PopupNews"
        button_id = "ctl00_MenuControl_button1"

        try:
            # 1. Wait for the container to exist
            wait = WebDriverWait(self.driver, timeout)
            
            # Check if container is in DOM
            containers = self.driver.find_elements(By.ID, container_id)
            if not containers or not containers[0].is_displayed():
                logging.debug("Popup container not visible. Skipping.")
                return False

            logging.info("Popup detected. Targeting 'Close' button...")

            # 2. Wait for the specific Close button to be clickable
            close_btn = wait.until(EC.element_to_be_clickable((By.ID, button_id)))

            # 3. Click the button
            # We use JavaScript click here because ITC's popups often have 
            # invisible overlays that block standard Selenium clicks.
            self.driver.execute_script("arguments[0].click();", close_btn)
            logging.info("Clicked 'Close' button via JS.")

            # 4. Wait for the popup container to disappear entirely
            # This is the most important step to prevent "Element Intercepted" errors later
            wait.until(EC.invisibility_of_element_located((By.ID, container_id)))
            
            # Brief pause to allow the site's backdrop (dimmed background) to fade out
            time.sleep(2)
            logging.info("Popup successfully cleared.")
            return True

        except TimeoutException:
            logging.info("No popup appeared or it took too long. Proceeding anyway.")
        except Exception as e:
            logging.warning(f"Note: Popup handler encountered an issue: {e}")
        
        return False
    
    def login(self, ac, pw):
        url = "https://www.trademap.org/Country_SelProduct.aspx"
        if not self.goto(url): return False
        
        self._handle_trademap_popup()

        time.sleep(random.uniform(2.0, 4.0))
        if not self._safe_click(By.ID, 'ctl00_MenuControl_marmenu_login'): return False
        
        time.sleep(random.uniform(2, 4))
        try:
            self.wait.until(EC.presence_of_element_located((By.ID, 'Username')))
            self.driver.find_element(By.ID, 'Username').send_keys(ac)
            self.driver.find_element(By.ID, 'Password').send_keys(pw)
            self._safe_click(By.XPATH, "//button[@name='button' and @value='login']")
        except Exception as e:
            logging.error(f"Error during login input: {e}")
            self._save_snapshot("login_input_fail")
            return False
            
        try:
            logging.info("Login submitted. Waiting for detection of next state...")

            captcha_indicator = (By.ID, "ctl00_PageContent_CaptchaAnswer") 
            success_indicator = (By.ID, "ctl00_MenuControl_Label_Login")   
            error_indicator = (By.ID, "ValidationSummary1")                

            WebDriverWait(self.driver, 20).until(EC.any_of(
                EC.presence_of_element_located(captcha_indicator), 
                EC.url_contains("stCaptcha.aspx"),                 
                EC.presence_of_element_located(success_indicator), 
                EC.presence_of_element_located(error_indicator)    
            ))
            
            time.sleep(1.5) 

            # --- OUTCOME ANALYSIS ---
            
            is_captcha_url = "stCaptcha.aspx" in self.driver.current_url
            has_captcha_input = len(self.driver.find_elements(*captcha_indicator)) > 0

            if is_captcha_url or has_captcha_input:
                logging.warning("CAPTCHA detected. Engaging Ensemble Auto-Solver...")
                
                solved = False
                for i in range(3):
                    # Try to solve
                    if not self._solve_captcha():
                        logging.warning(f"Solver internal error on attempt {i+1}")
                    
                    logging.info("Waiting for page response (6s)...")
                    time.sleep(6) 
                    
                    if "stCaptcha.aspx" not in self.driver.current_url:
                        if len(self.driver.find_elements(*success_indicator)) > 0:
                            logging.info("CAPTCHA page bypassed successfully!")
                            solved = True
                            break
                        else:
                            logging.info("URL changed. Checking destination...")
                    
                    logging.warning(f"Captcha attempt {i+1} did not result in success. Retrying if attempts remain...")

                if not solved:
                    logging.error("Failed to solve CAPTCHA after 3 attempts.")
                    self._save_snapshot("captcha_bypass_fail")
                    return False

            if len(self.driver.find_elements(*error_indicator)) > 0:
                 error_el = self.driver.find_element(*error_indicator)
                 if error_el.is_displayed():
                    logging.error(f"LOGIN FAILED: {error_el.text}")
                    return False

            logging.info("Verifying destination page...")
            
            self.wait.until(EC.any_of(
                EC.presence_of_element_located((By.ID, "ctl00_PageContent_MyGridView1")),
                EC.presence_of_element_located((By.ID, "ctl00_MenuControl_Label_Login")),
                EC.presence_of_element_located((By.ID, "ctl00_NavigationControl_DropDownList_Product"))
            ))

            self._wait_for_ready_state(5)
            logging.info("Login process complete and destination page is verified.")
            return True

        except TimeoutException:
            logging.error("Verification failed. Timed out waiting for expected elements.")
            logging.error(f"Final URL: {self.driver.current_url}")
            self._save_snapshot("post_login_timeout")
            return False
        except Exception as e:
            logging.error(f"Unexpected error during login: {e}")
            self._save_snapshot("post_login_error")
            return False