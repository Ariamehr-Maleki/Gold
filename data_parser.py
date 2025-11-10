# data_parser.py

import pandas as pd
import re
import os
import math
from spider_core import logging

# This function remains the same as the previous version
def _parse_timeseries_txt(file_path, config):
    logging.info(f"Parsing Time Series data from TXT file: {os.path.basename(file_path)}")
    try:
        df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig')
        df.columns = [col.strip().strip('"') for col in df.columns]
        df = df.apply(lambda x: x.str.strip().str.strip('"') if x.dtype == "object" else x)

        data_source_col = df.columns[0]

        value_cols = [col for col in df.columns if re.search(r'value in \d{4}', col.lower())]
        qty_cols = [col for col in df.columns if re.search(r'quantity in \d{4}', col.lower()) or re.search(r'qty in \d{4}', col.lower())]
        uv_cols = [col for col in df.columns if re.search(r'unit value in \d{4}', col.lower())]

        if not value_cols:
            value_cols = [col for col in df.columns if 'value in' in col.lower() or col.lower().endswith('value')]
        
        for col in value_cols + qty_cols + uv_cols:
            df[col] = pd.to_numeric(df[col], errors='coerce')
        df.fillna(0, inplace=True)

        def year_from_col(col):
            m = re.search(r'(\d{4})', col)
            return int(m.group(1)) if m else None

        years = sorted([year for c in (value_cols or qty_cols) if (year := year_from_col(c))])
        latest_year, start_year = (years[-1], years[0]) if years else (None, None)
        periods = (latest_year - start_year) if latest_year and start_year and (latest_year - start_year) > 0 else 1

        def col_for_year(prefix_cols, y):
            return next((c for c in prefix_cols if str(y) in c), None)

        data = {'years': years, 'latest_year': latest_year, 'start_year': start_year, 'periods': periods, 'raw_file': os.path.basename(file_path)}
        
        def safe_cagr(end, start, n):
            if start is None or end is None or start <= 0 or n <= 0: return 0.0
            return round(((end / start) ** (1 / n) - 1) * 100, 2)
        
        world_row = df[df[data_source_col].astype(str).str.lower() == 'world']
        if not world_row.empty and years:
            world_values = [int(world_row[vc].iloc[0]) if (vc := col_for_year(value_cols, y)) else 0 for y in years]
            world_quantities = [int(world_row[qc].iloc[0]) if qty_cols and (qc := col_for_year(qty_cols, y)) else None for y in years]
            world_unit_values = [float(world_row[uc].iloc[0]) if uv_cols and (uc := col_for_year(uv_cols, y)) else None for y in years]
            data.update({'world_values_usd': world_values, 'world_quantities': world_quantities, 'world_unit_values': world_unit_values})
            data['total_value_usd'] = world_values[-1] if world_values else 0
            if len(world_values) >= 2:
                last, prev = world_values[-1], world_values[-2]
                data['market_growth_last_year_pct'] = round((last - prev) / prev * 100, 2) if prev > 0 else 0.0
                data['market_growth_cagr_pct'] = safe_cagr(last, world_values[0], periods)

        suppliers = []
        try:
            comp_df = df[df[data_source_col].astype(str).str.lower() != 'world']
            latest_val_col = col_for_year(value_cols, years[-1]) if years else None
            comp_df_sorted = comp_df.sort_values(by=latest_val_col, ascending=False) if latest_val_col else comp_df
            world_total = data.get('total_value_usd') or (comp_df_sorted[latest_val_col].sum() if latest_val_col in comp_df_sorted.columns else 0)

            for i, row in comp_df_sorted.iterrows():
                name = str(row[data_source_col]).strip()
                v_latest = int(row.get(latest_val_col, 0))
                q_col, u_col = (col_for_year(qty_cols, years[-1]), col_for_year(uv_cols, years[-1])) if years else (None, None)
                q_latest = int(row[q_col]) if q_col and pd.notna(row[q_col]) else None
                u_latest = float(row[u_col]) if u_col and pd.notna(row[u_col]) else None
                cagr, last_year_growth = 0.0, 0.0
                if years and len(years) >= 2:
                    val_col_prev = col_for_year(value_cols, years[-2])
                    v_prev = row.get(val_col_prev) if val_col_prev else 0
                    if pd.notna(v_prev) and v_prev > 0:
                        last_year_growth = round((v_latest - v_prev) / v_prev * 100, 2)
                if years and periods > 0:
                    val_col_start = col_for_year(value_cols, start_year)
                    v_start = row.get(val_col_start) if val_col_start else 0
                    if pd.notna(v_start) and v_start > 0:
                        cagr = safe_cagr(v_latest, v_start, periods)
                suppliers.append({'rank': len(suppliers) + 1, 'name': name, 'value_usd': v_latest, 'market_share_pct': round((v_latest / world_total) * 100, 2) if world_total else 0.0, 'quantity_latest': q_latest, 'unit_value_latest': u_latest, 'growth_cagr_pct': cagr, 'growth_last_year_pct': last_year_growth})

            data['suppliers_full_list'] = suppliers
            data['top_suppliers_sample'] = suppliers[:20]
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
        logging.error(f"Failed parsing timeseries file: {e}")
        return {}

# *** NEW PARSING FUNCTION for World Importers List ***
def _parse_world_importers_txt(file_path, config):
    logging.info(f"Parsing World Importers data from TXT file: {os.path.basename(file_path)}")
    try:
        df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig', dtype=str).fillna('0')
        df.columns = [c.strip().strip('"') for c in df.columns]
        
        importers_col = df.columns[0]
        value_col = next((c for c in df.columns if 'value' in c.lower() and '2024' in c), df.columns[1])
        cagr_col = next((c for c in df.columns if 'annual growth' in c.lower()), None)
        
        df[value_col] = pd.to_numeric(df[value_col].str.replace(',', ''), errors='coerce').fillna(0)
        if cagr_col:
            df[cagr_col] = pd.to_numeric(df[cagr_col].str.replace(',', ''), errors='coerce').fillna(0)

        world_row = df[df[importers_col].str.lower() == 'world'].iloc[0]
        world_total_imports = world_row[value_col]
        world_import_cagr = world_row.get(cagr_col, 0.0)

        importers_df = df[df[importers_col].str.lower() != 'world'].copy()
        importers_df['rank'] = importers_df[value_col].rank(method='dense', ascending=False).astype(int)
        target_market_row = importers_df[importers_df[importers_col].str.lower() == config['target_market'].lower()]
        
        target_market_rank = int(target_market_row.iloc[0]['rank']) if not target_market_row.empty else 'Not found'

        return {
            "world_total_imports_usd": world_total_imports,
            "world_imports_growth_cagr_pct": world_import_cagr,
            "target_market_world_rank": target_market_rank
        }
    except Exception as e:
        logging.error(f"Could not parse world importers file. Error: {e}")
        return {}

# This function remains unchanged
def _parse_company_txt(file_path):
    logging.info(f"Parsing Company data from TXT file: {os.path.basename(file_path)}")
    try:
        df = pd.read_csv(file_path, sep='\t', header=0, encoding='utf-8-sig', dtype=str).fillna('')
        original_cols = list(df.columns)
        lowered = [c.strip().lower() for c in original_cols]

        def find_col(candidates):
            for cand in candidates:
                for i, c in enumerate(lowered):
                    if cand == c or cand in c or c in cand: return original_cols[i]
            return None

        name_col = find_col(['importers', 'company name', 'company', 'exporters'])
        if not name_col:
            logging.error(f"No valid company column found in {original_cols}")
            return []

        col_map = {'name': name_col, 'city': find_col(['city', 'town']), 'website': find_col(['website', 'web site']),'phone': find_col(['phone', 'tel']), 'email': find_col(['email', 'e-mail']), 'address': find_col(['address', 'addr'])}
        records = [{key: str(row.get(col, '')).strip() for key, col in col_map.items() if col} for _, row in df.iterrows()]
        return records
    except Exception as e:
        logging.error(f"Could not parse company file. Error: {e}")
        return []