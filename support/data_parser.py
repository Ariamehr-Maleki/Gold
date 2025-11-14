# data_parser.py (Corrected and Enhanced)

import pandas as pd
import re
import os
import math
from spider_core import logging
import pycountry_convert as pc

def get_continent(country_name):
    country_map = {
        "Bolivia (Plurinational State of)": "Bolivia", "Brunei Darussalam": "Brunei",
        "Iran (Islamic Republic of)": "Iran", "Korea, Republic of": "South Korea",
        "Russian Federation": "Russia", "United Kingdom": "United Kingdom",
        "United States of America": "United States", "Viet Nam": "Vietnam",
        "China, Hong Kong SAR": "Hong Kong", "State of Palestine": "Palestine",
        "Türkiye": "Turkey"
    }
    country_name = country_map.get(country_name, country_name).strip()
    try:
        country_alpha2 = pc.country_name_to_country_alpha2(country_name)
        continent_code = pc.country_alpha2_to_continent_code(country_alpha2)
        return pc.convert_continent_code_to_continent_name(continent_code)
    except Exception:
        return "Unknown"

def _add_regional_suppliers(final_data, config):
    logging.info("Classifying suppliers by region...")
    your_country_name = config.get('your_country')
    your_region = get_continent(your_country_name)
    if your_region == "Unknown":
        logging.error(f"Could not determine region for '{your_country_name}'.")
        final_data["regional_suppliers"] = []
        return final_data
    
    regional_suppliers = []
    full_supplier_list = final_data.get('suppliers_full_list', [])
    for supplier in full_supplier_list:
        supplier_name = supplier.get('name')
        if supplier_name and get_continent(supplier_name) == your_region:
            if supplier_name.lower() != your_country_name.lower():
                regional_suppliers.append(supplier)
    final_data["regional_suppliers"] = regional_suppliers
    logging.info(f"Found {len(regional_suppliers)} other suppliers from {your_region}.")
    return final_data

def _parse_timeseries_txt(file_path, config):
    logging.info(f"Parsing Time Series data from TXT file: {os.path.basename(file_path)}")
    try:
        df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig')
        df.columns = [col.strip().strip('"') for col in df.columns]
        df = df.apply(lambda x: x.str.strip().str.strip('"') if x.dtype == "object" else x)
        data_source_col = df.columns[0]

        all_year_cols = [col for col in df.columns if re.search(r'\d{4}', col)]
        
        ### BUG FIX START ###
        # The original logic was `and 'unit' not in c.lower()`. 
        # This was too aggressive and incorrectly excluded columns from the `unit_value.txt` file, 
        # causing the parser to only see the final summary column for year 2024.
        # The fix is to be more specific and only exclude columns that contain 'unit value'.
        value_cols = [c for c in all_year_cols if 'value' in c.lower() and 'unit value' not in c.lower()]
        ### BUG FIX END ###

        qty_cols = [c for c in all_year_cols if 'quantity' in c.lower()]
        uv_cols = [c for c in all_year_cols if 'unit value' in c.lower()]
        
        # This fallback is now less likely to be needed, but remains as a safeguard.
        if not value_cols:
            value_cols = [col for col in df.columns if 'value' in col.lower()]
        
        for col in value_cols + qty_cols + uv_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.fillna(0, inplace=True)

        def year_from_col(col):
            m = re.search(r'(\d{4})', col)
            return int(m.group(1)) if m else None

        # Now, this 'years' list will be correctly populated from all 5 year columns.
        years = sorted(list(set([year for c in value_cols if (year := year_from_col(c))])))
        if not years:
             logging.error("Could not extract any years from the column headers. Aborting parse.")
             return {}
        
        latest_year, start_year = years[-1], years[0]
        periods = (latest_year - start_year) if (latest_year - start_year) > 0 else 1

        def col_for_year(prefix_cols, y):
            return next((c for c in prefix_cols if str(y) in c), None)

        data = {'years': years, 'latest_year': latest_year, 'start_year': start_year, 'periods': periods, 'raw_file': os.path.basename(file_path)}
        
        def safe_cagr(end, start, n):
            if start is None or end is None or start <= 0 or n <= 0: return 0.0
            return round(((end / start) ** (1 / n) - 1) * 100, 2)
        
        world_row = df[df[data_source_col].astype(str).str.lower() == 'world']
        if not world_row.empty:
            world_values = [int(world_row[vc].iloc[0]) if (vc := col_for_year(value_cols, y)) is not None and vc in world_row.columns else 0 for y in years]
            world_quantities = [int(world_row[qc].iloc[0]) if qty_cols and (qc := col_for_year(qty_cols, y)) is not None and qc in world_row.columns else None for y in years]
            world_unit_values = [float(world_row[uc].iloc[0]) if uv_cols and (uc := col_for_year(uv_cols, y)) is not None and uc in world_row.columns else None for y in years]
            
            data.update({
                'world_values_usd': world_values, 
                'world_quantities': world_quantities, 
                'world_unit_values': world_unit_values
            })
            
            if world_values:
                data['total_value_usd'] = world_values[-1]
                if len(world_values) >= 2:
                    last, prev = world_values[-1], world_values[-2]
                    data['market_growth_last_year_pct'] = round((last - prev) / prev * 100, 2) if prev > 0 else 0.0
                    data['market_growth_cagr_pct'] = safe_cagr(last, world_values[0], periods)

        suppliers = []
        try:
            comp_df = df[df[data_source_col].astype(str).str.lower() != 'world']
            latest_val_col = col_for_year(value_cols, latest_year)
            start_val_col = col_for_year(value_cols, start_year)
            
            comp_df_sorted = comp_df.sort_values(by=latest_val_col, ascending=False) if latest_val_col in comp_df.columns else comp_df
            world_total = data.get('total_value_usd') or (comp_df_sorted[latest_val_col].sum() if latest_val_col in comp_df_sorted.columns else 0)

            for i, row in comp_df_sorted.iterrows():
                name = str(row[data_source_col]).strip()
                v_latest = int(row.get(latest_val_col, 0))
                
                share_latest = round((v_latest / world_total) * 100, 2) if world_total else 0.0
                
                v_start = row.get(start_val_col, 0) if start_val_col in row else 0
                world_start_total = data['world_values_usd'][0] if data.get('world_values_usd') else 0
                share_start = round((v_start / world_start_total) * 100, 2) if world_start_total > 0 else 0.0
                gained_share = share_latest > share_start

                q_col, u_col = (col_for_year(qty_cols, latest_year), col_for_year(uv_cols, latest_year))
                q_latest = int(row[q_col]) if q_col and q_col in row and pd.notna(row[q_col]) else None
                u_latest = float(row[u_col]) if u_col and u_col in row and pd.notna(row[u_col]) else None
                cagr, last_year_growth = 0.0, 0.0

                if len(years) >= 2:
                    val_col_prev = col_for_year(value_cols, years[-2])
                    v_prev = row.get(val_col_prev) if val_col_prev else 0
                    if pd.notna(v_prev) and v_prev > 0:
                        last_year_growth = round((v_latest - v_prev) / v_prev * 100, 2)
                
                if pd.notna(v_start) and v_start > 0:
                    cagr = safe_cagr(v_latest, v_start, periods)

                suppliers.append({
                    'rank': len(suppliers) + 1, 'name': name, 'value_usd': v_latest, 
                    'market_share_pct': share_latest, 'gained_share_over_5_years': gained_share,
                    'quantity_latest': q_latest, 'unit_value_latest': u_latest, 
                    'growth_cagr_pct': cagr, 'growth_last_year_pct': last_year_growth
                })

            data['suppliers_full_list'] = suppliers
            data['top_suppliers_sample'] = suppliers[:20]
            data['suppliers_gaining_share'] = [s['name'] for s in suppliers[:10] if s['gained_share_over_5_years']]
            
            hhi = sum(s['market_share_pct'] ** 2 for s in suppliers[:50])
            data['hhi'] = round(hhi, 2)
            data['concentration'] = 'not concentrated' if hhi < 1500 else 'moderately concentrated' if hhi < 2500 else 'concentrated'
            
            if found := next((s for s in suppliers if s['name'].lower() == config['your_country'].lower()), None):
                data.update(found)
        except Exception as e:
            logging.debug(f"Could not compute detailed supplier list: {e}")
        logging.info("Successfully parsed Time Series data.")
        return data
    except Exception as e:
        logging.error(f"Failed parsing timeseries file: {e}", exc_info=True)
        return {}


def _merge_supplementary_data(base_data, file_path, data_type='quantity'):
    logging.info(f"Merging '{data_type}' data from {os.path.basename(file_path)}")
    try:
        df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig', dtype=str).fillna('0')
        df.columns = [c.strip().strip('"') for c in df.columns]
        partner_col = df.columns[0]
        
        year_cols = [c for c in df.columns if re.search(r'\d{4}', c)]
        for col in year_cols:
            df[col] = pd.to_numeric(df[col].str.replace(',', '').str.strip(), errors='coerce').fillna(0)

        world_row = df[df[partner_col].str.lower() == 'world']
        if not world_row.empty:
            for i, year in enumerate(base_data.get('years', [])):
                year_col = next((c for c in year_cols if str(year) in c), None)
                if year_col:
                    world_value = world_row.iloc[0].get(year_col, 0)
                    if data_type == 'quantity' and 'world_quantities' in base_data and i < len(base_data['world_quantities']):
                        base_data['world_quantities'][i] = int(world_value) if pd.notna(world_value) else None
                    elif data_type == 'unit_value' and 'world_unit_values' in base_data and i < len(base_data['world_unit_values']):
                        base_data['world_unit_values'][i] = float(world_value) if pd.notna(world_value) else None

        latest_year = base_data.get('latest_year')
        if not latest_year: return
        
        target_col_name = next((c for c in df.columns if str(latest_year) in c), None)
        if not target_col_name: return

        suppliers_map = {s['name'].lower(): s for s in base_data['suppliers_full_list']}
        
        for _, row in df[df[partner_col].str.lower() != 'world'].iterrows():
            partner_name = str(row[partner_col]).strip()
            if partner_name.lower() in suppliers_map:
                target_partner = suppliers_map[partner_name.lower()]
                value = row[target_col_name]
                if data_type == 'quantity': 
                    target_partner['quantity_latest'] = int(value) if pd.notna(value) else None
                elif data_type == 'unit_value': 
                    target_partner['unit_value_latest'] = float(value) if pd.notna(value) else None
    except Exception as e:
        logging.error(f"Failed to merge supplementary data from {file_path}. Error: {e}")
        
def parse_full_timeseries(value_file, quantity_file, unit_value_file, config):
    logging.info("--- Starting full timeseries parsing and merging from 3 files ---")
    if not value_file or not os.path.exists(value_file):
        logging.error(f"Value file not found: {value_file}. Aborting parse.")
        return {}
    final_data = _parse_timeseries_txt(value_file, config)
    if not final_data or 'suppliers_full_list' not in final_data:
        logging.warning("Parsing the primary value file did not yield a full dataset. Merging supplementary data may be incomplete.")
        if not final_data: final_data = {}

    if quantity_file and os.path.exists(quantity_file):
        _merge_supplementary_data(final_data, quantity_file, data_type='quantity')
    if unit_value_file and os.path.exists(unit_value_file):
        _merge_supplementary_data(final_data, unit_value_file, data_type='unit_value')
    for supplier in final_data.get('suppliers_full_list', []):
        value = supplier.get('value_usd')
        quantity = supplier.get('quantity_latest')
        if supplier.get('unit_value_latest') is None and value and quantity and quantity > 0:
            supplier['unit_value_latest'] = round((value * 1000) / quantity, 2)
    
    if any(s['name'].lower() != 'world' for s in final_data.get('suppliers_full_list', [])):
        final_data = _add_regional_suppliers(final_data, config)

    logging.info("Successfully merged all timeseries data.")
    return final_data

def parse_world_importers_txt(file_path, config):
    logging.info(f"Parsing World Importers data from TXT file: {os.path.basename(file_path)}")
    try:
        df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig', dtype=str).fillna('0')
        df.columns = [c.strip().strip('"') for c in df.columns]
        importers_col = df.columns[0]

        year_cols = [c for c in df.columns if re.search(r'\d{4}', c)]
        if not year_cols: return {}
        years = sorted([int(re.search(r'(\d{4})', c).group(1)) for c in year_cols])
        latest_year = years[-1]
        value_col = next(c for c in year_cols if str(latest_year) in c and 'value' in c.lower())
        
        df[value_col] = pd.to_numeric(df[value_col].str.replace(',', ''), errors='coerce').fillna(0)

        world_row = df[df[importers_col].str.lower() == 'world'].iloc[0]
        world_total_imports = world_row[value_col]
        
        importers_df = df[df[importers_col].str.lower() != 'world'].copy()
        importers_df['rank'] = importers_df[value_col].rank(method='dense', ascending=False).astype(int)
        
        target_market_row = importers_df[importers_df[importers_col].str.lower() == config['target_market'].lower()]
        
        if not target_market_row.empty:
            target_market_rank = int(target_market_row.iloc[0]['rank'])
        else:
            target_market_rank = 'Not found in top importers'

        return {
            "world_total_imports_usd": int(world_total_imports),
            "target_market_world_rank": target_market_rank
        }
    except Exception as e:
        logging.error(f"Could not parse world importers file. Error: {e}", exc_info=True)
        return {}

def parse_company_txt(file_path):
    logging.info(f"Parsing Company data from TXT file: {os.path.basename(file_path)}")
    if not file_path or not os.path.exists(file_path):
        logging.warning("Company file path not provided or file does not exist.")
        return []
    try:
        df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig', dtype=str).fillna('')
        original_cols, lowered = list(df.columns), [c.strip().lower() for c in list(df.columns)]
        def find_col(candidates):
            for cand in candidates:
                for i, c in enumerate(lowered):
                    if cand == c or cand in c or c in cand: return original_cols[i]
            return None
        name_col = find_col(['importers', 'company name', 'company', 'exporters'])
        if not name_col: return []
        col_map = {'name': name_col, 'city': find_col(['city', 'town']), 'website': find_col(['website', 'web site']),'phone': find_col(['phone', 'tel']), 'email': find_col(['email', 'e-mail']), 'address': find_col(['address', 'addr'])}
        records = [{key: str(row.get(col, '')).strip() for key, col in col_map.items() if col} for _, row in df.iterrows()]
        return records
    except Exception as e:
        logging.error(f"Could not parse company file. Error: {e}")
        return []