# orchestrator/utils.py
import logging
import os
import sys
from typing import Any, Dict, List, Optional

def setup_logging(log_file_path: str) -> logging.Logger:
    """Configures and returns a logger that writes to both file and console."""
    logger = logging.getLogger("Orchestrator")
    logger.setLevel(logging.INFO)

    # --- FIX: Prevent double logging by stopping propagation to root logger ---
    logger.propagate = False 

    # Prevent adding duplicate handlers if this function is called multiple times
    if logger.hasHandlers():
        logger.handlers.clear()

    # File handler
    file_handler = logging.FileHandler(log_file_path, mode='w', encoding='utf-8')
    file_formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    file_handler.setFormatter(file_formatter)
    logger.addHandler(file_handler)

    # Console handler
    console_handler = logging.StreamHandler(sys.stdout)
    console_formatter = logging.Formatter('%(levelname)s: %(message)s')
    console_handler.setFormatter(console_formatter)
    logger.addHandler(console_handler)

    return logger

def setup_logging(log_file_path):
    # (Existing logging setup code here)
    logger = logging.getLogger(__name__)
    logger.setLevel(logging.INFO)
    
    # Create file handler
    fh = logging.FileHandler(log_file_path)
    fh.setLevel(logging.INFO)
    
    # Create console handler
    ch = logging.StreamHandler()
    ch.setLevel(logging.INFO)
    
    # Create formatter and add it to the handlers
    formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
    fh.setFormatter(formatter)
    ch.setFormatter(formatter)
    
    # Add the handlers to the logger
    logger.addHandler(fh)
    logger.addHandler(ch)
    
    return logger

def load_country_lookup(logger, json_path="m49-list-with-itc.json"):
    """
    Loads the country JSON and creates a mapping from country name to M49 code.
    """
    country_map = {}
    try:
        with open(json_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
            for country in data.get('countries', []):
                name = country.get('name')
                m49code = country.get('m49code')
                
                # We use the country name in all caps as the key for case-insensitive lookup
                if name and m49code is not None:
                    country_map[name.upper()] = str(m49code)

        logger.info(f"Loaded {len(country_map)} country names for lookup.")
    except FileNotFoundError:
        logger.warning(f"Country code file not found at {json_path}. Name-to-code lookup disabled.")
    except json.JSONDecodeError as e:
        logger.error(f"Error decoding country JSON file: {e}")
    except Exception as e:
        logger.error(f"An unexpected error occurred while loading country data: {e}")

    return country_map

def get_country_code(country_name, country_map):
    """
    Translates a country name (case-insensitive) to its M49 code string.
    """
    if not country_name:
        return None
    return country_map.get(country_name.upper())

def get_by_path(data: Dict[str, Any], path: str) -> Optional[Any]:
    """
    Access a nested value in a dictionary using a dot-separated path.
    Example: get_by_path(data, "a.b.c")
    """
    keys = path.split('.')
    for key in keys:
        if isinstance(data, dict) and key in data:
            data = data[key]
        else:
            return None
    return data

def set_by_path(data: Dict[str, Any], path: str, value: Any):
    """
    Set a value in a nested dictionary using a dot-separated path.
    Creates nested dictionaries if they don't exist.
    Example: set_by_path(data, "a.b.c", 123)
    """
    keys = path.split('.')
    current_level = data
    for i, key in enumerate(keys[:-1]):
        if key not in current_level or not isinstance(current_level[key], dict):
            current_level[key] = {}
        current_level = current_level[key]
    current_level[keys[-1]] = value