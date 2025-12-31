# main.py

import argparse
import json
import os
from datetime import datetime

from orchestrator.engine import Orchestrator
from orchestrator.utils import setup_logging, load_country_lookup, get_country_code 

def run_orchestration(args):
    """Loads configs and runs the main orchestrator."""
    
    # --- 1. Create Output Directory and Setup Logging ---
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
    
    # --- 3. Load Country Code Lookup ---
    # We pass this map to the Orchestrator later
    country_map = load_country_lookup(logger, args.country_list)

    # --- 4. Load Run Parameters & Apply Overrides ---
    run_params = {}
    
    # Attempt to load run_config, but do NOT crash if missing.
    # This ensures CLI arguments can work standalone.
    if args.run_config:
        if os.path.exists(args.run_config):
            try:
                with open(args.run_config, 'r', encoding='utf-8') as f:
                    run_params = json.load(f)
                logger.info(f"Loaded scraper run parameters from {args.run_config}")
            except json.JSONDecodeError as e:
                logger.error(f"Error parsing run config file: {e}. Proceeding with defaults.")
        else:
            logger.warning(f"Run config file '{args.run_config}' not found. Relying on CLI arguments.")

    # --- Handle Name-to-ID Translation ---
    # Priority: 
    # 1. CLI Explicit ID (--your-country-id)
    # 2. CLI Name Translation (--your-country-name -> Lookup)
    # 3. Existing value in run_params (handled by update logic later)

    resolved_your_id = args.your_country_id or get_country_code(args.your_country_name, country_map)
    resolved_target_id = args.target_market_id or get_country_code(args.target_market_name, country_map)
    
    # Warning if name provided but ID not found
    if args.your_country_name and not resolved_your_id:
        logger.warning(f"Could not resolve ID for Your Country Name: '{args.your_country_name}'")
    if args.target_market_name and not resolved_target_id:
        logger.warning(f"Could not resolve ID for Target Market Name: '{args.target_market_name}'")

    # Define overrides (None values are filtered out)
    cli_overrides = {
        'hs_code': args.hs_code,
        'your_country_id': resolved_your_id, 
        'your_country_name': args.your_country_name,
        'target_market_id': resolved_target_id,
        'target_market_name': args.target_market_name
    }
    
    active_overrides = {k: v for k, v in cli_overrides.items() if v is not None}
    
    # Log successful resolutions for clarity
    if args.your_country_name and resolved_your_id and str(resolved_your_id) != args.your_country_id:
        logger.info(f"Resolved 'Your Country' name '{args.your_country_name}' to ID '{resolved_your_id}'")
    if args.target_market_name and resolved_target_id and str(resolved_target_id) != args.target_market_id:
        logger.info(f"Resolved 'Target Market' name '{args.target_market_name}' to ID '{resolved_target_id}'")
        
    # APPLY OVERRIDES
    if active_overrides:
        logger.info(f"Overriding run config with CLI arguments: {active_overrides}")
        # Ensure common_params dict exists
        if 'common_params' not in run_params:
            run_params['common_params'] = {}
        # Update (Overwrite) existing params with CLI values
        run_params['common_params'].update(active_overrides)

    # --- 5. Initialize and Run the Orchestrator ---
    orchestrator = Orchestrator(
        config=config,
        template=template,
        outdir=output_directory,
        run_params=run_params,
        country_map=country_map,
        is_dry_run=args.dry_run,
        parallel=not args.sequential,
        timeout=args.timeout,
        logger=logger
    )
    
    orchestrator.run()

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Main orchestrator for the trade data scraping suite.")
    parser.add_argument("--run-config", default="config/run_config.json", help="Path to the JSON file with run parameters.")
    parser.add_argument("--country-list", default="m49-list-with-itc.json", help="Path to the JSON file containing country names and codes.")
    
    parser.add_argument("--hs-code", help="Override HS code.")
    parser.add_argument("--your-country-id", help="Override exporting country ID.")
    parser.add_argument("--target-market-id", help="Override target market ID.")
    parser.add_argument("--your-country-name", help="Override exporting country name.")
    parser.add_argument("--target-market-name", help="Override target market name.")

    parser.add_argument("--config", default="config/config.json", help="Main scraper config.")
    parser.add_argument("--template", default="config/template.json", help="Output template.")
    parser.add_argument("--outdir", default="./runs", help="Output directory.")
    parser.add_argument("--timeout", type=int, default=600, help="Scraper timeout.")
    parser.add_argument("--dry-run", action='store_true', help="Dry run.")
    parser.add_argument("--sequential", action='store_true', help="Force sequential execution.")
    
    args = parser.parse_args()
    run_orchestration(args)