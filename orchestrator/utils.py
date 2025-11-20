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