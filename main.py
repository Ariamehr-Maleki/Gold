# main.py

import argparse
import json
import os
from datetime import datetime

from orchestrator.engine import Orchestrator
from orchestrator.utils import setup_logging, load_dual_country_maps, get_country_code

def run_orchestration(args):
    # --- 1. Logging Setup ---
    run_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    output_directory = os.path.join(args.outdir, run_timestamp)
    os.makedirs(output_directory, exist_ok=True)
    logger = setup_logging(os.path.join(output_directory, 'orchestrator.log'))

    # --- 2. Load Configs ---
    try:
        with open(args.config, 'r', encoding='utf-8') as f:
            config = json.load(f)
        with open(args.template, 'r', encoding='utf-8') as f:
            template = json.load(f)
    except Exception as e:
        logger.critical(f"Config load error: {e}")
        return

    # --- 3. Load Country Maps (ITC + M49) ---
    # This reads the file once and gives us both dictionaries
    itc_map, m49_map = load_dual_country_maps(logger, args.country_list)

    # --- 4. Run Parameters & Overrides ---
    run_params = {}
    if args.run_config and os.path.exists(args.run_config):
        try:
            with open(args.run_config, 'r') as f: run_params = json.load(f)
        except Exception: pass

    # Resolve IDs for CLI args (Defaulting to ITC for general "common_params")
    resolved_your_id = args.your_country_id or get_country_code(args.your_country_name, itc_map)
    resolved_target_id = args.target_market_id or get_country_code(args.target_market_name, itc_map)

    overrides = {
        'hs_code': args.hs_code,
        'your_country_id': resolved_your_id,
        'your_country_name': args.your_country_name,
        'target_market_id': resolved_target_id,
        'target_market_name': args.target_market_name
    }
    
    # Update run_params
    if 'common_params' not in run_params: run_params['common_params'] = {}
    run_params['common_params'].update({k: v for k, v in overrides.items() if v is not None})

    # --- 5. Start Orchestrator ---
    orchestrator = Orchestrator(
        config=config,
        template=template,
        outdir=output_directory,
        run_params=run_params,
        country_map=itc_map,       # Standard map
        country_map_m49=m49_map,   # ePing specific map
        is_dry_run=args.dry_run,
        parallel=not args.sequential,
        timeout=args.timeout,
        logger=logger
    )
    
    orchestrator.run()

    return output_directory

if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-config", default="config/run_config.json")
    parser.add_argument("--country-list", default="m49-list-with-itc.json")
    parser.add_argument("--hs-code")
    parser.add_argument("--your-country-id")
    parser.add_argument("--target-market-id")
    parser.add_argument("--your-country-name")
    parser.add_argument("--target-market-name")
    parser.add_argument("--config", default="config/config.json")
    parser.add_argument("--template", default="config/template.json")
    parser.add_argument("--outdir", default="./runs")
    parser.add_argument("--timeout", type=int, default=600)
    parser.add_argument("--dry-run", action='store_true')
    parser.add_argument("--sequential", action='store_true')
    
    args = parser.parse_args()
    run_orchestration(args)