# orchestrator/utils.py

import json
import logging
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

def setup_logging(log_file_path: str) -> logging.Logger:
    """Configures and returns a logger that writes to both file and console."""
    logger = logging.getLogger("Orchestrator")
    logger.setLevel(logging.INFO)
    logger.propagate = False 

    if logger.hasHandlers():
        logger.handlers.clear()

    try:
        file_handler = logging.FileHandler(log_file_path, mode='w', encoding='utf-8')
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(levelname)s - %(message)s'))
        logger.addHandler(file_handler)
    except Exception as e:
        print(f"Warning: Could not set up file logging: {e}")

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(logging.Formatter('%(levelname)s: %(message)s'))
    logger.addHandler(console_handler)

    return logger

def load_dual_country_maps(logger, json_path="m49-list-with-itc.json") -> Tuple[Dict[str, str], Dict[str, str]]:
    """
    Reads the JSON file ONCE and returns two separate lookups.
    Returns: (itc_map, m49_map)
    """
    itc_map = {}
    m49_map = {}

    try:
        if not os.path.exists(json_path):
             logger.warning(f"Country code file not found at {json_path}. Lookups disabled.")
             return {}, {}

        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Support both structure types: list or dict with 'countries'
        items = data['countries'] if isinstance(data, dict) and 'countries' in data else data

        for country in items:
            # Get Name (Normalize to UPPER for lookup)
            name = country.get('name') or country.get('Name') or country.get('english')
            if not name: 
                continue
            
            normalized_name = name.strip().upper()

            # 1. Populate ITC Map
            itc = country.get('itcCode')
            if itc is not None:
                itc_map[normalized_name] = str(itc)

            # 2. Populate M49 Map
            m49 = country.get('m49code')
            if m49 is not None:
                m49_map[normalized_name] = str(m49)

        logger.info(f"Loaded Maps: {len(itc_map)} ITC codes, {len(m49_map)} M49 codes.")
        
    except Exception as e:
        logger.error(f"Error loading dual country maps: {e}")
        return {}, {}

    return itc_map, m49_map

def get_country_code(country_name, country_map):
    """Translates a country name (case-insensitive) to code string."""
    if not country_name: return None
    return country_map.get(country_name.upper())

def get_by_path(data: Dict[str, Any], path: str) -> Optional[Any]:
    keys = path.split('.')
    current = data
    for key in keys:
        if isinstance(current, dict) and key in current:
            current = current[key]
        elif isinstance(current, list):
            try:
                idx = int(key)
                if 0 <= idx < len(current): current = current[idx]
                else: return None
            except ValueError: return None
        else: return None
    return current