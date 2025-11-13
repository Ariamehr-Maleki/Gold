import json
import logging
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any, Dict, List, Optional

from utils import get_by_path, set_by_path
import reporting

class Orchestrator:
    """
    Orchestrates scraper execution, data validation, and aggregation.
    """
    def __init__(self, config: Dict, template: Dict, outdir: str,
                 is_dry_run: bool, parallel: bool, timeout: int, logger: logging.Logger):
        self.config = config
        self.template = template
        self.outdir = outdir
        self.is_dry_run = is_dry_run
        self.parallel = parallel
        self.timeout = timeout
        self.logger = logger
        self.log_dir = os.path.join(self.outdir, 'logs')
        self.run_metadata = {}

    def run(self):
        """Main execution flow."""
        self.logger.info("Orchestration started.")
        self.logger.info(f"Dry run: {self.is_dry_run}, Parallel: {self.parallel}, Timeout: {self.timeout}s")

        run_results = []
        if not self.is_dry_run:
            run_results = self._run_scrapers()
        else:
            self.logger.info("Dry run: Skipping scraper execution.")
        
        self.run_metadata['scraper_runs'] = run_results
        
        scraper_outputs = self._load_scraper_outputs()
        final_template, mapping_report = self._map_and_merge(scraper_outputs)
        
        self._generate_reports(final_template, mapping_report)
        self.logger.info("Orchestration finished.")

    def _run_single_scraper(self, scraper_config: Dict) -> Dict:
        """Executes a single scraper script in a subprocess."""
        name = scraper_config['name']
        script_path = scraper_config['path']
        
        # --- FIX: The orchestrator now builds the full path robustly ---
        # 1. Get just the FILENAME from the config.
        #    We use 'output_file' which is a more accurate key name.
        output_filename = scraper_config.get('output_file', f"{name}_output.json")
        
        # 2. Always join it with the main output directory.
        output_path = os.path.join(self.outdir, output_filename)
        # --- END FIX ---
        
        # This line is now safe because output_path is guaranteed to have a directory.
        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        cmd_template = scraper_config.get('cmd_template', 'python {path} --output {output}')
        cmd = [part.format(path=script_path, output=output_path) for part in cmd_template.split()]
        cmd[0] = sys.executable

        self.logger.info(f"Running scraper '{name}': {' '.join(cmd)}")
        start_time = time.time()
        log_path = os.path.join(self.log_dir, f"{name}.log")
        result = {"name": name, "status": "FAIL", "duration": 0, "output_path": output_path, "log_path": log_path}

        try:
            with open(log_path, 'w', encoding='utf-8') as log_file:
                process = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
                log_file.write("--- STDOUT ---\n" + process.stdout + "\n--- STDERR ---\n" + process.stderr)

            duration = round(time.time() - start_time, 2)
            result["duration"] = duration
            
            if process.returncode == 0:
                self.logger.info(f"Scraper '{name}' finished successfully in {duration}s.")
                result["status"] = "SUCCESS"
            else:
                self.logger.error(f"Scraper '{name}' failed with exit code {process.returncode}. See log: {log_path}")
        except subprocess.TimeoutExpired:
            result["duration"] = self.timeout
            result["status"] = "TIMEOUT"
            self.logger.error(f"Scraper '{name}' timed out after {self.timeout}s. Log: {log_path}")
        except Exception as e:
            result["duration"] = round(time.time() - start_time, 2)
            self.logger.critical(f"Unexpected error running '{name}': {e}", exc_info=True)
        return result

    def _run_scrapers(self) -> List[Dict]:
        """Runs all configured scrapers, returning their execution results."""
        scrapers = self.config['scrapers']
        self.logger.info(f"Executing {len(scrapers)} scrapers...")
        start_time = time.time()
        
        results = []
        if self.parallel and len(scrapers) > 1:
            with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                futures = {executor.submit(self._run_single_scraper, sc): sc for sc in scrapers}
                for future in as_completed(futures):
                    results.append(future.result())
        else:
            for scraper_config in scrapers:
                results.append(self._run_single_scraper(scraper_config))
        
        self.logger.info(f"All scraper executions finished in {time.time() - start_time:.2f}s.")
        return results

    def _load_scraper_outputs(self) -> Dict[str, Any]:
        """Loads JSON outputs from all scrapers specified in config, handling missing files."""
        all_outputs = {}
        for scraper in self.config['scrapers']:
            name = scraper['name']

            # --- FIX: Replicate the same robust path logic here ---
            output_filename = scraper.get('output_file', f"{name}_output.json")
            path = os.path.join(self.outdir, output_filename)
            # --- END FIX ---
            
            if not os.path.exists(path):
                if self.is_dry_run:
                    self.logger.warning(f"Dry run: Output for '{name}' not found at '{path}'. Will skip.")
                else:
                    self.logger.error(f"Output file for scraper '{name}' not found at '{path}'. It may have failed.")
                continue

            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                all_outputs[name] = {"data": data, "metadata": scraper}
                self.logger.info(f"Successfully loaded output for '{name}'.")
            except json.JSONDecodeError:
                self.logger.error(f"Failed to decode JSON from output of '{name}' at '{path}'.")
        return all_outputs

    def _map_and_merge(self, scraper_outputs: Dict[str, Any]) -> (Dict, Dict):
        """Applies mappings and merges data into a deep copy of the template."""
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
                        "priority": content['metadata'].get('priority', 0),
                        "confidence": content['metadata'].get('confidence', 0.5),
                    }
                    candidates_by_field.setdefault(dest_path, []).append(candidate)

        filled_template = json.loads(json.dumps(self.template)) # Deep copy
        merge_strategy = self.config.get('defaults', {}).get('merge_strategy', 'priority')
        mapping_report = {}

        for dest_path, candidates in candidates_by_field.items():
            if not candidates: continue

            if merge_strategy == 'priority':
                chosen = sorted(candidates, key=lambda c: c['priority'], reverse=True)[0]
            else: # Fallback
                chosen = sorted(candidates, key=lambda c: c['priority'], reverse=True)[0]

            set_by_path(filled_template, dest_path, chosen['value'])
            mapping_report[dest_path] = {
                "chosen_candidate": chosen,
                "all_candidates": candidates,
                "merge_strategy_used": merge_strategy
            }
        
        filled_template.setdefault("meta", {})
        filled_template["meta"]["orchestration_timestamp_utc"] = datetime.utcnow().isoformat()
        filled_template["meta"]["run_metadata"] = self.run_metadata
        filled_template["meta"]["mapping_summary"] = {"fields_mapped": len(mapping_report), "merge_strategy": merge_strategy}

        return filled_template, mapping_report

    def _generate_reports(self, final_template: Dict, mapping_report: Dict):
        """Orchestrates the generation of all output files and reports."""
        final_output_path = os.path.join(self.outdir, 'filled_template.json')
        reporting.generate_final_output(final_template, final_output_path)
        self.logger.info(f"Successfully wrote filled template to {final_output_path}")

        report_path_json = os.path.join(self.outdir, 'mapping_report.json')
        reporting.generate_mapping_report_json(mapping_report, report_path_json)
        self.logger.info(f"Wrote mapping report to {report_path_json}")

        report_path_md = os.path.join(self.outdir, 'mapping_report.md')
        reporting.generate_mapping_report_md(mapping_report, report_path_md)
        self.logger.info(f"Wrote markdown summary report to {report_path_md}")

        checklist_path = os.path.join(self.outdir, 'checklist.md')
        reporting.generate_checklist_md(final_template, checklist_path)
        self.logger.info(f"Generated manual review checklist at {checklist_path}")