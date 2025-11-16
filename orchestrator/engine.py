# orchestrator/engine.py

import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List

# --- Local Application Imports ---
from orchestrator import reporting, doc_generator
from orchestrator.utils import get_by_path, set_by_path


class Orchestrator:
    """
    Orchestrates scraper execution, data aggregation, and report generation.
    """
    def __init__(self, config: Dict, template: Dict, outdir: str, run_params: Dict,
                 is_dry_run: bool, parallel: bool, timeout: int, logger: logging.Logger):
        self.config = config
        self.template = template
        self.outdir = outdir
        self.run_params = run_params # Now stores the structured config
        self.is_dry_run = is_dry_run
        self.parallel = parallel
        self.timeout = timeout
        self.logger = logger
        self.log_dir = os.path.join(self.outdir, 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        self.run_metadata = {}
        
        # Define the directory for scraper-specific logs
        self.log_dir = os.path.join(self.outdir, 'logs')
        
        # --- CRITICAL FIX: Ensure the log directory exists before running scrapers ---
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.run_metadata = {}

    def run(self):
        """Main execution flow of the orchestration process."""
        self.logger.info("Orchestration started.")
        self.logger.info(f"Using run parameters: {json.dumps(self.run_params, indent=2)}")
        self.logger.info(f"Dry run: {self.is_dry_run}, Parallel: {self.parallel}, Timeout: {self.timeout}s")

        run_results = []
        if self.is_dry_run:
            self.logger.info("Dry run mode: Skipping scraper execution.")
        else:
            run_results = self._run_scrapers()
        
        self.run_metadata['scraper_runs'] = run_results
        
        scraper_outputs = self._load_scraper_outputs()
        final_data, mapping_report = self._map_and_merge(scraper_outputs)
        
        self._generate_reports(final_data, mapping_report)
        self.logger.info(f"Orchestration finished. All outputs are in: {self.outdir}")

    def _run_single_scraper(self, scraper_config: Dict) -> Dict:
        """
        Executes a single scraper, merging common and specific parameters.
        """
        name = scraper_config['name']
        script_path = scraper_config['path']
        output_path = os.path.join(self.outdir, scraper_config.get('output_file', f"{name}_output.json"))
        log_path = os.path.join(self.log_dir, f"{name}.log")

        # --- NEW: Parameter Merging Logic ---
        # 1. Start with a copy of the common parameters
        final_params = self.run_params.get('common_params', {}).copy()
        # 2. Get scraper-specific parameters for the current scraper
        specific_params = self.run_params.get('scraper_specific_params', {}).get(name, {})
        # 3. Merge them - specific values will overwrite common ones if keys are the same
        final_params.update(specific_params)
        
        cmd = [sys.executable, script_path, '--output', output_path]
        
        # Add the final, merged parameters to the command
        for key, value in final_params.items():
            if value is not None:
                arg_name = f'--{key.replace("_", "-")}'
                cmd.extend([arg_name, str(value)])

        self.logger.info(f"Running scraper '{name}' with final params: {final_params}")
        self.logger.debug(f"Executing command: {' '.join(cmd)}")
        start_time = time.time()
        result = {"name": name, "status": "FAIL", "duration": 0, "output_path": output_path, "log_path": log_path}

        try:
            # Open the dedicated log file for this scraper's output
            with open(log_path, 'w', encoding='utf-8') as log_file:
                process = subprocess.run(
                    cmd, 
                    capture_output=True, 
                    text=True, 
                    timeout=self.timeout,
                    check=False  # We check the return code manually
                )
                # Write both stdout and stderr to the log file for debugging
                log_file.write("--- STDOUT ---\n" + process.stdout + "\n--- STDERR ---\n" + process.stderr)

            duration = round(time.time() - start_time, 2)
            result["duration"] = duration
            
            if process.returncode == 0:
                result["status"] = "SUCCESS"
                self.logger.info(f"Scraper '{name}' finished successfully in {duration}s.")
            else:
                self.logger.error(f"Scraper '{name}' failed with exit code {process.returncode}. See log: {log_path}")
                
        except subprocess.TimeoutExpired:
            result.update({"duration": self.timeout, "status": "TIMEOUT"})
            self.logger.error(f"Scraper '{name}' timed out after {self.timeout}s. Log: {log_path}")
        except Exception as e:
            result["duration"] = round(time.time() - start_time, 2)
            self.logger.critical(f"An unexpected error occurred while running '{name}': {e}", exc_info=True)
            
        return result
    
    def _run_scrapers(self) -> List[Dict]:
        """
        Runs all scrapers defined in the configuration, either in parallel or sequentially.
        """
        scrapers = self.config.get('scrapers', [])
        if not scrapers:
            self.logger.warning("No scrapers found in the configuration file.")
            return []
            
        self.logger.info(f"Executing {len(scrapers)} scrapers...")
        start_time = time.time()
        
        results = []
        # Use parallel execution if enabled and there's more than one scraper
        if self.parallel and len(scrapers) > 1:
            with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                future_to_scraper = {executor.submit(self._run_single_scraper, sc): sc for sc in scrapers}
                for future in as_completed(future_to_scraper):
                    results.append(future.result())
        else:
            # Run sequentially otherwise
            for scraper_config in scrapers:
                results.append(self._run_single_scraper(scraper_config))
        
        self.logger.info(f"All scraper executions finished in {time.time() - start_time:.2f}s.")
        return results

    def _load_scraper_outputs(self) -> Dict[str, Any]:
        """
        Loads the JSON output files from all successfully completed scrapers.
        """
        all_outputs = {}
        for scraper_run in self.run_metadata.get('scraper_runs', []):
            if scraper_run['status'] == 'SUCCESS':
                name = scraper_run['name']
                path = scraper_run['output_path']
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    
                    # Find the original config for this scraper to get metadata like priority
                    scraper_meta = next((s for s in self.config['scrapers'] if s['name'] == name), {})
                    all_outputs[name] = {"data": data, "metadata": scraper_meta}
                    self.logger.info(f"Successfully loaded output for '{name}'.")
                except (FileNotFoundError, json.JSONDecodeError) as e:
                    self.logger.error(f"Could not load or parse output for '{name}' from {path}: {e}")
        return all_outputs

    def _map_and_merge(self, scraper_outputs: Dict[str, Any]) -> tuple[Dict, Dict]:
        """
        Maps data from scraper outputs to the final template based on configured rules.
        """
        candidates_by_field = {}
        for scraper_name, content in scraper_outputs.items():
            mappings = self.config.get('mappings', {}).get(scraper_name, {})
            for src_path, dest_path in mappings.items():
                value = get_by_path(content['data'], src_path)
                if value is not None:
                    candidate = {
                        "scraper": scraper_name,
                        "source_path": src_path,
                        "value": value,
                        "priority": content['metadata'].get('priority', 0)
                    }
                    candidates_by_field.setdefault(dest_path, []).append(candidate)

        # Create a deep copy of the template to avoid modifying the original
        filled_template = json.loads(json.dumps(self.template))
        mapping_report = {}

        for dest_path, candidates in candidates_by_field.items():
            if not candidates:
                continue
            
            # Choose the best candidate based on priority
            chosen = sorted(candidates, key=lambda c: c['priority'], reverse=True)[0]
            set_by_path(filled_template, dest_path, chosen['value'])
            
            mapping_report[dest_path] = {
                "chosen_candidate": chosen,
                "all_candidates": candidates
            }
        
        # Add metadata about the orchestration run to the final output
        filled_template.setdefault("meta", {})["orchestration_timestamp_utc"] = datetime.utcnow().isoformat()
        filled_template["meta"]["run_metadata"] = self.run_metadata
        return filled_template, mapping_report

    def _generate_reports(self, final_data: Dict, mapping_report: Dict):
        """
        Generates all final output files, including JSON, markdown reports, and the DOCX/PDF factsheet.
        """
        # 1. Generate the main machine-readable JSON output
        final_output_path = os.path.join(self.outdir, 'final_report.json')
        reporting.generate_final_output(final_data, final_output_path)
        self.logger.info(f"Successfully wrote final JSON report to {final_output_path}")

        # 2. Generate human-readable markdown reports
        report_path_md = os.path.join(self.outdir, 'mapping_report.md')
        reporting.generate_mapping_report_md(mapping_report, report_path_md)
        self.logger.info(f"Wrote markdown mapping report to {report_path_md}")

        checklist_path = os.path.join(self.outdir, 'review_checklist.md')
        reporting.generate_checklist_md(final_data, checklist_path)
        self.logger.info(f"Generated manual review checklist at {checklist_path}")

        # 3. Generate the final Word and PDF factsheet
        self.logger.info("Starting generation of Quantitative Export Factsheet...")
        template_path = "Quantitative_Factsheet_Template.docx"
        
        if os.path.exists(template_path):
            try:
                doc_generator.generate_factsheet(
                    data_path=final_output_path,
                    template_path=template_path,
                    output_dir=self.outdir
                )
                self.logger.info("Successfully generated factsheet documents (DOCX and PDF).")
            except Exception as e:
                self.logger.error(f"Failed to generate factsheet document: {e}", exc_info=True)
        else:
            self.logger.warning(f"Factsheet template not found at '{template_path}'. Skipping document generation.")