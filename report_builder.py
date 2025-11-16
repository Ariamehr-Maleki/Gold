import argparse
import json
import os
import sys
from datetime import datetime

def load_json_file(filepath):
    """Safely loads a JSON file, providing a clear error message on failure."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        print(f"FATAL ERROR: A required file was not found at '{filepath}'.")
        return None
    except json.JSONDecodeError:
        print(f"FATAL ERROR: The file '{filepath}' contains invalid JSON and could not be read.")
        return None

def format_value(num):
    """Formats a number into a more readable string (e.g., billions, millions)."""
    if num is None or not isinstance(num, (int, float)):
        return "[Data not available]"
    if num >= 1_000_000_000:
        return f"{num / 1_000_000_000:.2f} billion"
    if num >= 1_000_000:
        return f"{num / 1_000_000:.2f} million"
    if num >= 1_000:
        return f"{num / 1_000:.2f} thousand"
    return str(num)

def populate_template_fields(trademap, macmap, eping, export_potential):
    """
    Processes loaded JSON data and builds a structured dictionary for the final report.
    """
    report = {}

    # --- Introduction & Overview ---
    report['introduction'] = {
        "product_name": macmap['overview'].get('product_description', '[Not Found]').split('–')[1].strip(),
        "target_market": trademap['config'].get('target_market', '[Not Found]'),
        "report_date": datetime.now().strftime("%B %Y"),
        "product_hs_code": trademap['config'].get('hs_code', '[Not Found]'),
        "exporting_country": trademap['config'].get('your_country', '[Not Found]'),
        "total_exports_from_country_usd": trademap.get('your_country_total_exports', {}).get('value_usd'),
        "total_exports_year": trademap.get('your_country_total_exports', {}).get('year'),
        "target_market_world_rank": trademap['importer_ranking'].get('target_market_world_rank')
    }

    # --- Market Size ---
    tm_world_imports = trademap['market_analysis'].get('total_value_usd')
    world_total_imports = trademap['importer_ranking'].get('world_total_imports_usd')
    share_in_world = (tm_world_imports / world_total_imports * 100) if tm_world_imports and world_total_imports else 0

    report['market_size'] = {
        "year": trademap['market_analysis'].get('latest_year'),
        "target_market_imports_from_world_usd": tm_world_imports,
        "target_market_share_of_world_imports_pct": round(share_in_world, 2),
        "target_market_imports_from_your_country_usd": trademap['market_analysis'].get('value_usd'),
        "your_country_market_share_pct": trademap['market_analysis'].get('market_share_pct')
    }

    # --- Market Growth ---
    report['market_growth'] = {
        "target_market_import_growth_5y_cagr_pct": trademap['market_analysis'].get('market_growth_cagr_pct'),
        "target_market_import_growth_last_year_pct": trademap['market_analysis'].get('market_growth_last_year_pct'),
        "import_growth_from_your_country_5y_cagr_pct": trademap['market_analysis'].get('growth_cagr_pct'),
        "your_country_gained_market_share": trademap['market_analysis'].get('gained_share_over_5_years')
    }
    
    # --- Unit Value Analysis ---
    top_suppliers = trademap['market_analysis'].get('top_suppliers_sample', [])
    highest_uv_supplier = max(top_suppliers, key=lambda x: x.get('unit_value_latest') or 0) if top_suppliers else {}
    lowest_uv_supplier = min(top_suppliers, key=lambda x: x.get('unit_value_latest') or 9e9) if top_suppliers else {}

    report['unit_value_analysis'] = {
        "target_market_avg_unit_value_usd": trademap['market_analysis'].get('world_unit_values', [None])[-1],
        "your_country_unit_value_usd": trademap['market_analysis'].get('unit_value_latest'),
        "highest_unit_value_supplier": {
            "name": highest_uv_supplier.get('name'),
            "value_usd_per_unit": highest_uv_supplier.get('unit_value_latest')
        },
        "lowest_unit_value_supplier": {
            "name": lowest_uv_supplier.get('name'),
            "value_usd_per_unit": lowest_uv_supplier.get('unit_value_latest')
        }
    }

    # --- Competition ---
    report['competition'] = {
        "market_concentration_level": trademap['market_analysis'].get('concentration'),
        "hhi_index": trademap['market_analysis'].get('hhi'),
        "top_3_suppliers": trademap['market_analysis'].get('suppliers_full_list', [])[:3],
        "suppliers_gaining_share": trademap['market_analysis'].get('suppliers_gaining_share', []),
        "top_regional_competitors": trademap['market_analysis'].get('regional_suppliers', [])[:5]
    }

    # --- Market Access ---
    tariffs = macmap.get('customs_tariffs', [])
    your_country_tariff = "Not Found"
    if tariffs and isinstance(tariffs[0], dict):
        tariff_key = next((k for k in tariffs[0] if k and k.strip().startswith("Applied Tariff")), None)
        if tariff_key:
            your_country_tariff = tariffs[0][tariff_key]

    report['market_access'] = {
        "benefits_from_preferential_access": False, # Assuming default
        "your_country_applied_tariff": your_country_tariff,
        "trade_remedies": macmap.get('trade_remedies', []),
        "regulatory_requirements": macmap.get('regulatory_requirements', {})
    }

    # --- Potential New Regulations ---
    report['potential_new_regulations'] = {
        "status": eping.get('status', 'No data'),
        "notification_count": len(eping.get('notifications', [])),
        "notifications": eping.get('notifications', [])
    }
    
    # --- Other Data ---
    report['other_data'] = {
        "potential_importers": trademap.get('potential_importers', []),
        "unrealized_export_potential": export_potential.get('analysis', {}).get('unrealized_potential')
    }

    return report

def main():
    """Main function to run the report builder script."""
    parser = argparse.ArgumentParser(
        description="Builds a structured JSON report from scraper outputs in a specified directory."
    )
    parser.add_argument(
        "--input-dir", 
        required=True, 
        help="Path to the directory containing the scraper output JSON files (e.g., ./runs/20251113_165307/)"
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to save the final, structured report JSON file (e.g., ./runs/20251113_165_report.json)"
    )
    args = parser.parse_args()

    # 1. Validate the input directory
    # --- FIX APPLIED HERE ---
    if not os.path.isdir(args.input_dir):
        print(f"FATAL ERROR: The provided path '{args.input_dir}' is not a valid directory.")
        sys.exit(1)

    # 2. Define expected filenames and construct full paths
    required_files = {
        "trademap": "trademap_output.json",
        "macmap": "macmap_output.json",
        "eping": "eping_output.json",
        "export_potential": "export_potential_output.json"
    }
    # --- FIX APPLIED HERE ---
    filepaths = {key: os.path.join(args.input_dir, fname) for key, fname in required_files.items()}

    # 3. Load all data sources
    loaded_data = {}
    for key, path in filepaths.items():
        data = load_json_file(path)
        if data is None:
            sys.exit(1)
        loaded_data[key] = data

    # 4. Populate the fields and build the final report dictionary
    final_report_data = populate_template_fields(**loaded_data)

    # 5. Write the final report to the specified output file
    try:
        with open(args.output, 'w', encoding='utf-8') as f:
            json.dump(final_report_data, f, ensure_ascii=False, indent=4)
        print(f"\nSUCCESS: Report data has been written to '{args.output}'")
    except IOError as e:
        print(f"FATAL ERROR: Could not write the final report to '{args.output}'. Reason: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()