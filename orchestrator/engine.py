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
from orchestrator.factsheet_builder import FactsheetBuilder 
from orchestrator import reporting, doc_generator
from orchestrator.utils import get_by_path

class Orchestrator:
    """
    Orchestrates scraper execution, data aggregation, and report generation.
    """
    def __init__(self, config: Dict, template: Dict, outdir: str, run_params: Dict,
                 country_map: Dict, country_map_m49: Dict, is_dry_run: bool, parallel: bool, timeout: int, logger: logging.Logger):
        self.config = config
        self.template = template
        self.outdir = outdir
        self.run_params = run_params 
        self.country_map = country_map  # ITC codes (default for all scrapers except eping)
        self.country_map_m49 = country_map_m49  # M49 codes (for eping)
        self.is_dry_run = is_dry_run
        self.parallel = parallel
        self.timeout = timeout
        self.logger = logger
        
        # Create specific folders
        self.log_dir = os.path.join(self.outdir, 'logs')
        self.scraper_output_dir = os.path.join(self.outdir, 'scraper_results')
        
        os.makedirs(self.log_dir, exist_ok=True)
        os.makedirs(self.scraper_output_dir, exist_ok=True)
        
        self.run_metadata = {}
        self._resolve_country_ids()

    def run(self):
        """Main execution flow."""
        self.logger.info("Orchestration started.")
        
        run_results = []
        if self.is_dry_run:
            self.logger.info("Dry run mode: Skipping scraper execution.")
        else:
            run_results = self._run_scrapers_with_dependencies()
        
        self.run_metadata['scraper_runs'] = run_results
        
        # Load results
        scraper_outputs = self._load_scraper_outputs()
        
        # Aggregate results into the final structure (Replacing old mapping logic)
        final_data = self._aggregate_results(scraper_outputs)
        
        # Generate final files
        self._generate_reports(final_data)
        self.logger.info(f"Orchestration finished. All outputs are in: {self.outdir}")

    def _resolve_country_ids(self):
        """
        Populates scraper-specific IDs based on the Country Name provided.
        ePing -> M49 Code
        TradeMap/Others -> ITC Code
        """
        common = self.run_params.get("common_params", {})
        target_name = common.get("target_market_name")

        # Ensure storage exists
        if "scraper_specific_params" not in self.run_params:
            self.run_params["scraper_specific_params"] = {}

        if target_name:
            target_name_upper = target_name.upper()
            
            # 1. Lookup Codes
            itc_code = self.country_map.get(target_name_upper)
            m49_code = self.country_map_m49.get(target_name_upper)

            if itc_code or m49_code:
                self.logger.info(f"Resolving '{target_name}': ITC={itc_code}, M49={m49_code}")

                # 2. Assign to EPING (Must use M49)
                if "eping" not in self.run_params["scraper_specific_params"]:
                    self.run_params["scraper_specific_params"]["eping"] = {}
                
                if m49_code:
                    self.run_params["scraper_specific_params"]["eping"]["target_market_id"] = m49_code
                else:
                    self.logger.warning(f"No M49 code found for '{target_name}'. ePing may fail.")

                # 3. Assign to OTHERS (Use ITC)
                for s in ['trademap', 'macmap', 'potential']:
                    if s not in self.run_params["scraper_specific_params"]:
                        self.run_params["scraper_specific_params"][s] = {}
                    if itc_code:
                        self.run_params["scraper_specific_params"][s]["target_market_id"] = itc_code
            else:
                self.logger.warning(f"Target '{target_name}' not found in country maps.")

    def _run_scrapers_with_dependencies(self) -> List[Dict]:
        """
        Phase 1: TradeMap & Independent.
        Phase 2: MacMap (dependent on TradeMap competitors).
        """
        all_scrapers = self.config.get('scrapers', [])
        results = []

        trademap_conf = next((s for s in all_scrapers if s['name'] == 'trademap'), None)
        macmap_conf = next((s for s in all_scrapers if s['name'] == 'macmap'), None)
        independent_scrapers = [s for s in all_scrapers if s['name'] != 'macmap']
        
        # --- PHASE 1 ---
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

        # --- MIDDLEWARE: Extract Competitors for MacMap ---
        if macmap_conf:
            tm_result = next((r for r in phase1_results if r['name'] == 'trademap' and r['status'] == 'SUCCESS'), None)
            
            competitor_ids = []
            competitor_names_map = {}
            if tm_result:
                self.logger.info("Analyzing TradeMap results to find top competitors...")
                competitor_ids, competitor_names_map = self._extract_competitors_from_trademap_output(tm_result['output_path'])
            else:
                self.logger.warning("TradeMap failed or didn't run. Cannot dynamically set MacMap competitors.")

            if competitor_ids:
                self.logger.info(f"Injecting Competitor IDs into MacMap: {competitor_ids}")
                self.logger.info(f"Competitor Names Map: {competitor_names_map}")
                
                if 'scraper_specific_params' not in self.run_params:
                    self.run_params['scraper_specific_params'] = {}
                if 'macmap' not in self.run_params['scraper_specific_params']:
                    self.run_params['scraper_specific_params']['macmap'] = {}

                # Join IDs as string for CLI arg
                self.run_params['scraper_specific_params']['macmap']['competitor_ids'] = " ".join(competitor_ids)
                
                # Store names map as JSON for CLI arg
                names_map_json = json.dumps(competitor_names_map)
                self.run_params['scraper_specific_params']['macmap']['competitor_names_map'] = names_map_json

            # --- PHASE 2 ---
            self.logger.info("--- Phase 2: Running Dependent Scrapers (MacMap) ---")
            macmap_result = self._run_single_scraper(macmap_conf)
            results.append(macmap_result)

        return results

    def _extract_competitors_from_trademap_output(self, json_path: str) -> tuple:
        """
        Reads TradeMap raw snapshots to find top 3 suppliers.
        Returns: (competitor_ids: List[str], names_map: Dict[str, str])
        """
        found_ids = []
        names_map = {}  # Maps competitor ID to country name
        try:
            with open(json_path, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            # Note: We look at the raw snapshots, not the generated factsheet
            suppliers_snapshot = data.get("snapshots", {}).get("target_market_suppliers", {})
            rows = suppliers_snapshot.get("data", [])
            
            if not rows:
                self.logger.warning("No supplier data found in TradeMap output.")
                return [], {}

            yc_name = self.run_params.get("common_params", {}).get("your_country_name", "").lower()
            
            valid_competitors = []
            for row in rows:
                p_name = row.get("partner_country", "").strip()
                p_name_lower = p_name.lower()
                
                if p_name_lower in ["world", "total", "nan", ""]: 
                    continue
                if yc_name and yc_name in p_name_lower:
                    continue
                
                val = row.get("value_imported_usd") or 0
                valid_competitors.append({"name": p_name, "value": val})

            top_3 = sorted(valid_competitors, key=lambda x: x['value'], reverse=True)[:3]
            
            for comp in top_3:
                c_name = comp['name']
                c_id = self.country_map.get(c_name.upper())
                
                # If exact match fails, try alternative format (replace ", " with " (")
                if not c_id and ", " in c_name:
                    alt_name = c_name.replace(", ", " (") + ")"
                    c_id = self.country_map.get(alt_name.upper())
                
                if c_id:
                    self.logger.info(f"Found Competitor: {c_name} -> ID: {c_id}")
                    found_ids.append(c_id)
                    names_map[c_id] = c_name  # Store the mapping
                else:
                    self.logger.warning(f"Could not find ID for competitor '{c_name}' in country_map.")

        except Exception as e:
            self.logger.error(f"Error extracting competitors: {e}")
        
        return found_ids, names_map

    def _run_single_scraper(self, scraper_config: Dict) -> Dict:
        name = scraper_config['name']
        script_path = scraper_config['path']
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
                if key == "competitor_ids" and isinstance(value, str):
                    cmd.append(arg_name)
                    cmd.extend(value.split()) 
                elif key == "competitor_names_map" and isinstance(value, str):
                    # Pass as-is (JSON string)
                    cmd.extend([arg_name, value])
                else:
                    cmd.extend([arg_name, str(value)])

        self.logger.info(f"Running scraper '{name}'...")
        start_time = time.time()
        result = {"name": name, "status": "FAIL", "duration": 0, "output_path": output_path}

        try:
            with open(log_path, 'w', encoding='utf-8') as log_file:
                process = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout, check=False)
                log_file.write("--- STDOUT ---\n" + process.stdout + "\n--- STDERR ---\n" + process.stderr)

            result["duration"] = round(time.time() - start_time, 2)
            
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

    def _aggregate_results(self, scraper_outputs: Dict[str, Any]) -> Dict[str, Any]:
        """
        Merges the specific output sections from each scraper into the final report structure.
        """
        self.logger.info("Aggregating scraper results into final report structure...")
        
        final_report = {
            "meta": {
                "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "run_metadata": self.run_metadata,
                "data_sources_status": {k: "Loaded" for k in scraper_outputs.keys()}
            }
        }

        # 1. TradeMap: Quantitative Export Factsheet
        if "trademap" in scraper_outputs:
            data = scraper_outputs["trademap"]["data"]
            # trademap_scraper.py now outputs "factsheet": { "Quantitative_Export_Factsheet": ... }
            if "factsheet" in data:
                final_report["factsheet"] = data["factsheet"] # Keep the top level key 'factsheet' as per your example
            else:
                self.logger.warning("TradeMap output missing 'factsheet' key.")

            # <--- ADD THIS: Pass Raw Snapshots for calculation logic --->
            if "snapshots" in data:
                final_report["snapshots"] = data["snapshots"]
            if "meta" in data:
                 final_report["trademap_meta"] = data["meta"]
                 
        # 2. MacMap: Market Access
        if "macmap" in scraper_outputs:
            data = scraper_outputs["macmap"]["data"]
            # macmap_scraper.py outputs { "Market_Access": ... }
            if "Market_Access" in data:
                final_report["Market_Access"] = data["Market_Access"]
            else:
                self.logger.warning("MacMap output missing 'Market_Access' key.")

        # 3. Export Potential Map
        if "potential" in scraper_outputs:
            data = scraper_outputs["potential"]["data"]
            # potential_scraper.py outputs { "source": ..., "analysis": ... }
            # Your desired output shows the whole object structure
            final_report["Export_Potential"] = data # We can verify if we want the root or just specific keys

        # 4. ePing: SPS/TBT Notifications
        if "eping" in scraper_outputs:
            data = scraper_outputs["eping"]["data"]
            # eping_scraper.py outputs { "config": ..., "data": { "notifications": ... } }
            final_report["SPS_TBT_Notifications"] = data # Storing the root ePing output

        return final_report

    def _generate_reports(self, final_data: Dict):
        """
        Generates final JSON, the specific Factsheet Schema JSON, and formatted document.
        """
        # 1. Save the aggregated Raw Report
        final_output_path = os.path.join(self.outdir, 'final_reportNew.json')
        reporting.generate_final_output(final_data, final_output_path)
        
        # 2. Build and Save the Presentation-Ready Factsheet JSON
        self.logger.info("Transforming data into Factsheet Schema...")
        try:
            builder = FactsheetBuilder(final_data)
            factsheet_json = builder.build()
            
            factsheet_json_path = os.path.join(self.outdir, 'factsheet_data.json')
            with open(factsheet_json_path, 'w', encoding='utf-8') as f:
                json.dump(factsheet_json, f, indent=4, ensure_ascii=False)
            
            self.logger.info(f"Factsheet data saved to: {factsheet_json_path}")
            
        except Exception as e:
            self.logger.error(f"Failed to build factsheet JSON: {e}", exc_info=True)

        # 3. Generate Word Document (Optional: You can now update doc_generator to use factsheet_data.json)
        self.logger.info("Starting generation of Quantitative Export Factsheet Document...")
        template_path = "Quantitative_Factsheet_Template.docx"
        
        if os.path.exists(template_path):
            try:
                # Note: doc_generator might need updates to read the new factsheet_data.json structure
                # For now, we keep the call as is, or you can point it to the new file.
                doc_generator.run(
                    json_path=final_output_path, # Or factsheet_json_path if you update doc_generator
                    template_path=template_path,
                    output_dir=self.outdir
                )
                self.logger.info("Successfully generated factsheet documents.")
            except Exception as e:
                self.logger.error(f"Failed to generate factsheet document: {e}", exc_info=True)
        else:
            self.logger.warning(f"Factsheet template not found at '{template_path}'.")