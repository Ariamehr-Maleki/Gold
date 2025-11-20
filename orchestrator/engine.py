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
        self.run_params = run_params 
        self.is_dry_run = is_dry_run
        self.parallel = parallel
        self.timeout = timeout
        self.logger = logger
        self.log_dir = os.path.join(self.outdir, 'logs')
        os.makedirs(self.log_dir, exist_ok=True)
        
        self.run_metadata = {}

    # ... [run, _run_single_scraper, _run_scrapers, _load_scraper_outputs methods remain unchanged] ...
    # ... Copy them from your existing file if needed, or just paste this class over ...

    def run(self):
        """Main execution flow."""
        self.logger.info("Orchestration started.")
        
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
        # ... (Keep existing implementation) ...
        # (For brevity, assuming you keep the existing code for running scrapers)
        name = scraper_config['name']
        script_path = scraper_config['path']
        output_path = os.path.join(self.outdir, scraper_config.get('output_file', f"{name}_output.json"))
        log_path = os.path.join(self.log_dir, f"{name}.log")

        final_params = self.run_params.get('common_params', {}).copy()
        specific_params = self.run_params.get('scraper_specific_params', {}).get(name, {})
        final_params.update(specific_params)
        
        cmd = [sys.executable, script_path, '--output', output_path]
        for key, value in final_params.items():
            if value is not None:
                arg_name = f'--{key.replace("_", "-")}'
                cmd.extend([arg_name, str(value)])

        self.logger.info(f"Running scraper '{name}'...")
        start_time = time.time()
        result = {"name": name, "status": "FAIL", "duration": 0, "output_path": output_path}

        try:
            with open(log_path, 'w', encoding='utf-8') as log_file:
                process = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
                log_file.write("--- STDOUT ---\n" + process.stdout + "\n--- STDERR ---\n" + process.stderr)

            duration = round(time.time() - start_time, 2)
            result["duration"] = duration
            
            if process.returncode == 0:
                result["status"] = "SUCCESS"
            else:
                self.logger.error(f"Scraper '{name}' failed. See log: {log_path}")
        except subprocess.TimeoutExpired:
            result.update({"duration": self.timeout, "status": "TIMEOUT"})
            self.logger.error(f"Scraper '{name}' timed out.")
        except Exception as e:
            self.logger.critical(f"Error running '{name}': {e}")
            
        return result

    def _run_scrapers(self) -> List[Dict]:
        # ... (Keep existing implementation) ...
        scrapers = self.config.get('scrapers', [])
        results = []
        if self.parallel and len(scrapers) > 1:
            with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                future_to_scraper = {executor.submit(self._run_single_scraper, sc): sc for sc in scrapers}
                for future in as_completed(future_to_scraper):
                    results.append(future.result())
        else:
            for scraper_config in scrapers:
                results.append(self._run_single_scraper(scraper_config))
        return results

    def _load_scraper_outputs(self) -> Dict[str, Any]:
        # ... (Keep existing implementation) ...
        all_outputs = {}
        for scraper_run in self.run_metadata.get('scraper_runs', []):
            if scraper_run['status'] == 'SUCCESS':
                name = scraper_run['name']
                path = scraper_run['output_path']
                try:
                    with open(path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                    scraper_meta = next((s for s in self.config['scrapers'] if s['name'] == name), {})
                    all_outputs[name] = {"data": data, "metadata": scraper_meta}
                except Exception as e:
                    self.logger.error(f"Failed to load output for {name}: {e}")
        return all_outputs

    def _prune_data_structure(self, data: Any, limit: int = 10) -> Any:
        """
        Recursively traverses the data structure. 
        If it finds a list, it keeps only the first 'limit' items.
        """
        if isinstance(data, dict):
            return {k: self._prune_data_structure(v, limit) for k, v in data.items()}
        elif isinstance(data, list):
            # Truncate list to the limit
            pruned_list = data[:limit]
            return [self._prune_data_structure(item, limit) for item in pruned_list]
        else:
            return data

    def _map_and_merge(self, scraper_outputs: Dict[str, Any]) -> tuple[Dict, Dict]:
        """
        Maps data, merges into template, AND PRUNES LARGE LISTS.
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

        filled_template = json.loads(json.dumps(self.template))
        mapping_report = {}

        for dest_path, candidates in candidates_by_field.items():
            if not candidates:
                continue
            
            chosen = sorted(candidates, key=lambda c: c['priority'], reverse=True)[0]
            set_by_path(filled_template, dest_path, chosen['value'])
            
            mapping_report[dest_path] = {
                "chosen_candidate": chosen,
                "all_candidates": candidates
            }
        
        filled_template.setdefault("meta", {})["orchestration_timestamp_utc"] = datetime.utcnow().isoformat()
        filled_template["meta"]["run_metadata"] = self.run_metadata
        
        # --- NEW: Apply pruning to reduce file size ---
        self.logger.info(f"Pruning data: Limiting all lists to a maximum of 10 items.")
        pruned_template = self._prune_data_structure(filled_template, limit=10)
        
        return pruned_template, mapping_report

    def _generate_reports(self, final_data: Dict, mapping_report: Dict):
        """Generates output files."""
        # 1. JSON
        final_output_path = os.path.join(self.outdir, 'final_report.json')
        reporting.generate_final_output(final_data, final_output_path)
        
        # 2. Markdown Reports
        report_path_md = os.path.join(self.outdir, 'mapping_report.md')
        reporting.generate_mapping_report_md(mapping_report, report_path_md)
        
        checklist_path = os.path.join(self.outdir, 'review_checklist.md')
        reporting.generate_checklist_md(final_data, checklist_path)

        # 3. Word Document
        self.logger.info("Starting generation of Quantitative Export Factsheet...")
        template_path = "Quantitative_Factsheet_Template.docx"
        
        if os.path.exists(template_path):
            try:
                doc_generator.run(
                    json_path=final_output_path,
                    template_path=template_path,
                    output_dir=self.outdir
                )
                self.logger.info("Successfully generated factsheet documents.")
            except Exception as e:
                self.logger.error(f"Failed to generate factsheet document: {e}", exc_info=True)
        else:
            self.logger.warning(f"Factsheet template not found at '{template_path}'.")