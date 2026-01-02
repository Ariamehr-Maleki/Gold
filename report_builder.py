import argparse
import json
import os
import sys
from datetime import datetime

def load_json_file(filepath):
    """Safely loads a JSON file, providing a clear error message on failure."""
    if not os.path.exists(filepath):
        print(f"WARNING: File not found at '{filepath}'. Skipping this section.")
        return None
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except json.JSONDecodeError:
        print(f"ERROR: The file '{filepath}' contains invalid JSON. Skipping.")
        return None

def main():
    """
    Aggregates separate scraper outputs into a single final_report.json.
    Assumes scrapers now output pre-structured data sections (Factsheet, Market Access, etc.).
    """
    parser = argparse.ArgumentParser(
        description="Aggregates scraper outputs into a final structured JSON report."
    )
    parser.add_argument(
        "--input-dir", 
        required=True, 
        help="Path to the directory containing the scraper output JSON files."
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to save the final structured report JSON file."
    )
    args = parser.parse_args()

    # 1. Validate Input Directory
    if not os.path.isdir(args.input_dir):
        print(f"FATAL ERROR: The input directory '{args.input_dir}' does not exist.")
        sys.exit(1)

    # 2. Define expected filenames
    files_map = {
        "trademap": os.path.join(args.input_dir, "trademap_output.json"),
        "macmap": os.path.join(args.input_dir, "macmap_output.json"),
        "eping": os.path.join(args.input_dir, "eping_output.json"),
        "potential": os.path.join(args.input_dir, "export_potential_output.json")
    }

    # 3. Load Data
    data_sources = {k: load_json_file(v) for k, v in files_map.items()}

    # 4. Build Final Report Structure
    final_report = {
        "meta": {
            "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "data_sources_status": {k: "Loaded" if v else "Missing" for k, v in data_sources.items()}
        }
    }

    # --- Section A: Quantitative Factsheet (TradeMap) ---
    # Scraper Output: { "factsheet": { "Quantitative_Export_Factsheet": { ... } }, ... }
    tm_data = data_sources.get("trademap")
    if tm_data and "factsheet" in tm_data:
        # We extract the inner dictionary directly
        final_report["Quantitative_Export_Factsheet"] = tm_data["factsheet"].get("Quantitative_Export_Factsheet", {})
    else:
        final_report["Quantitative_Export_Factsheet"] = {}

    # --- Section B: Market Access (MacMap) ---
    # Scraper Output: { "Market_Access": { ... } }
    mm_data = data_sources.get("macmap")
    if mm_data and "Market_Access" in mm_data:
        final_report["Market_Access"] = mm_data["Market_Access"]
    else:
        final_report["Market_Access"] = {}

    # --- Section C: Export Potential (Potential Map) ---
    # Scraper Output: { "source": "...", "analysis": { "product": ..., "export_potential": ... } }
    ep_data = data_sources.get("potential")
    if ep_data and "analysis" in ep_data:
        final_report["Export_Potential"] = ep_data["analysis"]
    else:
        final_report["Export_Potential"] = {}

    # --- Section D: SPS/TBT Notifications (ePing) ---
    # Scraper Output: { "config": ..., "data": { "notifications": [...] } }
    eping_data = data_sources.get("eping")
    if eping_data and "data" in eping_data:
        final_report["SPS_TBT_Notifications"] = eping_data["data"]
    else:
        final_report["SPS_TBT_Notifications"] = {"notifications": []}

    # 5. Save Final Report
    try:
        os.makedirs(os.path.dirname(args.output), exist_ok=True)
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(final_report, f, ensure_ascii=False, indent=4)
        print(f"SUCCESS: Final report generated at '{args.output}'")
    except Exception as e:
        print(f"FATAL ERROR: Failed to write output file: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()