import yaml
import csv
import logging
import pandas as pd
import time
import os
import random
import json
from typing import Dict, Optional, List
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager
from fuzzywuzzy import fuzz
from selenium.webdriver.common.keys import Keys

with open('locators/ashby_locators.json', 'r') as file:
    locators = json.load(file)

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('ashby_automation.log'),
        logging.StreamHandler()
    ]
)

def select_profile():
    """Dynamically list YAML files in configuration/ and let user select one."""
    credentials_dir = "credentials"
    yaml_files = [
        f for f in os.listdir(credentials_dir)
        if os.path.isfile(os.path.join(credentials_dir, f)) and f.lower().endswith(('.yaml', '.yml'))
    ]

    if not yaml_files:
        logging.error("No YAML files found in credentials directory.")
        raise FileNotFoundError("No YAML files found in credentials directory.")

    yaml_files.sort()
    print("Select a profile:")
    for idx, yaml_file in enumerate(yaml_files, 1):
        print(f"{idx}. {yaml_file}")

    while True:
        try:
            choice = input(f"Enter profile number (1-{len(yaml_files)}): ").strip()
            profile_num = int(choice)
            if 1 <= profile_num <= len(yaml_files):
                selected_yaml = os.path.join(credentials_dir, yaml_files[profile_num - 1])
                logging.info(f"Selected profile: {selected_yaml}")
                return selected_yaml
            else:
                print(f"Please enter a number between 1 and {len(yaml_files)}.")
        except ValueError:
            print("Invalid input. Please enter a number.")

def generate_job_links_from_csv(file_path):
    
    data = pd.read_csv(file_path)

   
    base_url = "https://jobs.ashbyhq.com/{company}/{job_id}"

    
    job_links = []

   
    for index, row in data.iterrows():
        company = row['company']
        platform = row['platform']
        job_id = row['job_id']

      
        if isinstance(platform, str) and platform.lower() == 'ashby':
          
            job_link = base_url.format(company=company, job_id=job_id)
            job_links.append(job_link)

    return job_links

class AshbyJobApply:
    def __init__(self, job_url, yaml_file, csv_file):
        self.job_url = job_url
        self.personal_details = self.load_yaml_credentials(yaml_file)
        self.qa_data = self.load_qa_csv(csv_file)

        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        chrome_options.add_argument("--disable-notifications")
        self.driver = webdriver.Chrome(
            service=Service(ChromeDriverManager().install()),
            options=chrome_options
        )
        self.wait = WebDriverWait(self.driver, 10)

    @staticmethod
    def load_yaml_credentials(yaml_file):
        with open(yaml_file, "r") as file:
            return yaml.safe_load(file)

    @staticmethod
    def load_qa_csv(csv_file):
        return pd.read_csv(csv_file)

    def open_job_page(self):
        try:
            self.driver.get(self.job_url)
            logging.info(f"Opened job page: {self.job_url}")
            time.sleep(3)

            apply_selectors = locators["apply_selectors"]

            for selector in apply_selectors:
                try:
                    apply_button = self.wait.until(
                        EC.element_to_be_clickable((By.CSS_SELECTOR, selector)))
                    apply_button.click()
                    logging.info("Apply button clicked successfully!")
                    time.sleep(5)
                    return
                except Exception as e:
                    logging.debug(f"Selector {selector} failed: {str(e)}")
                    continue

            raise Exception("Could not find apply button with any selector")
        except Exception as e:
            logging.error(f"Error in open_job_page: {str(e)}")
            raise

    def upload_resume(self):
        try:
            resume_path = self.personal_details.get("resume_path")

            if not resume_path:
                logging.error("No resume_path specified in YAML credentials")
                return False

            if not os.path.isabs(resume_path):
                resume_path = os.path.join(os.getcwd(), resume_path)

            if not os.path.exists(resume_path):
                logging.error(f"Resume file not found at: {resume_path}")
                return False

            logging.info(f"Attempting to upload resume from: {resume_path}")

            file_input = None
            selectors = locators["file_input_selectors"]

            for selector in selectors:
                try:
                    file_input = self.wait.until(
                        EC.presence_of_element_located((By.CSS_SELECTOR, selector))
                    )
                    break
                except Exception:
                    continue

            if not file_input:
                logging.error("Could not find file input element")
                return False

            self.driver.execute_script("""
                arguments[0].style.display = 'block';
                arguments[0].style.visibility = 'visible';
                arguments[0].style.height = 'auto';
                arguments[0].style.width = 'auto';
                arguments[0].style.position = 'static';
                arguments[0].removeAttribute('hidden');
                arguments[0].removeAttribute('disabled');
            """, file_input)

            time.sleep(0.5)
            file_input.send_keys(resume_path)
            logging.info("Resume file sent to input element")

            try:
                WebDriverWait(self.driver, 15).until(
                    EC.any_of(
                        EC.presence_of_element_located((By.XPATH, "//*[contains(., 'Upload complete')]")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='file-upload-success']")),
                        EC.presence_of_element_located((By.XPATH, "//*[contains(., 'uploaded successfully')]")),
                        EC.presence_of_element_located((By.CSS_SELECTOR, "._success_1wnh2_1"))
                    )
                )
                logging.info("Resume upload confirmed by UI")
            except Exception as e:
                logging.warning(f"No explicit upload confirmation detected: {str(e)}")

            return True

        except Exception as e:
            logging.error(f"Error in resume upload: {str(e)}")
            return False

    def fill_application_form(self):
        try:
            logging.info("Filling out the application form...")

            fields = locators["form_fields"]

            for field_name, selectors in fields.items():
                value = self.personal_details.get(field_name)
                if not value:
                    logging.warning(f"No value provided for mandatory field: {field_name}")
                    continue

                for selector in selectors:
                    try:
                        element = self.wait.until(
                            EC.presence_of_element_located((By.CSS_SELECTOR, selector)))
                        element.clear()
                        element.send_keys(value)
                        logging.info(f"Filled field {field_name} with value {value}")

                        if field_name == "location":
                            try:
                                suggestions = self.wait.until(
                                    EC.presence_of_all_elements_located((By.CSS_SELECTOR, locators["location_suggestion"])))

                                desired_location = value.lower().strip()
                                location_found = False

                                for suggestion in suggestions:
                                    if suggestion.text.lower().strip() == desired_location:
                                        suggestion.click()
                                        logging.info(f"Selected location suggestion: {suggestion.text}")
                                        location_found = True
                                        break

                                if not location_found and suggestions:
                                    suggestions[0].click()
                                    logging.warning(f"Exact location match not found, selected first suggestion: {suggestions[0].text}")

                            except Exception as e:
                                logging.warning(f"Error selecting location suggestion: {str(e)}")
                                try:
                                    element.send_keys(Keys.ARROW_DOWN)
                                    element.send_keys(Keys.RETURN)
                                    logging.info("Selected location using keyboard navigation")
                                except Exception as fallback_e:
                                    logging.error(f"Failed to select location with fallback method: {str(fallback_e)}")
                        break
                    except Exception as e:
                        logging.warning(f"Error filling field {field_name} with selector {selector}: {str(e)}")
                        continue

            linkedin_value = self.personal_details.get("linkedin profile")
            if linkedin_value:
                try:
                    linkedin_label = self.wait.until(
                        EC.presence_of_element_located((By.XPATH, "//label[contains(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), 'linkedin')]"))
                    )
                    linkedin_input = linkedin_label.find_element(By.XPATH, ".//following-sibling::input")
                    linkedin_input.clear()
                    linkedin_input.send_keys(linkedin_value)
                    logging.info("Filled LinkedIn field")
                except Exception as e:
                    logging.warning(f"LinkedIn field not found or failed to fill: {str(e)}")

            self.fill_qa_section()

            logging.info("Form filled successfully!")
            time.sleep(1)

        except Exception as e:
            logging.error(f"Error filling application form: {str(e)}")
            raise

    def fill_qa_section(self):
        def safe_strip(value):
            return str(value).strip() if pd.notna(value) else ""

        try:
            logging.info("Filling out the Q&A section...")

            if self.qa_data.empty:
                logging.info("No Q&A data to fill.")
                return

            try:
                form_container = self.wait.until(
                    EC.presence_of_element_located((By.CSS_SELECTOR, "div.ashby-application-form-container"))
                )
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", form_container)
                time.sleep(0.5)
            except:
                logging.warning("Could not locate form container")

            form_questions = self.get_form_questions()
            if not form_questions:
                logging.warning("No Q&A questions found in the form. Skipping Q&A section.")
                return

            for index, row in self.qa_data.iterrows():
                question = safe_strip(row.get("Question"))
                answer = safe_strip(row.get("Answer"))

                if not question:
                    logging.warning("Empty question found in CSV, skipping.")
                    continue

                logging.info(f"Processing question: '{question}'")

                matched_question, score = self.fuzzy_match_question(question, form_questions, threshold=80)
                if not matched_question:
                    logging.warning(f"No match found for question: '{question}' (best score: {score})")
                    continue
                logging.info(f"Matched CSV question '{question}' to form question '{matched_question}' (score: {score})")

                question_container = None
                escaped_question = self.escape_xpath_text(matched_question.lower())

                try:
                    question_container = self.wait.until(
                        EC.presence_of_element_located((
                            By.XPATH,
                            f"//div[contains(@class, 'ashby-application-form-field-entry') and .//label[contains(normalize-space(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), {escaped_question})]]"
                        ))
                    )
                    self._highlight_element(question_container, "yellow")
                except Exception as e:
                    logging.debug(f"Primary XPath failed for '{matched_question}': {str(e)}")

                if not question_container:
                    for selector_template in locators["qa_selectors"]:
                        try:
                            elements = self.driver.find_elements(By.CSS_SELECTOR, selector_template)
                            for element in elements:
                                try:
                                    label = element.find_element(By.CSS_SELECTOR, "label.ashby-application-form-question-title")
                                    if fuzz.token_sort_ratio(matched_question.lower(), label.text.lower()) >= 80:
                                        question_container = element
                                        self._highlight_element(question_container, "yellow")
                                        logging.info(f"Found question '{matched_question}' using selector: {selector_template}")
                                        break
                                except:
                                    continue
                            if question_container:
                                break
                        except:
                            continue

                if not question_container:
                    logging.warning(f"Could not locate question: '{matched_question}'")
                    continue

                try:
                    container_html = question_container.get_attribute("outerHTML")[:500]
                    logging.debug(f"Question container HTML for '{matched_question}': {container_html}")

                    try:
                        answer_field = question_container.find_element(
                            By.XPATH, ".//input[not(@type='radio' or @type='checkbox')] | .//textarea")
                        answer_field.clear()
                        answer_field.send_keys(answer)
                        logging.info(f"Filled text input for '{matched_question}' with '{answer}'")
                        continue
                    except:
                        pass

                    try:
                        select = Select(question_container.find_element(By.XPATH, ".//select[not(@multiple)]"))
                        select.select_by_visible_text(answer)
                        logging.info(f"Selected dropdown option for '{matched_question}' with '{answer}'")
                        continue
                    except:
                        pass

                    try:
                        select = Select(question_container.find_element(By.XPATH, ".//select[@multiple]"))
                        select.select_by_visible_text(answer)
                        logging.info(f"Selected multi-select option for '{matched_question}' with '{answer}'")
                        continue
                    except:
                        pass

                    try:
                        radio = question_container.find_element(
                            By.XPATH, f".//input[@type='radio' and following-sibling::*[contains(normalize-space(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), '{answer.lower()}')]]")
                        self.driver.execute_script("arguments[0].click();", radio)
                        logging.info(f"Selected radio button for '{matched_question}' with '{answer}'")
                        continue
                    except:
                        pass

                    try:
                        button = question_container.find_element(
                            By.XPATH, f".//button[contains(normalize-space(translate(text(), 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz')), '{answer.lower()}')]")
                        self.driver.execute_script("arguments[0].click();", button)
                        logging.info(f"Clicked button for '{matched_question}' with '{answer}'")
                        continue
                    except:
                        pass

                    try:
                        checkbox = question_container.find_element(
                            By.XPATH, f".//input[@type='checkbox' and @name='{answer}']")
                        self.driver.execute_script("arguments[0].click();", checkbox)
                        logging.info(f"Checked checkbox for '{matched_question}' with '{answer}'")
                        continue
                    except:
                        pass

                    logging.warning(f"Could not determine answer field type for question: '{matched_question}'")

                except Exception as e:
                    logging.warning(f"Failed to answer question '{matched_question}': {str(e)}")

            logging.info("Q&A section filled successfully!")

        except Exception as e:
            logging.error(f"Error filling Q&A section: {str(e)}")
            raise

    def escape_xpath_text(self, text):
        """Escape special characters in XPath text to prevent syntax errors."""
        if "'" in text:
            parts = text.split("'")
            return "concat(" + ", '\"', ".join(f"'{part}'" for part in parts) + ")"
        return f"'{text}'"

    def get_form_questions(self):
        """Extract Q&A questions, excluding personal detail fields."""
        try:
            question_elements = self.driver.find_elements(
                By.CSS_SELECTOR, "div._fieldEntry_hkyf8_29 label._heading_101oc_53._label_hkyf8_43.ashby-application-form-question-title"
            )
            exclude_keywords = ['name', 'email', 'phone', 'location', 'linkedin', 'resume']
            questions = [
                elem.text.strip() for elem in question_elements
                if elem.text.strip() and not any(keyword in elem.text.lower() for keyword in exclude_keywords)
            ]
            logging.info(f"Form Q&A questions found: {questions}")
            return questions
        except Exception as e:
            logging.warning(f"Could not extract form questions: {str(e)}")
            return []

    def fuzzy_match_question(self, csv_question, form_questions, threshold=80):
        """Find the best matching form question with at least 80% similarity, avoiding personal fields."""
        csv_question_clean = csv_question.lower().split('?.')[0].strip()
        best_match = None
        best_score = 0
        for form_question in form_questions:
            partial_score = fuzz.partial_ratio(csv_question_clean, form_question.lower())
            token_score = fuzz.token_sort_ratio(csv_question_clean, form_question.lower())
            combined_score = (partial_score * 0.4 + token_score * 0.6)
            if (combined_score > best_score and combined_score >= threshold and
                not any(keyword in form_question.lower() for keyword in ['location', 'email', 'name', 'phone', 'linkedin', 'resume'])):
                best_score = combined_score
                best_match = form_question
        logging.debug(f"Fuzzy match for '{csv_question}': Best match='{best_match}', Score={best_score}")
        return best_match, best_score

    def _wait_for_required_fields_to_be_filled(self):
        try:
            missing_fields = []

            while True:
                missing_fields.clear()

                # Standard fields with required attribute
                required_fields = self.driver.find_elements(By.XPATH, "//*[@required]")
                for field in required_fields:
                    try:
                        field_type = field.get_attribute("type")
                        field_value = field.get_attribute("value")
                        field_name = field.get_attribute("name") or field.get_attribute("id") or "Unnamed Field"
                        logging.debug(f"Checking required field: type={field_type}, value={field_value}, name={field_name}")

                        if field_name == "_systemfield_resume":
                            continue

                        if field_type in ["radio", "checkbox"]:
                            if not field.is_selected():
                                missing_fields.append(field)
                                logging.info(f"Required radio/checkbox not selected: {field_name}")
                        elif field_value in [None, ""]:
                            missing_fields.append(field)
                            logging.info(f"Required field not filled: {field_name}")
                    except Exception as e:
                        logging.warning(f"Error checking required field: {str(e)}")
                        continue

                # Fields marked required by label class
                required_labels = self.driver.find_elements(By.XPATH, "//label[contains(@class, '_required_')]")
                for label in required_labels:
                    try:
                        for_attr = label.get_attribute("for")
                        if not for_attr:
                            continue

                        # Check for group of radio buttons
                        radio_buttons = self.driver.find_elements(By.XPATH, f"//input[@type='radio' and contains(@id, '{for_attr}')]")
                        if radio_buttons:
                            if not any(rb.is_selected() for rb in radio_buttons):
                                missing_fields.append(label)
                                logging.info(f"Required radio group not answered: {label.text.strip()}")
                            continue

                        # Check for group of checkboxes
                        checkbox_buttons = self.driver.find_elements(By.XPATH, f"//input[@type='checkbox' and contains(@id, '{for_attr}')]")
                        if checkbox_buttons:
                            if not any(cb.is_selected() for cb in checkbox_buttons):
                                missing_fields.append(label)
                                logging.info(f"Required checkbox group not answered: {label.text.strip()}")
                            continue

                    except Exception as e:
                        logging.warning(f"Error checking required group by label: {str(e)}")
                        continue

                if not missing_fields:
                    logging.info("All required fields are filled.")
                    return True

                missing_field_names = [
                    field.text.strip() if hasattr(field, 'text') and field.text.strip() else field.get_attribute("name") or field.get_attribute("id") or "Unnamed Field"
                    for field in missing_fields
                ]
                logging.info(f"Waiting for {len(missing_fields)} required fields to be filled: {missing_field_names}")
                time.sleep(2)

        except Exception as e:
            logging.error(f"Error while waiting for required fields to be filled: {str(e)}")
            return False

    def _highlight_element(self, element, color="yellow"):
        """Highlights (blinks) a Selenium WebElement."""
        driver = element._parent

        def apply_style(s):
            driver.execute_script("arguments[0].setAttribute('style', arguments[1]);",
                                  element, s)

        original_style = element.get_attribute('style')
        apply_style(f"border: 2px solid {color}; background-color: {color};")
        time.sleep(0.3)
        apply_style(original_style)

    # def _find_submit_button(self):
    #     try:
    #         button = WebDriverWait(self.driver, 10).until(
    #             EC.element_to_be_clickable((By.CSS_SELECTOR, "button._button_8wvgw_29._primary_8wvgw_96._greedy_8wvgw_218._submitButton_4fqrp_411.ashby-application-form-submit-button"))
    #         )
    #         if button.is_displayed():
    #             logging.info("Found submit button with CSS selector")
    #             self._highlight_element(button, "green")
    #             return button
    #     except Exception as e:
    #         logging.error(f"Could not locate submit button with CSS selector: {str(e)}")
    #         raise
    def _find_submit_button(self):
        submit_selectors = locators.get("submit_selectors", [])

        for selector in submit_selectors:
            try:
                button = WebDriverWait(self.driver, 3).until(
                    EC.element_to_be_clickable((By.CSS_SELECTOR, selector))
                )
                if button.is_displayed():
                    logging.info(f"Found submit button using selector: {selector}")
                    self._highlight_element(button, "green")
                    return button
            except Exception as e:
                logging.debug(f"Selector failed: {selector} - {str(e)}")

        logging.error("Could not locate submit button using any known selectors")
        return None


    def _click_submit_button(self, button, max_attempts=3):
        for attempt in range(max_attempts):
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block: 'center'});", button)
                time.sleep(0.5 + random.random())

                if attempt == 0:
                    button.click()
                    logging.info("Clicked submit button normally")
                elif attempt == 1:
                    self.driver.execute_script("arguments[0].click();", button)
                    logging.info("Used JavaScript click")
                else:
                    self.driver.execute_script("""
                        arguments[0].style.display = 'block';
                        arguments[0].style.visibility = 'visible';
                        arguments[0].style.opacity = 1;
                        arguments[0].click();
                    """, button)
                    logging.info("Used forced visibility click")

                time.sleep(2 + random.random())

                try:
                    button.is_displayed()
                    logging.debug(f"Still on same page after click attempt {attempt + 1}")
                except:
                    logging.info("Page changed after click - assuming submission started")
                    return True

            except Exception as e:
                logging.warning(f"Submit click attempt {attempt + 1} failed: {str(e)}")
                time.sleep(1 + random.random())

        return False

    def _verify_submission(self, timeout=20):
        confirmation_indicators = locators["confirmation_indicators"]
        try:
            WebDriverWait(self.driver, timeout).until(
                EC.any_of(*[getattr(EC, ind["method"])((ind["by"], ind["value"])) for ind in confirmation_indicators])
            )
            logging.info("Clear submission confirmation detected")
            return True
        except Exception as e:
            logging.warning(f"Error during submission verification: {str(e)}")
            current_url = self.driver.current_url.lower()
            if not ("apply" in current_url or "form" in current_url):
                logging.info("URL suggests we left application page - assuming success")
                return True
            return False

    def submit_application(self):
        try:
            logging.info("Starting submission process...")

            if not self._wait_for_required_fields_to_be_filled():
                logging.error("Required fields not filled before submission")
                self.log_application_status("Required Fields Not Filled")
                return False

            submit_button = self._find_submit_button()
            if not submit_button:
                logging.error("Could not locate submit button")
                self.log_application_status("Submit Button Not Found")
                return False

            if not self._click_submit_button(submit_button):
                logging.error("Failed to click submit button")
                self.log_application_status("Submit Click Failed")
                return False

            submission_verified = self._verify_submission()

            if submission_verified:
                logging.info("Application submitted successfully!")
                self.log_application_status("Success")
                return True
            else:
                logging.warning("Submission confirmation not clearly detected")
                self.log_application_status("Possible Success")
                return True

        except Exception as e:
            logging.error(f"Unexpected error during submission: {str(e)}")
            self.log_application_status("Submission Error")
            return False


        
    

    def log_application_status(self, status):
        # Get the current date to create a day-wise log file
        current_date = datetime.now().strftime("%Y-%m-%d")
        log_filename = f"log/application_log_{current_date}.csv"

        # Ensure the log directory exists
        os.makedirs("log", exist_ok=True)
        logging.info(f"Log directory ensured: {os.path.abspath('log')}")

        # Get the current timestamp
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

        # Get the candidate name from personal_details
        candidate_name = self.personal_details.get("name", "Unknown")

        # Log entry format: [timestamp], candidate_name, status, job_url
        log_entry = f"[{timestamp}], {candidate_name}, {status}, {self.job_url}\n"

        # Append the log entry to the day-wise log file
        try:
            with open(log_filename, mode="a", newline="", encoding='utf-8') as file:
                file.write(log_entry)
            logging.info(f"Log entry written to {log_filename}")
        except Exception as e:
            logging.error(f"Failed to write log entry: {str(e)}")

    def close_browser(self):
        try:
            self.driver.quit()
        except Exception as e:
            logging.warning(f"Error closing browser: {str(e)}")

if __name__ == "__main__":
    # Generate job links from the CSV file
    job_links = generate_job_links_from_csv('jobs/linkedin_jobs.csv')

    yaml_file = select_profile()
    csv_file = "config/answers.csv"

    try:
        for job_url in job_links:
            if not isinstance(job_url, str):
                continue

            logging.info(f"\n=== Starting application for: {job_url} ===\n")
            bot = AshbyJobApply(job_url, yaml_file, csv_file)

            try:
                bot.open_job_page()
                bot.upload_resume()
                bot.fill_application_form()
                bot.submit_application()
            except Exception as e:
                logging.error(f"Error during application process for {job_url}: {str(e)}")
                bot.log_application_status("Error")
            finally:
                bot.close_browser()
                time.sleep(5)

    except Exception as e:
        logging.error(f"Fatal error: {str(e)}")



