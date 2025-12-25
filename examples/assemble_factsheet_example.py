"""
Example: How to use the Factsheet Assembler

This shows the complete flow:
1. Parse 3 Excel snapshots using the existing parser
2. Load config
3. Build populated Factsheet JSON
4. Save output
"""

import json
import os
from support.data_parser import parse_snapshot_excel
from support.factsheet_assembler import build_quantitative_export_factsheet


def assemble_factsheet_from_downloads(
    downloads_dir: str,
    config_dict: dict,
    output_file: str
) -> dict:
    """
    End-to-end: download → parse → assemble → output.
    
    Args:
        downloads_dir: Directory containing the 3 Excel files:
            - world_snapshot.xls
            - target_country.xls
            - your_country_exports.xls
        config_dict: dict with keys:
            - your_country
            - target_market
            - product_name
            - hs_code
            - year
        output_file: Path to write the JSON
        
    Returns:
        The populated Factsheet JSON dict
    """
    
    # Step 1: Parse the 3 Excel files
    print("📊 Parsing snapshots...")
    
    world_file = os.path.join(downloads_dir, "world_snapshot.xls")
    target_file = os.path.join(downloads_dir, "target_country.xls")
    your_file = os.path.join(downloads_dir, "your_country_exports.xls")
    
    world_data = parse_snapshot_excel(world_file)
    target_data = parse_snapshot_excel(target_file)
    your_country_data = parse_snapshot_excel(your_file)
    
    print(f"  ✓ World data: {len(world_data)} entries")
    print(f"  ✓ Target market data: {len(target_data)} entries")
    print(f"  ✓ Your country data: {len(your_country_data)} entries")
    
    # Step 2: Build Factsheet
    print("\n🔧 Building Factsheet...")
    factsheet = build_quantitative_export_factsheet(
        config=config_dict,
        world_data=world_data,
        target_data=target_data,
        your_country_data=your_country_data
    )
    
    # Step 3: Save
    print(f"\n💾 Saving to {output_file}...")
    os.makedirs(os.path.dirname(output_file), exist_ok=True)
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(factsheet, f, indent=2, ensure_ascii=False)
    
    print("✅ Done!")
    return factsheet


# =============================================================================
# EXAMPLE USAGE
# =============================================================================

if __name__ == "__main__":
    
    # Your configuration
    config = {
        "your_country": "Italy",
        "target_market": "Germany",
        "product_name": "Pasta",
        "hs_code": "190210",
        "year": "2024"
    }
    
    # Run the pipeline
    factsheet = assemble_factsheet_from_downloads(
        downloads_dir="test/test68",  # ← Output from trademap_scraper
        config_dict=config,
        output_file="output_factsheets/pasta_to_germany.json"
    )
    
    # Pretty-print the result (first section only)
    print("\n📄 Sample output (Header section):")
    print(json.dumps(
        factsheet["Quantitative_Export_Factsheet"]["Header"],
        indent=2
    ))
