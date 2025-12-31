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
                 country_map: Dict, is_dry_run: bool, parallel: bool, timeout: int, logger: logging.Logger):
        self.config = config
        self.template = template
        self.outdir = outdir
        self.run_params = run_params 
        self.country_map = country_map  # To look up competitor IDs
        self.is_dry_run = is_dry_run
        self.parallel = parallel
        self.timeout = timeout
        self.logger = logger
        
        # --- NEW: Create specific folders ---
        self.log_dir = os.path.join(self.outdir, 'logs')
        self.scraper_output_dir = os.path.join(self.outdir, 'scraper_results') # <-- Specific folder for JSONs
        
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.scraper_output_dir, exist_ok=True)
        
        self.run_metadata = {}

    def run(self):
        """Main execution flow."""
        self.logger.info("Orchestration started.")
        
        run_results = []
        if self.is_dry_run:
            self.logger.info("Dry run mode: Skipping scraper execution.")
        else:
            # Modified to handle dependencies (TradeMap -> MacMap)
            run_results = self._run_scrapers_with_dependencies()
        
        self.run_metadata['scraper_runs'] = run_results
        
        scraper_outputs = self._load_scraper_outputs()
        final_data, mapping_report = self._map_and_merge(scraper_outputs)
        
        self._generate_reports(final_data, mapping_report)
        self.logger.info(f"Orchestration finished. All outputs are in: {self.outdir}")

    def _run_scrapers_with_dependencies(self) -> List[Dict]:
        """
        Runs scrapers in phases.
        Phase 1: TradeMap (to get competitor data) and other independent scrapers.
        Phase 2: MacMap (using competitor IDs from TradeMap) and others.
        """
        all_scrapers = self.config.get('scrapers', [])
        results = []

        # Identify specific scrapers
        trademap_conf = next((s for s in all_scrapers if s['name'] == 'trademap'), None)
        macmap_conf = next((s for s in all_scrapers if s['name'] == 'macmap'), None)
        
        # List of independent scrapers (excluding MacMap for now)
        independent_scrapers = [s for s in all_scrapers if s['name'] != 'macmap']
        
        # --- PHASE 1: Run Independent Scrapers (including TradeMap) ---
        self.logger.info("--- Phase 1: Running Independent Scrapers ---")
        
        phase1_results = []
        if self.parallel and len(independent_scrapers) > 1:
            with ThreadPoolExecutor(max_workers=os.cpu_count()) as executor:
                future_to_scraper = {executor.submit(self._run_single_scraper, sc): sc for sc in independent_scrapers}
                for future in as_completed(future_to_scraper):
                    phase1_results.append(future.result())
        else:
            for scraper_config in independent_scrapers:
                phase1_results.append(self._run_single_scraper(scraper_config))
        
        results.extend(phase1_results)

        # --- MIDDLEWARE: Extract Competitors from TradeMap for MacMap ---
        if macmap_conf:
            # Check if TradeMap ran successfully
            tm_result = next((r for r in phase1_results if r['name'] == 'trademap' and r['status'] == 'SUCCESS'), None)
            
            competitor_ids = []
            if tm_result:
                self.logger.info("Analyzing TradeMap results to find top competitors...")
                competitor_ids = self._extract_competitors_from_trademap_output(tm_result['output_path'])
            else:
                self.logger.warning("TradeMap failed or didn't run. Cannot dynamically set MacMap competitors.")

            if competitor_ids:
                # Inject into run_params for MacMap
                # Note: The scraper expects "--competitor-ids id1 id2 ..."
                self.logger.info(f"Injecting Competitor IDs into MacMap: {competitor_ids}")
                
                # Ensure structure exists
                if 'scraper_specific_params' not in self.run_params:
                    self.run_params['scraper_specific_params'] = {}
                if 'macmap' not in self.run_params['scraper_specific_params']:
                    self.run_params['scraper_specific_params']['macmap'] = {}

                # Create a space-separated string for the command line argument (or list depending on how _run_single handles it)
                # _run_single_scraper handles list values by converting to string, but argparse nargs='+' expects multiple args.
                # To keep it simple for the generic runner, we pass them as a list.
                self.run_params['scraper_specific_params']['macmap']['competitor_ids'] = " ".join(competitor_ids)

            # --- PHASE 2: Run MacMap ---
            self.logger.info("--- Phase 2: Running Dependent Scrapers (MacMap) ---")
            macmap_result = self._run_single_scraper(macmap_conf)
            results.append(macmap_result)

        return results

    def _extract_competitors_from_trademap_output(self, json_path: str) -> List[str]:
        """
        Reads TradeMap JSON, finds top 2 suppliers (excluding Your Country),
        converts names to IDs using self.country_map.
        """
        found_ids = []
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Access the Suppliers snapshot
            # Structure: data -> snapshots -> target_market_suppliers -> data -> list of dicts
            suppliers_snapshot = data.get("snapshots", {}).get("target_market_suppliers", {})
            rows = suppliers_snapshot.get("data", [])
            
            if not rows:
                self.logger.warning("No supplier data found in TradeMap output.")
                return []

            # Get parameters to filter out self/world
            yc_name = self.run_params.get("common_params", {}).get("your_country_name", "").lower()
            
            valid_competitors = []
            for row in rows:
                p_name = row.get("partner_country", "").strip()
                p_name_lower = p_name.lower()
                
                # Filter exclusions
                if p_name_lower in ["world", "total", "nan", ""]: 
                    continue
                if yc_name and yc_name in p_name_lower:
                    continue
                
                # Ensure we have value to sort by
                val = row.get("value_imported_usd") or 0
                valid_competitors.append({"name": p_name, "value": val})

            # Sort by value descending and take top 2
            top_2 = sorted(valid_competitors, key=lambda x: x['value'], reverse=True)[:2]
            
            for comp in top_2:
                c_name = comp['name']
                # Lookup ID (Uppercase for map key)
                c_id = self.country_map.get(c_name.upper())
                
                if c_id:
                    self.logger.info(f"Found Competitor: {c_name} -> ID: {c_id}")
                    found_ids.append(c_id)
                else:
                    self.logger.warning(f"Could not find ID for competitor '{c_name}' in country_map.")

        except Exception as e:
            self.logger.error(f"Error extracting competitors: {e}")
        
        return found_ids

    def _run_single_scraper(self, scraper_config: Dict) -> Dict:
        name = scraper_config['name']
        script_path = scraper_config['path']
        
        # --- MODIFIED: Save to specific subdirectory ---
        output_filename = scraper_config.get('output_file', f"{name}_output.json")
        output_path = os.path.join(self.scraper_output_dir, output_filename)
        
        log_path = os.path.join(self.log_dir, f"{name}.log")

        final_params = self.run_params.get('common_params', {}).copy()
        specific_params = self.run_params.get('scraper_specific_params', {}).get(name, {})
        final_params.update(specific_params)
        
        cmd = [sys.executable, script_path, '--output', output_path]
        for key, value in final_params.items():
            if value is not None:
                arg_name = f'--{key.replace("_", "-")}'
                
                # Special handling for MacMap competitor-ids which is a list in argparse
                # If we passed it as a space-separated string in Phase 1 logic above, 
                # we need to split it so subprocess sees separate arguments.
                if key == "competitor_ids" and isinstance(value, str):
                    cmd.append(arg_name)
                    cmd.extend(value.split()) # Splits "156 840" into ["156", "840"]
                else:
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
                self.logger.info(f"Scraper '{name}' finished successfully.")
            else:
                self.logger.error(f"Scraper '{name}' failed (Exit Code {process.returncode}). See log: {log_path}")
        except subprocess.TimeoutExpired:
            result.update({"duration": self.timeout, "status": "TIMEOUT"})
            self.logger.error(f"Scraper '{name}' timed out.")
        except Exception as e:
            self.logger.critical(f"Error running '{name}': {e}")
            
        return result

    def _load_scraper_outputs(self) -> Dict[str, Any]:
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

    # ... [Keep existing _prune_data_structure, _map_and_merge, _generate_reports] ...
    # (These do not need changes based on the prompt, assuming they are imported or copied from original file)
    
    def _prune_data_structure(self, data: Any, limit: int = 10) -> Any:
        if isinstance(data, dict):
            return {k: self._prune_data_structure(v, limit) for k, v in data.items()}
        elif isinstance(data, list):
            pruned_list = data[:limit]
            return [self._prune_data_structure(item, limit) for item in pruned_list]
        else:
            return data

    def _map_and_merge(self, scraper_outputs: Dict[str, Any]) -> tuple[Dict, Dict]:
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
        
        self.logger.info(f"Pruning data: Limiting all lists to a maximum of 10 items.")
        pruned_template = self._prune_data_structure(filled_template, limit=10)
        
        return pruned_template, mapping_report

    def _generate_reports(self, final_data: Dict, mapping_report: Dict):
        final_output_path = os.path.join(self.outdir, 'final_report.json')
        reporting.generate_final_output(final_data, final_output_path)
        
        report_path_md = os.path.join(self.outdir, 'mapping_report.md')
        reporting.generate_mapping_report_md(mapping_report, report_path_md)
        
        checklist_path = os.path.join(self.outdir, 'review_checklist.md')
        reporting.generate_checklist_md(final_data, checklist_path)

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