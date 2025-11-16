"""
Robust Time Series Parser for ITC-style TXT exports
- Parses value / quantity / unit value TSVs with flexible column names
- Normalises column names and maps year -> (value, quantity, unit_value)
- Merges the three files into a single data structure
- Exports CSVs: parsed raw tables, suppliers list, world timeseries, merged summary

Usage (example):
    from data_parser import parse_full_timeseries
    cfg = {'your_country': 'Iran', 'target_market': 'United States of America'}
    out = parse_full_timeseries('value.txt', 'quantity.txt', 'unit_value.txt', cfg, out_dir='./output')

This file intentionally logs liberally (uses spider_core.logging) and is defensive about missing columns.
"""

import os
import re
import math
from typing import Dict, List, Optional, Tuple

import pandas as pd

from support.spider_core import logging
import pycountry_convert as pc

# ----------------------------- Helpers ----------------------------------

def _clean_col(col: str) -> str:
    if col is None:
        return ""
    c = str(col).strip().strip('"').strip()
    # normalize spacing
    c = re.sub(r"\s+", " ", c)
    return c


def _norm(col: str) -> str:
    """Normalized lowered version used for classification."""
    c = _clean_col(col).lower()
    c = re.sub(r"[^a-z0-9 ]", " ", c)
    c = re.sub(r"\s+", " ", c).strip()
    return c


def _extract_year(col: str) -> Optional[int]:
    m = re.search(r"(19|20)\d{2}", str(col))
    return int(m.group(0)) if m else None


def _to_num(x):
    if pd.isna(x):
        return None
    s = str(x).strip()
    if s == '' or s.lower() in ['no quantity', 'no data', 'na', 'n/a', 'no quantity ']:
        return None
    # remove commas and non-number characters except dot and minus
    s = re.sub(r"[^0-9\.\-]", "", s)
    try:
        if '.' in s:
            return float(s)
        return int(s)
    except Exception:
        try:
            return float(s)
        except Exception:
            return None


def get_continent(country_name: str) -> str:
    country_map = {
        "Bolivia (Plurinational State of)": "Bolivia",
        "Brunei Darussalam": "Brunei",
        "Iran (Islamic Republic of)": "Iran",
        "Korea, Republic of": "South Korea",
        "Russian Federation": "Russia",
        "United Kingdom": "United Kingdom",
        "United States of America": "United States",
        "Viet Nam": "Vietnam",
        "China, Hong Kong SAR": "Hong Kong",
        "State of Palestine": "Palestine",
        "Türkiye": "Turkey",
    }
    try:
        if not country_name:
            return "Unknown"
        country = country_map.get(country_name, country_name).strip()
        alpha2 = pc.country_name_to_country_alpha2(country)
        code = pc.country_alpha2_to_continent_code(alpha2)
        return pc.convert_continent_code_to_continent_name(code)
    except Exception:
        return "Unknown"

# ----------------------------- Parsing primitives -----------------------

def _read_tsv(path: str) -> pd.DataFrame:
    return pd.read_csv(path, sep='\t', header=0, encoding='utf-8-sig', dtype=str).fillna('')


def _normalize_df_columns(df: pd.DataFrame) -> pd.DataFrame:
    new_cols = [_clean_col(c) for c in df.columns]
    df.columns = new_cols
    return df


def _build_year_column_map(columns: List[str]) -> Dict[int, Dict[str, List[str]]]:
    """Return map: year -> { 'value': [cols], 'quantity': [cols], 'unit_value': [cols], 'unit_label': [cols] }
    We allow lists because some files use multiple columns per year (e.g. quantity + unit label).
    """
    out: Dict[int, Dict[str, List[str]]] = {}
    for col in columns:
        year = _extract_year(col)
        if not year:
            continue
        norm = _norm(col)
        entry = out.setdefault(year, {'value': [], 'quantity': [], 'unit_value': [], 'unit_label': []})
        # classification heuristics
        if 'unit value' in norm or 'imported unit value' in norm or 'unit value' in col.lower():
            entry['unit_value'].append(col)
        elif 'quantity' in norm or 'imported quantity' in norm or re.search(r'\bquantity\b', norm):
            entry['quantity'].append(col)
        elif 'value' in norm or 'imported value' in norm:
            entry['value'].append(col)
        elif 'unit' in norm and not any(k in norm for k in ['unit value', 'unit/']):
            # column like '2020-Unit' that denotes the unit label for the quantity
            entry['unit_label'].append(col)
        else:
            # fallback: if 'value' appears inside the original string, put it under value
            if 'value' in col.lower():
                entry['value'].append(col)
            elif 'qty' in col.lower() or 'quant' in col.lower():
                entry['quantity'].append(col)
            # else ignore
    return out

# ----------------------------- Core parser ------------------------------

def _parse_value_df(value_df: pd.DataFrame) -> Tuple[List[int], str, Dict[int, str], pd.DataFrame]:
    """Return (years_sorted, index_col, year->value_col (single chosen), df)
    Chooses the best 'value' column for each year if multiple exist.
    """
    value_df = _normalize_df_columns(value_df.copy())
    index_col = value_df.columns[0]
    cols = list(value_df.columns)
    year_map = _build_year_column_map(cols)
    years = sorted(year_map.keys())

    year_to_value_col = {}
    for y in years:
        # prefer columns that include 'value' explicitly
        candidates = year_map[y]['value']
        if not candidates:
            # fallback: search any column containing the year and 'import' or 'usd' or 'value'
            candidates = [c for c in cols if str(y) in c and ('value' in _norm(c) or 'import' in _norm(c) or 'usd' in _norm(c))]
        if candidates:
            year_to_value_col[y] = candidates[0]

    return years, index_col, year_to_value_col, value_df


def _safe_get_row_value(row: pd.Series, col: Optional[str]) -> Optional[float]:
    if not col or col not in row.index:
        return None
    return _to_num(row[col])


def _safe_get_df_value(df: pd.DataFrame, row_sel, col: Optional[str]) -> Optional[float]:
    try:
        r = df.loc[row_sel]
        if isinstance(r, pd.Series):
            return _to_num(r.get(col, None))
        # if multiple rows returned, take first
        return _to_num(r.iloc[0].get(col, None))
    except Exception:
        return None

# ----------------------------- Merge & compute -------------------------

def parse_full_timeseries(value_file: str, quantity_file: Optional[str], unit_value_file: Optional[str], config: Dict, out_dir: Optional[str] = None) -> Dict:
    """Main entrypoint: returns a structured dict and writes helpful CSVs to out_dir (or same dir as value_file)

    config: must include 'your_country' (for regional suppliers) and optionally 'target_market'.
    """
    logging.info("=== parse_full_timeseries starting ===")
    if not value_file or not os.path.exists(value_file):
        logging.error(f"Value file missing: {value_file}")
        return {}

    if out_dir is None:
        out_dir = os.path.dirname(value_file) or '.'
    os.makedirs(out_dir, exist_ok=True)

    # Load value table
    try:
        val_df = _read_tsv(value_file)
    except Exception as e:
        logging.error(f"Failed to load value file: {e}")
        return {}

    years, index_col, year_to_value_col, val_df = _parse_value_df_wrapper(val_df)

    if not years:
        logging.error("No year columns detected in value file; aborting.")
        return {}

    latest_year = years[-1]
    start_year = years[0]
    periods = latest_year - start_year if latest_year > start_year else 1

    data = {
        'years': years,
        'latest_year': latest_year,
        'start_year': start_year,
        'periods': periods,
        'raw_file': os.path.basename(value_file)
    }

    # Convert value columns to numeric and export a parsed copy
    for y, c in year_to_value_col.items():
        val_df[c] = val_df[c].astype(str).str.replace(',', '').apply(lambda x: _to_num(x))

    parsed_csv = os.path.join(out_dir, os.path.basename(value_file).replace('.txt', '_parsed_values.csv'))
    try:
        val_df.to_csv(parsed_csv, index=False, encoding='utf-8-sig')
        logging.info(f"Saved parsed values CSV: {parsed_csv}")
    except Exception as e:
        logging.debug(f"Could not save parsed values CSV: {e}")

    # locate world row
    world_mask = val_df[index_col].astype(str).str.strip().str.lower() == 'world'
    world_values = []
    if world_mask.any():
        world_row_idx = val_df.index[world_mask][0]
        for y in years:
            col = year_to_value_col.get(y)
            world_values.append(_safe_get_df_value(val_df, world_row_idx, col) or 0)
    data['world_values_usd'] = world_values
    if world_values:
        data['total_value_usd'] = world_values[-1]
        if len(world_values) >= 2 and (prev := world_values[-2]):
            last = world_values[-1]
            data['market_growth_last_year_pct'] = round((last - prev) / prev * 100, 2) if prev != 0 else 0.0
            data['market_growth_cagr_pct'] = _safe_cagr(last, world_values[0], periods)

    # Build suppliers list
    suppliers = []
    comp_df = val_df[~world_mask].copy() if world_mask.any() else val_df.copy()
    # fill numeric on chosen value columns
    for y, c in year_to_value_col.items():
        if c in comp_df.columns:
            comp_df[c] = comp_df[c].astype(str).str.replace(',', '').apply(lambda x: _to_num(x) or 0)

    # pick latest value column name
    latest_val_col = year_to_value_col.get(latest_year)
    start_val_col = year_to_value_col.get(start_year)

    # compute world_total as world record if exists else sum of latest_val_col
    world_total = data.get('total_value_usd') or (int(comp_df[latest_val_col].sum()) if latest_val_col in comp_df.columns else 0)

    # iterate suppliers sorted by latest value
    if latest_val_col and latest_val_col in comp_df.columns:
        comp_df_sorted = comp_df.sort_values(by=latest_val_col, ascending=False)
    else:
        comp_df_sorted = comp_df

    for idx, row in comp_df_sorted.iterrows():
        name = _clean_col(row[index_col])
        v_latest = _to_num(row.get(latest_val_col)) or 0
        v_start = _to_num(row.get(start_val_col)) or 0
        share_latest = round((v_latest / world_total) * 100, 2) if world_total else 0.0
        share_start = round((v_start / (data['world_values_usd'][0] if data.get('world_values_usd') else 0)) * 100, 2) if data.get('world_values_usd') and data['world_values_usd'][0] else 0.0
        gained_share = share_latest > share_start
        last_year_growth = 0.0
        if len(years) >= 2:
            prev_col = year_to_value_col.get(years[-2])
            v_prev = _to_num(row.get(prev_col)) or 0
            if v_prev and v_prev != 0:
                last_year_growth = round((v_latest - v_prev) / v_prev * 100, 2)
        cagr = _safe_cagr(v_latest, v_start, periods) if v_start and v_start > 0 else 0.0

        suppliers.append({
            'rank': len(suppliers) + 1,
            'name': name,
            'value_usd': int(v_latest) if isinstance(v_latest, (int,)) else (float(v_latest) if v_latest else 0),
            'market_share_pct': share_latest,
            'gained_share_over_5_years': gained_share,
            'quantity_latest': None,
            'unit_value_latest': None,
            'growth_cagr_pct': cagr,
            'growth_last_year_pct': last_year_growth,
        })

    data['suppliers_full_list'] = suppliers
    data['top_suppliers_sample'] = suppliers[:20]
    data['suppliers_gaining_share'] = [s['name'] for s in suppliers if s['gained_share_over_5_years']]

    # compute HHI for top 50
    try:
        hhi = sum((s['market_share_pct'] or 0) ** 2 for s in suppliers[:50])
        data['hhi'] = round(hhi, 2)
        data['concentration'] = 'not concentrated' if hhi < 1500 else 'moderately concentrated' if hhi < 2500 else 'concentrated'
    except Exception:
        data['hhi'] = None
        data['concentration'] = 'unknown'

    # Merge quantity file (if present)
    if quantity_file and os.path.exists(quantity_file):
        try:
            qdf = _read_tsv(quantity_file)
            qdf = _normalize_df_columns(qdf)
            _merge_quantity_into(data, qdf, index_col, latest_year)
        except Exception as e:
            logging.error(f"Failed merging quantity file: {e}")

    # Merge unit value file (if present)
    if unit_value_file and os.path.exists(unit_value_file):
        try:
            udf = _read_tsv(unit_value_file)
            udf = _normalize_df_columns(udf)
            _merge_unitvalue_into(data, udf, index_col, latest_year)
        except Exception as e:
            logging.error(f"Failed merging unit value file: {e}")

    # compute unit_value from value & quantity if missing (assume value is in US$ thousand if the unit_file had such column presence)
    for s in data['suppliers_full_list']:
        if s.get('unit_value_latest') is None:
            v = s.get('value_usd')
            q = s.get('quantity_latest')
            if v and q and q > 0:
                # In many ITC exports value is in US$ thousand; if that's the case unit = (value*1000)/quantity
                s['unit_value_latest'] = round((float(v) * 1000.0) / float(q), 2)

    # add regional suppliers
    try:
        data = _add_regional_suppliers(data, config)
    except Exception as e:
        logging.debug(f"_add_regional_suppliers failed: {e}")

    # Export CSVs
    try:
        suppliers_csv = os.path.join(out_dir, os.path.basename(value_file).replace('.txt', '_suppliers.csv'))
        pd.DataFrame(data['suppliers_full_list']).to_csv(suppliers_csv, index=False, encoding='utf-8-sig')
        logging.info(f"Exported suppliers CSV: {suppliers_csv}")
    except Exception as e:
        logging.error(f"Failed writing suppliers CSV: {e}")

    try:
        world_csv = os.path.join(out_dir, os.path.basename(value_file).replace('.txt', '_world_timeseries.csv'))
        world_df = pd.DataFrame({'year': data['years'], 'value_usd': data.get('world_values_usd', [])})
        # optionally include world quantities/unit_values if present
        if 'world_quantities' in data:
            world_df['quantity'] = data['world_quantities']
        if 'world_unit_values' in data:
            world_df['unit_value'] = data['world_unit_values']
        world_df.to_csv(world_csv, index=False, encoding='utf-8-sig')
        logging.info(f"Exported world timeseries CSV: {world_csv}")
    except Exception as e:
        logging.error(f"Failed writing world CSV: {e}")

    # full merged JSON-like object returns
    logging.info("=== parse_full_timeseries finished ===")
    return data

# ----------------------------- Internal helpers ------------------------

def _parse_value_df_wrapper(val_df: pd.DataFrame) -> Tuple[List[int], str, Dict[int, str], pd.DataFrame]:
    """Wrapper to call _parse_value_df and handle exceptions."""
    try:
        return _parse_value_df(val_df)
    except Exception as e:
        logging.error(f"Error parsing value df: {e}")
        # attempt a best-effort fallback: build mapping directly
        val_df = _normalize_df_columns(val_df)
        cols = list(val_df.columns)
        year_map = _build_year_column_map(cols)
        years = sorted(year_map.keys())
        index_col = val_df.columns[0]
        year_to_value_col = {y: (year_map[y]['value'][0] if year_map[y]['value'] else next((c for c in cols if str(y) in c), None)) for y in years}
        return years, index_col, year_to_value_col, val_df


def _parse_value_df(val_df: pd.DataFrame) -> Tuple[List[int], str, Dict[int, str], pd.DataFrame]:
    """A safer, clearer implementation that chooses the best value column per year."""
    val_df = _normalize_df_columns(val_df.copy())
    index_col = val_df.columns[0]
    cols = list(val_df.columns)
    year_map = _build_year_column_map(cols)
    years = sorted(year_map.keys())

    # prefer columns that explicitly mention 'value' and 'import'
    year_to_value_col: Dict[int, str] = {}
    for y in years:
        cand = year_map[y]['value']
        if not cand:
            # attempt to find column containing year and 'import' or 'value'
            cand = [c for c in cols if str(y) in c and ('value' in _norm(c) or 'import' in _norm(c) or 'usd' in _norm(c))]
        if cand:
            year_to_value_col[y] = cand[0]
    return years, index_col, year_to_value_col, val_df


def _safe_cagr(end, start, n):
    try:
        if start is None or end is None or start <= 0 or n <= 0:
            return 0.0
        return round(((end / start) ** (1.0 / n) - 1.0) * 100.0, 2)
    except Exception:
        return 0.0


def _merge_quantity_into(base_data: Dict, qdf: pd.DataFrame, index_col: str, latest_year: int):
    logging.info("Merging quantity data...")
    try:
        cols = list(qdf.columns)
        year_map = _build_year_column_map(cols)
        # attempt to extract world quantities
        world_mask = qdf[index_col].astype(str).str.strip().str.lower() == 'world'
        if world_mask.any():
            widx = qdf.index[world_mask][0]
            world_quantities = []
            for y in base_data['years']:
                qcands = year_map.get(y, {}).get('quantity', [])
                qval = None
                if qcands:
                    qval = _safe_get_df_value(qdf, widx, qcands[0])
                world_quantities.append(int(qval) if qval else None)
            base_data['world_quantities'] = world_quantities

        # map partner quantities for latest_year
        latest_q_cols = year_map.get(latest_year, {}).get('quantity', [])
        target_col = latest_q_cols[0] if latest_q_cols else next((c for c in cols if str(latest_year) in c and 'quantity' in _norm(c)), None)
        if not target_col:
            logging.debug("No target quantity column found for latest year.")
            return

        # build lookup
        # ensure suppliers exist
        suppliers_map = {s['name'].lower(): s for s in base_data.get('suppliers_full_list', [])}
        for _, row in qdf[qdf[index_col].astype(str).str.strip().str.lower() != 'world'].iterrows():
            partner = _clean_col(row[index_col])
            key = partner.lower()
            if key in suppliers_map:
                qval = _to_num(row.get(target_col))
                suppliers_map[key]['quantity_latest'] = int(qval) if qval else None
    except Exception as e:
        logging.error(f"Error merging quantity: {e}")


def _merge_unitvalue_into(base_data: Dict, udf: pd.DataFrame, index_col: str, latest_year: int):
    logging.info("Merging unit value data...")
    try:
        cols = list(udf.columns)
        year_map = _build_year_column_map(cols)

        # world unit values (if any)
        world_mask = udf[index_col].astype(str).str.strip().str.lower() == 'world'
        if world_mask.any():
            widx = udf.index[world_mask][0]
            world_uv = []
            for y in base_data['years']:
                ucands = year_map.get(y, {}).get('unit_value', [])
                uval = None
                if ucands:
                    uval = _safe_get_df_value(udf, widx, ucands[0])
                world_uv.append(float(uval) if uval else None)
            base_data['world_unit_values'] = world_uv

        # attempt to use the special summary columns often present in unit files (e.g. "Imported value in 2024, US Dollar thousand")
        # find any column containing "imported value in 2024" or "imported quantity in 2024"
        value_summary_col = next((c for c in cols if str(latest_year) in c and 'imported value' in _norm(c)), None)
        quantity_summary_col = next((c for c in cols if str(latest_year) in c and 'imported quantity' in _norm(c)), None)
        # map suppliers
        suppliers_map = {s['name'].lower(): s for s in base_data.get('suppliers_full_list', [])}

        for _, row in udf[udf[index_col].astype(str).str.strip().str.lower() != 'world'].iterrows():
            partner = _clean_col(row[index_col])
            key = partner.lower()
            if key not in suppliers_map:
                continue
            s = suppliers_map[key]
            # unit value per latest year if present as per-year unit value
            ucands = year_map.get(latest_year, {}).get('unit_value', [])
            if ucands and ucands[0] in row.index:
                uval = _to_num(row.get(ucands[0]))
                s['unit_value_latest'] = float(uval) if uval else None
            # fallback: if quantity and value summary columns exist here, fill them
            if quantity_summary_col and quantity_summary_col in row.index:
                qv = _to_num(row.get(quantity_summary_col))
                s['quantity_latest'] = int(qv) if qv else None
            if value_summary_col and value_summary_col in row.index:
                # these summary values sometimes are US$ thousand
                vv = _to_num(row.get(value_summary_col))
                # if supplier value wasn't set earlier, set it
                if vv and (not s.get('value_usd') or s.get('value_usd') == 0):
                    s['value_usd'] = int(vv) if isinstance(vv, int) else int(vv)
    except Exception as e:
        logging.error(f"Error merging unit value: {e}")


def _add_regional_suppliers(final_data: Dict, config: Dict) -> Dict:
    logging.info("Classifying suppliers by region...")
    your_country_name = config.get('your_country')
    if not your_country_name:
        logging.warning("No your_country provided in config; skipping regional classification")
        final_data['regional_suppliers'] = []
        return final_data
    your_region = get_continent(your_country_name)
    if your_region == 'Unknown':
        logging.error(f"Could not determine region for '{your_country_name}'")
        final_data['regional_suppliers'] = []
        return final_data
    regional_suppliers = []
    for s in final_data.get('suppliers_full_list', []):
        name = s.get('name')
        if not name:
            continue
        try:
            if get_continent(name) == your_region and name.lower() != your_country_name.lower():
                regional_suppliers.append(s)
        except Exception:
            continue
    final_data['regional_suppliers'] = regional_suppliers
    logging.info(f"Found {len(regional_suppliers)} suppliers in the same region ({your_region}).")
    return final_data

# ----------------------------- World importers parsing ------------------

def parse_world_importers_txt(file_path: str, config: Dict) -> Dict:
    logging.info(f"Parsing World Importers from {file_path}")
    if not file_path or not os.path.exists(file_path):
        logging.error("World importers file missing.")
        return {}
    try:
        df = _read_tsv(file_path)
        df = _normalize_df_columns(df)
        importers_col = df.columns[0]
        year_cols = [c for c in df.columns if _extract_year(c)]
        if not year_cols:
            return {}
        years = sorted(list({_extract_year(c) for c in year_cols if _extract_year(c)}))
        latest_year = years[-1]
        # find a value column for latest year
        value_col = next((c for c in year_cols if str(latest_year) in c and 'value' in _norm(c)), None)
        if not value_col:
            value_col = next((c for c in year_cols if str(latest_year) in c), None)
        df[value_col] = df[value_col].astype(str).str.replace(',', '').apply(lambda x: _to_num(x) or 0)
        world_row = df[df[importers_col].astype(str).str.strip().str.lower() == 'world']
        if world_row.empty:
            world_total = int(df[value_col].sum())
        else:
            world_total = int(world_row.iloc[0][value_col])
        importers_df = df[df[importers_col].astype(str).str.strip().str.lower() != 'world'].copy()
        importers_df['rank'] = importers_df[value_col].rank(method='dense', ascending=False).astype(int)
        target = config.get('target_market')
        if target:
            target_row = importers_df[importers_df[importers_col].astype(str).str.strip().str.lower() == target.lower()]
            if not target_row.empty:
                rank = int(target_row.iloc[0]['rank'])
            else:
                rank = 'Not found in top importers'
        else:
            rank = None
        return {
            'world_total_imports_usd': int(world_total),
            'target_market_world_rank': rank
        }
    except Exception as e:
        logging.error(f"Could not parse world importers: {e}")
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
    
# ----------------------------- CLI example ------------------------------

if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description='Parse ITC-style value/quantity/unit_value TXT files and export CSVs')
    parser.add_argument('--value', required=True, help='Value TXT file')
    parser.add_argument('--quantity', required=False, help='Quantity TXT file')
    parser.add_argument('--unit', required=False, help='Unit value TXT file')
    parser.add_argument('--your-country', required=False, help='Your country name (for regional suppliers)')
    parser.add_argument('--target-market', required=False, help='Target market name (for world importers ranking)')
    parser.add_argument('--outdir', required=False, help='Output directory for CSVs')
    args = parser.parse_args()
    cfg = {'your_country': args.your_country or '', 'target_market': args.target_market or ''}
    res = parse_full_timeseries(args.value, args.quantity, args.unit, cfg, out_dir=args.outdir)
    print('Done. Parsed result keys:', list(res.keys()))
