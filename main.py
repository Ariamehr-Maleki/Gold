# main.py
import argparse
import json
import os
from datetime import datetime

from orchestrator.engine import Orchestrator
from orchestrator.utils import setup_logging

def run_orchestration(args):
    """Loads configs and runs the main orchestrator."""
    
    # --- 1. Create Output Directory ---
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_directory = os.path.join(args.outdir, run_timestamp)
    os.makedirs(output_directory, exist_ok=True)
    
    # Setup logging
    log_file_path = os.path.join(output_directory, 'orchestrator.log')
    logger = setup_logging(log_file_path)

    # --- 2. Load Main Configuration Files ---
    try:
        with open(args.config, 'r', encoding='utf-8') as f:
            config = json.load(f)
        logger.info(f"Loaded main configuration from {args.config}")
        
        with open(args.template, 'r', encoding='utf-8') as f:
            template = json.load(f)
        logger.info(f"Loaded data template from {args.template}")
    except FileNotFoundError as e:
        logger.critical(f"Configuration or template file not found: {e}")
        return
    except json.JSONDecodeError as e:
        logger.critical(f"Error decoding JSON from a configuration file: {e}")
        return

    run_params = {}
    if args.run_config:
        try:
            with open(args.run_config, 'r', encoding='utf-8') as f:
                run_params = json.load(f)
            logger.info(f"Loaded scraper run parameters from {args.run_config}")
        except (FileNotFoundError, json.JSONDecodeError) as e:
            logger.critical(f"Could not load or parse run config file: {e}")
            return
            
    # Second, override with any specific command-line arguments
    cli_overrides = {
        'hs_code': args.hs_code,
        'your_country_id': args.your_country_id,
        'your_country_name': args.your_country_name,
        'target_market_id': args.target_market_id,
        'target_market_name': args.target_market_name
    }
    # Filter out None values and update the params
    # This ensures that only arguments actually passed on the CLI will override the file
    active_overrides = {k: v for k, v in cli_overrides.items() if v is not None}
    if active_overrides:
        logger.info(f"Overriding run config with CLI arguments: {active_overrides}")
        run_params.setdefault('common_params', {}).update(active_overrides)


    # --- 4. Initialize and Run the Orchestrator ---
    orchestrator = Orchestrator(
        config=config,
        template=template,
        outdir=output_directory,
        run_params=run_params,
        is_dry_run=args.dry_run,
        parallel=not args.sequential,
        timeout=args.timeout,
        logger=logger
    )
    
    orchestrator.run()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Main orchestrator for the trade data scraping suite.")
    
    # --- Configuration for the run (file-based with CLI overrides) ---
    parser.add_argument("--run-config", default="config/run_config.json", help="Path to the JSON file with run parameters (HS code, countries, etc.).")
    
    # --- Optional Overrides for run-config ---
    parser.add_argument("--hs-code", help="Override the HS code from the run-config file.")
    parser.add_argument("--your-country-id", help="Override the exporting country ID from the run-config file.")
    parser.add_argument("--your-country-name", help="Override the exporting country name from the run-config file.")
    parser.add_argument("--target-market-id", help="Override the target market ID from the run-config file.")
    parser.add_argument("--target-market-name", help="Override the target market name from the run-config file.")

    # --- Orchestrator settings ---
    parser.add_argument("--config", default="config/config.json", help="Path to the main JSON configuration file.")
    parser.add_argument("--template", default="config/template.json", help="Path to the JSON template for the final output.")
    parser.add_argument("--outdir", default="./runs", help="Directory to save all outputs, logs, and reports.")
    parser.add_argument("--timeout", type=int, default=600, help="Timeout in seconds for each scraper subprocess.")
    parser.add_argument("--dry-run", action='store_true', help="Run the orchestrator without executing scrapers. Used for testing mapping.")
    parser.add_argument("--sequential", action='store_true', help="Force scrapers to run one by one instead of in parallel.")
    
    args = parser.parse_args()
    run_orchestration(args)