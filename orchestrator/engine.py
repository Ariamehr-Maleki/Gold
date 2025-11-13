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

from orchestrator.utils import get_by_path, set_by_path
from orchestrator import reporting

class Orchestrator:
    """Orchestrates scraper execution, data validation, and aggregation."""
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
        os.makedirs(self.log_dir, exist_ok=True)
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
        self.logger.info(f"Orchestration finished. Outputs are in: {self.outdir}")

    def _run_single_scraper(self, scraper_config: Dict) -> Dict:
        """Executes a single scraper script in a subprocess."""
        name = scraper_config['name']
        script_path = scraper_config['path']
        output_filename = scraper_config.get('output_file', f"{name}_output.json")
        output_path = os.path.join(self.outdir, output_filename)

        cmd = [sys.executable, script_path, '--output', output_path]
        if self.config.get('run_headless', True):
            cmd.append('--headless')

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
        """Loads JSON outputs from all successfully run scrapers."""
        all_outputs = {}
        for scraper_run in self.run_metadata.get('scraper_runs', []):
            if scraper_run['status'] == 'SUCCESS':
                name = scraper_run['name']
                path = scraper_run['output_path']
                try:
                    with open(path, 'r', encoding='utf--8') as f:
                        data = json.load(f)
                    
                    scraper_meta = next((s for s in self.config['scrapers'] if s['name'] == name), {})
                    all_outputs[name] = {"data": data, "metadata": scraper_meta}
                    self.logger.info(f"Successfully loaded output for '{name}'.")
                except (FileNotFoundError, json.JSONDecodeError) as e:
                    self.logger.error(f"Could not load or parse output for '{name}' from {path}: {e}")
        return all_outputs

    def _map_and_merge(self, scraper_outputs: Dict[str, Any]) -> tuple[Dict, Dict]:
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
                        "priority": content['metadata'].get('priority', 0)
                    }
                    candidates_by_field.setdefault(dest_path, []).append(candidate)

        filled_template = json.loads(json.dumps(self.template)) # Deep copy
        mapping_report = {}

        for dest_path, candidates in candidates_by_field.items():
            if not candidates: continue
            
            chosen = sorted(candidates, key=lambda c: c['priority'], reverse=True)[0]
            set_by_path(filled_template, dest_path, chosen['value'])
            mapping_report[dest_path] = {
                "chosen_candidate": chosen,
                "all_candidates": candidates
            }
        
        filled_template.setdefault("meta", {})["orchestration_timestamp_utc"] = datetime.utcnow().isoformat()
        filled_template["meta"]["run_metadata"] = self.run_metadata
        return filled_template, mapping_report

    def _generate_reports(self, final_template: Dict, mapping_report: Dict):
        """Generates all output files and reports."""
        final_output_path = os.path.join(self.outdir, 'final_report.json')
        reporting.generate_final_output(final_template, final_output_path)
        self.logger.info(f"Successfully wrote final report to {final_output_path}")

        report_path_md = os.path.join(self.outdir, 'mapping_report.md')
        reporting.generate_mapping_report_md(mapping_report, report_path_md)
        self.logger.info(f"Wrote markdown summary report to {report_path_md}")

        checklist_path = os.path.join(self.outdir, 'review_checklist.md')
        reporting.generate_checklist_md(final_template, checklist_path)
        self.logger.info(f"Generated manual review checklist at {checklist_path}")