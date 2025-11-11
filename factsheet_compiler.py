# factsheet_compiler.py

import os
import glob
import json
from datetime import datetime

# IMPORTANT: We are reusing the parsing logic from the existing files
from data_parser import parse_full_timeseries, parse_company_txt
from main import enrich_factsheet_metrics

# --- Configuration ---
# This must match the config used during the scrape to find the correct files.
CONFIG = {
    "product_name": "Electric motors of an output not exceeding 37.5 W",
    "hs_code": "850110",
    "your_country": "South Africa", "your_country_id": "710",
    "target_market": "Germany", "target_market_id": "276",
}

ARCHIVE_DIR = os.path.join(os.getcwd(), "archived_downloads")


def find_latest_archived_files(archive_dir, config):
    """Finds the most recent complete set of archived files for a scraping run."""
    print(f"Scanning for archived files in: {archive_dir}")
    all_files = glob.glob(os.path.join(archive_dir, "*.txt"))
    if not all_files:
        print("No archived files found.")
        return None

    # Extract timestamps (the first part of the filename)
    timestamps = sorted(list(set([os.path.basename(f).split('_')[0] for f in all_files])), reverse=True)
    latest_timestamp = timestamps[0]
    print(f"Found latest timestamp: {latest_timestamp}")

    latest_files = [f for f in all_files if os.path.basename(f).startswith(latest_timestamp)]

    # Map the files to their expected roles based on the naming convention from main.py
    file_map = {
        "world_market_overview_value": next((f for f in latest_files if "world_value.txt" in f), None),
        "world_market_overview_quantity": next((f for f in latest_files if "world_quantity.txt" in f), None),
        "world_market_overview_unit_value": next((f for f in latest_files if "world_unit_value.txt" in f), None),
        "target_market_imports_value": next((f for f in latest_files if "target_market_imports_value.txt" in f), None),
        "target_market_imports_quantity": next((f for f in latest_files if "target_market_imports_quantity.txt" in f), None),
        "target_market_imports_unit_value": next((f for f in latest_files if "target_market_imports_unit_value.txt" in f), None),
        "your_country_exports_value": next((f for f in latest_files if "your_country_exports_value.txt" in f), None),
        "your_country_exports_quantity": next((f for f in latest_files if "your_country_exports_quantity.txt" in f), None),
        "your_country_exports_unit_value": next((f for f in latest_files if "your_country_exports_unit_value.txt" in f), None),
        "company_sample": next((f for f in latest_files if "company_sample.txt" in f), None),
    }

    # Verify that the essential files were found
    if not file_map["target_market_imports_value"]:
        print("Error: Could not find the essential 'target_market_imports_value.txt' file for the latest run.")
        return None

    print("Successfully identified latest set of archived files.")
    return file_map


def compile_factsheet_data(parsed_data, config):
    """
    Takes the parsed data and structures it into a dictionary that maps directly
    to the fields in the Quantitative Export Factsheet template.
    """
    print("Compiling data into factsheet format...")
    
    # Extracting the main data blocks for easier access
    world_overview = parsed_data.get('world_market_overview', {})
    target_market = parsed_data.get('target_market_analysis', {})
    your_country_exports = parsed_data.get('your_country_global_exports', {})
    metrics = parsed_data.get('factsheet_metrics', {})
    
    your_country_in_target_market = next((s for s in target_market.get('suppliers_full_list', [])
                                         if s.get('name', '').lower() == config['your_country'].lower()), {})

    factsheet = {
        "header": {
            "product": config['product_name'],
            "hs_code": config['hs_code'],
            "target_market": config['target_market'],
            "your_country": config['your_country'],
            "date": datetime.now().strftime("%B %Y"),
            "latest_year": target_market.get('latest_year', 'N/A')
        },
        "opportunity_summary": {
            "your_country_total_exports_to_world_usd": your_country_exports.get('total_exports_to_world_usd'),
            "target_market_world_rank_for_imports": metrics.get('target_market_rank_in_world_imports'),
            # Data not available from current scraper, must be found manually
            "target_market_capital_city": "[Manual Entry Required]",
            "target_market_population": "[Manual Entry Required]",
            "target_market_gdp_per_capita": "[Manual Entry Required]",
        },
        "size_of_market": {
            "target_market_total_imports_from_world_usd": metrics.get('target_market_total_imports_usd'),
            "target_market_share_of_world_imports_pct": round((metrics.get('target_market_total_imports_usd', 0) / world_overview.get('total_value_usd', 1)) * 100, 2) if world_overview.get('total_value_usd') else 0,
            "target_market_imports_from_your_country_usd": metrics.get('target_market_imports_from_your_country_usd'),
            "your_country_share_of_target_market_imports_pct": metrics.get('your_country_share_of_target_imports_pct'),
        },
        "growth_of_market": {
            "target_market_imports_from_world_cagr_pct": target_market.get('market_growth_cagr_pct'),
            "world_imports_cagr_pct": world_overview.get('market_growth_cagr_pct'),
            "target_market_imports_last_year_growth_pct": target_market.get('market_growth_last_year_pct'),
            "target_market_imports_from_your_country_cagr_pct": your_country_in_target_market.get('growth_cagr_pct'),
            "line_graph_data_usd": {
                "years": target_market.get('years', []),
                "values": target_market.get('world_values_usd', [])
            }
        },
        "unit_value": {
            "target_market_avg_unit_value": metrics.get('target_market_unit_value_latest'),
            "world_avg_unit_value": metrics.get('world_unit_value_latest'),
            "your_country_unit_value_in_target_market": metrics.get('your_country_unit_value_latest'),
            # GAPS: The current parser does not extract historical unit value data
            "historical_trends": "[Parser Modification Required]",
            "top_suppliers_unit_values": [
                {"name": s.get('name'), "unit_value": s.get('unit_value_latest')}
                for s in target_market.get('top_suppliers_sample', [])[:10]
            ]
        },
        "competition": {
            "concentration_level": metrics.get('concentration'),
            "hhi_index": metrics.get('hhi'),
            "top_5_suppliers": metrics.get('top_suppliers_top5', []),
            "regional_suppliers": target_market.get('regional_suppliers', []),
            # GAP: The current parser does not calculate historical market share changes
            "suppliers_with_gaining_share": "[Parser Modification Required]"
        },
        "market_access": {
            "tariffs_and_agreements": "[Major Scraper Expansion Required - e.g., scrape macmap.org]",
            "non_tariff_measures": "[Major Scraper Expansion Required - e.g., scrape macmap.org]",
            "potential_new_ntms": "[Major Scraper Expansion Required - e.g., scrape epingalert.org]",
        },
        "business_partners": parsed_data.get('business_partners_sample', []),
        "other_markets": {
            "analysis": "[Major Scraper Expansion Required - e.g., scrape exportpotential.intracen.org]"
        }
    }
    return factsheet


if __name__ == '__main__':
    # 1. Find the latest set of archived files
    archived_files = find_latest_archived_files(ARCHIVE_DIR, CONFIG)

    if archived_files:
        # 2. Parse the data from the files using existing functions
        print("\n--- Parsing Data from Archived Files ---")
        
        world_data = parse_full_timeseries(
            value_file=archived_files.get('world_market_overview_value'),
            quantity_file=archived_files.get('world_market_overview_quantity'),
            unit_value_file=archived_files.get('world_market_overview_unit_value'),
            config=CONFIG
        )
        
        target_market_data = parse_full_timeseries(
            value_file=archived_files.get('target_market_imports_value'),
            quantity_file=archived_files.get('target_market_imports_quantity'),
            unit_value_file=archived_files.get('target_market_imports_unit_value'),
            config=CONFIG
        )
        
        export_data = parse_full_timeseries(
            value_file=archived_files.get('your_country_exports_value'),
            quantity_file=archived_files.get('your_country_exports_quantity'),
            unit_value_file=archived_files.get('your_country_exports_unit_value'),
            config=CONFIG
        )
        
        company_data = []
        if archived_files.get('company_sample'):
            company_data = parse_company_txt(archived_files.get('company_sample'))

        # 3. Aggregate and enrich the data (same as in main.py)
        final_data = {
            "header": {**CONFIG, "date": datetime.now().strftime("%B %Y")},
            "world_market_overview": world_data,
            "target_market_analysis": target_market_data,
            "your_country_global_exports": {"total_exports_to_world_usd": export_data.get("total_value_usd")},
            "business_partners_sample": company_data
        }
        final_data = enrich_factsheet_metrics(final_data, CONFIG)

        # 4. Compile the final factsheet-oriented dictionary
        factsheet_output = compile_factsheet_data(final_data, CONFIG)
        
        # 5. Save the new, structured JSON
        output_filename = "factsheet_template_data.json"
        with open(output_filename, 'w', encoding='utf-8') as f:
            json.dump(factsheet_output, f, ensure_ascii=False, indent=4)
        
        print(f"\nSUCCESS: Compiled data has been saved to '{output_filename}'")
        print("This file is now structured to help you fill out the template.")