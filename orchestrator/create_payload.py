# orchestrator/create_payload.py (Final Version)

import json
import argparse
from datetime import datetime

def create_factsheet_payload(final_report_path: str, output_path: str):
    """
    Reads the final_report.json and generates a flat JSON payload with unique, 
    unambiguous placeholders for direct document replacement.
    """
    try:
        with open(final_report_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        print(f"FATAL: Could not read or parse '{final_report_path}'. {e}")
        return

    # ===== 1. EXTRACT DATA WITH SAFE DEFAULTS =====
    meta = data.get('meta', {})
    summary = data.get('summary', {})
    market_data = data.get('market_size_and_growth', {})
    competition = data.get('competition_and_suppliers', {})
    unit_values_data = data.get('unit_values', {})
    historical = data.get('historical_data', {})

    # Base Info
    exporting_country = meta.get('exporting_country', 'N/A')
    importing_country = meta.get('importing_country', 'N/A')
    hs_code = meta.get('product_hs6', 'N/A')
    product_name = f"Portable digital machines (HS {hs_code})"
    years = historical.get('years', [])
    latest_year = years[-1] if years else datetime.now().year - 1

    # Key Figures
    total_exports_yc_world = summary.get('your_country_total_exports_usd', 0)
    target_market_rank = summary.get('target_market_world_rank', 'N/A')
    target_market_imports = market_data.get('target_market_total_imports_usd', 0)
    world_total_imports = market_data.get('world_total_imports_usd', 0)

    # Supplier & Competition Info
    all_suppliers = competition.get('all_suppliers', [])
    your_country_data = next((s for s in all_suppliers if s.get('name') == exporting_country), {})
    your_country_imports_value = your_country_data.get('value_usd', 0)
    your_country_market_share = your_country_data.get('market_share_pct', 0)
    
    top_3_suppliers = all_suppliers[:3]
    s1 = top_3_suppliers[0] if len(top_3_suppliers) > 0 else {}
    s2 = top_3_suppliers[1] if len(top_3_suppliers) > 1 else {}
    s3 = top_3_suppliers[2] if len(top_3_suppliers) > 2 else {}

    # Growth Info
    market_cagr = market_data.get('target_market_growth_cagr_5y_pct', 0.0) or 0.0
    world_cagr = market_data.get('world_market_growth_cagr_5y_pct', 0.0) or 0.0
    market_last_year_growth = market_data.get('target_market_growth_last_year_pct', 0.0) or 0.0
    your_country_cagr = your_country_data.get('growth_cagr_pct', 0.0) or 0.0

    # Unit Value Info (Correctly accessing the lists)
    tm_unit_values = data.get('market_analysis',{}).get('world_unit_values',[]) # This is misnamed in parser but is the TM value
    tm_unit_value = tm_unit_values[-1] if tm_unit_values and tm_unit_values[-1] is not None else 0

    world_unit_value = unit_values_data.get('world_avg_unit_value_usd') or 0
    yc_unit_value = your_country_data.get('unit_value_latest') or 0
    
    # ===== 2. PERFORM CALCULATIONS AND LOGIC =====
    tm_world_share = round((target_market_imports / world_total_imports) * 100, 2) if world_total_imports else 0
    market_vs_world_growth = "better than" if market_cagr > world_cagr else "worse than"
    market_share_trend = "increasing" if market_cagr > world_cagr else "decreasing"
    is_sustained = "sustained" if abs(market_last_year_growth) >= abs(market_cagr) else "not sustained"
    last_year_trend = "growing" if market_last_year_growth >= 0 else "contracting"
    yc_share_change = "gained" if your_country_cagr > market_cagr else "lost"
    tm_vs_world_unit_value = "more than" if tm_unit_value > world_unit_value else "less than"
    yc_vs_tm_unit_value = "higher" if yc_unit_value > tm_unit_value else "lower"
    
    # ===== 3. BUILD THE FINAL PAYLOAD DICTIONARY =====
    payload = {
        # Introduction
        '[Product]': product_name,
        '[Target Market]': importing_country,
        '[Month Year]': datetime.now().strftime("%B %Y"),
        '[00.00.00]': str(hs_code),
        '[Your Country]': exporting_country,
        '[Name of Country]': importing_country,

        # Summary Box
        '[yc_total_exports_world_usd]': f"USD {total_exports_yc_world:,.0f}",
        '[latest_year_for_exports]': str(latest_year),
        '[rank]': str(target_market_rank),
        
        # Size of the Market
        '[latest_year]': str(latest_year),
        '[tm_imports_from_world_value]': f"USD {target_market_imports:,.0f}",
        '[tm_world_share_pct]': f"{tm_world_share}",
        '[tm_imports_from_yc_value]': f"USD {your_country_imports_value:,.0f}",
        '[yc_market_share_pct]': f"{your_country_market_share}",

        # Growth of the Market
        '[tm_cagr]': f"{market_cagr}",
        '[market_vs_world_growth]': market_vs_world_growth,
        '[world_cagr]': f"{world_cagr}",
        '[market_share_trend]': market_share_trend,
        '[period]': f"{latest_year - 1}-{latest_year}",
        '[is_sustained]': is_sustained,
        '[last_year_trend]': last_year_trend,
        '[tm_last_year_growth_pct]': f"{market_last_year_growth}",
        '[yc_cagr]': f"{your_country_cagr}",
        '[yc_share_change]': yc_share_change,
        
        # Unit Value Section
        '[tm_avg_unit_value]': f"{tm_unit_value:,.2f}",
        '[tm_vs_world_unit_value]': tm_vs_world_unit_value,
        '[world_avg_unit_value]': f"{world_unit_value:,.2f}",
        '[yc_unit_value]': f"{yc_unit_value:,.2f}",
        '[yc_vs_tm_unit_value]': yc_vs_tm_unit_value,
        # Unit value trends are not yet calculated, leaving placeholders
        
        # Competition
        '[concentration]': competition.get('concentration_level', 'N/A'),
        '[supplier 1]': s1.get('name', 'N/A'),
        '[supplier 2]': s2.get('name', 'N/A'),
        '[supplier 3]': s3.get('name', 'N/A'),
        '[s1_share]': str(s1.get('market_share_pct', 0)),
        '[s2_share]': str(s2.get('market_share_pct', 0)),
        '[s3_share]': str(s3.get('market_share_pct', 0)),
        '[suppliers_gaining_share]': "; ".join(competition.get('suppliers_gaining_share', []) or ["None"]),
        '[your_region]': "your region",
        '[regional_competitors]': "; ".join([s['name'] for s in competition.get('regional_competitors', [])] or ["None"]),
    }

    # Save the payload
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=4, ensure_ascii=False)
    
    print(f"SUCCESS: Created factsheet payload at '{output_path}'")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(description="Create a flat JSON payload for the factsheet generator.")
    parser.add_argument("--input", required=True, help="Path to final_report.json")
    parser.add_argument("--output", required=True, help="Path to save payload.json")
    args = parser.parse_args()
    create_factsheet_payload(args.input, args.output)