# support/data_parser.py
import os
import pandas as pd
import logging
import re

# -------------------------
# Helpers
# -------------------------

def _clean_num(x):
    """
    Converts TradeMap formatted numbers to float.
    Returns None if conversion fails.
    """
    if pd.isna(x) or x is None:
        return None
    
    s = str(x).strip()
    
    # Common TradeMap non-numeric placeholders
    if s.lower() in ['', '-', 'n.a.', 'na', 'no quantity', 'nan', 'no quantity']:
        return None
    
    # Remove thousands separators (spaces, non-breaking spaces, commas) and % signs
    s = s.replace('\xa0', '').replace(' ', '').replace(',', '').replace('%', '')
    
    try:
        return float(s)
    except ValueError:
        return None

def _get_table_df(file_path):
    """
    Reads the HTML file and extracts the main data table.
    Attempts to locate the correct header row dynamically.
    """
    try:
        # TradeMap exports are often HTML files with .xls extension.
        # We read all tables looking for the specific grid ID.
        dfs = pd.read_html(file_path, attrs={'id': 'ctl00_PageContent_MyGridView1'}, header=None)
        
        if not dfs:
            return None
        
        raw_df = dfs[0]
        
        # Strategy: Find the row that contains "Value imported" or "Value exported" to use as header
        header_idx = -1
        for idx, row in raw_df.iterrows():
            row_str = " ".join([str(val) for val in row.values]).lower()
            if "value" in row_str and ("imported" in row_str or "exported" in row_str):
                header_idx = idx
                break
        
        if header_idx != -1:
            # Set header from the found row
            df = raw_df.iloc[header_idx+1:].copy()
            df.columns = raw_df.iloc[header_idx]
        else:
            # Fallback to standard TradeMap layout (usually row 1 is header)
            # Re-read with header=1
            dfs = pd.read_html(file_path, attrs={'id': 'ctl00_PageContent_MyGridView1'}, header=1)
            df = dfs[0]

        # Clean empty rows and columns
        df = df.dropna(how='all').reset_index(drop=True)
        return df

    except Exception as e:
        logging.error(f"Error reading HTML table from {file_path}: {e}")
    return None

def _find_col_idx(columns, keywords):
    """Returns the index of the first column containing any of the keywords."""
    for idx, col in enumerate(columns):
        col_str = str(col).lower()
        for kw in keywords:
            if kw in col_str:
                return idx
    return -1

# -------------------------
# Specific Parsers
# -------------------------

def parse_companies_list(file_path, out_dir=None):
    """
    Parses the Companies 'Excel' file (which is actually HTML).
    Target Table ID: ctl00_PageContent_MyGridView1
    """
    if not os.path.exists(file_path): 
        return []
    
    df = None
    try:
        # STRATEGY: Read as HTML, targeting the specific grid ID
        dfs = pd.read_html(
            file_path, 
            attrs={'id': 'ctl00_PageContent_MyGridView1'}, 
            header=0,
            encoding='utf-8'
        )
        
        if dfs:
            df = dfs[0]
        
        if df is None or df.empty:
            logging.warning(f"No company data found in {file_path}")
            return []

        # CLEANUP: Normalize column names
        df.columns = [
            str(c).strip().lower()
            .replace(' ', '_')
            .replace('(', '')
            .replace(')', '') 
            for c in df.columns
        ]
        
        records = []
        for _, row in df.iterrows():
            c_name = row.get("company_name")
            if not c_name or str(c_name).lower() == 'nan': 
                continue

            record = {
                "company_name": str(c_name).strip(),
                "country": str(row.get("country", "")).strip(),
                "city": str(row.get("city", "")).strip(),
                "website": str(row.get("website", "")).strip(),
                
                "products_traded": _clean_num(row.get("number_of_product_or_service_categories_traded")),
                "employees": _clean_num(row.get("number_of_employees")),
                "turnover_usd": _clean_num(row.get("turnover_usd"))
            }

            for key in ["country", "city", "website"]:
                if record[key].lower() == "nan":
                    record[key] = ""

            records.append(record)
        
        _save_csv(records, file_path, out_dir)
        logging.info(f"Successfully parsed {len(records)} companies.")
        return records

    except Exception as e:
        logging.error(f"Error parsing companies HTML/Excel: {e}")
        return []

def parse_target_market_suppliers(file_path, out_dir=None):
    """ Parses 'target_market_suppliers.xls' (Imports by Country) """
    df = _get_table_df(file_path)
    if df is None or df.empty: return []

    # Map columns dynamically
    cols = df.columns
    idx_partner = 0 # Always first
    idx_val = _find_col_idx(cols, ["value imported", "usd"])
    idx_balance = _find_col_idx(cols, ["trade balance"])
    idx_share = _find_col_idx(cols, ["share", "%"])
    idx_qty = _find_col_idx(cols, ["quantity", "tons", "units"])
    idx_unit = _find_col_idx(cols, ["unit"])
    idx_unit_val = _find_col_idx(cols, ["unit value"])
    idx_growth_5y = _find_col_idx(cols, ["growth", "per annum", "2019-2023", "2020-2024", "2021-2025"]) # Adjust years as needed
    idx_growth_1y = _find_col_idx(cols, ["growth", "2022-2023", "2023-2024", "2024-2025"])
    
    idx_dist = _find_col_idx(cols, ["distance"])
    idx_tariff = _find_col_idx(cols, ["tariff"])

    records = []
    for _, row in df.iterrows():
        try:
            # First column is usually the label
            label = str(row.iloc[idx_partner]).strip()
            if label.lower() in ['nan', '', 'total']: 
                if label.lower() == 'total': label = 'World'
                else: continue

            record = {
                "partner_country": label,
                "value_imported_usd": _clean_num(row.iloc[idx_val]) * 1000 if idx_val != -1 else None,
                "trade_balance_usd": _clean_num(row.iloc[idx_balance]) * 1000 if idx_balance != -1 else None,
                "share_in_target_market_imports_pct": _clean_num(row.iloc[idx_share]) if idx_share != -1 else None,
                "quantity_imported": _clean_num(row.iloc[idx_qty]) if idx_qty != -1 else None,
                "quantity_unit": str(row.iloc[idx_unit]).strip() if idx_unit != -1 else "",
                "unit_value_usd": _clean_num(row.iloc[idx_unit_val]) if idx_unit_val != -1 else None,
                "growth_value_5y_pct": _clean_num(row.iloc[idx_growth_5y]) if idx_growth_5y != -1 else None,
                "growth_value_1y_pct": _clean_num(row.iloc[idx_growth_1y]) if idx_growth_1y != -1 else None,
                "avg_distance_km": _clean_num(row.iloc[idx_dist]) if idx_dist != -1 else None,
                "tariff_applied_pct": _clean_num(row.iloc[idx_tariff]) if idx_tariff != -1 else None
            }
            records.append(record)
        except Exception:
            continue

    _save_csv(records, file_path, out_dir)
    return records

def parse_base_country_exports(file_path, out_dir=None):
    """ Parses 'base_country_exports.xls' (Exports by Country) """
    df = _get_table_df(file_path)
    if df is None or df.empty: return []

    cols = df.columns
    idx_partner = 0
    idx_val = _find_col_idx(cols, ["value exported", "usd"])
    idx_share = _find_col_idx(cols, ["share", "%"])
    idx_growth_5y = _find_col_idx(cols, ["growth", "per annum"])
    
    records = []
    for _, row in df.iterrows():
        try:
            label = str(row.iloc[idx_partner]).strip()
            if label.lower() in ['nan', '']: continue
            if label.lower() == 'total': label = 'World'

            record = {
                "partner_country": label,
                "value_exported_usd": _clean_num(row.iloc[idx_val]) * 1000 if idx_val != -1 else None,
                "share_in_base_country_exports_pct": _clean_num(row.iloc[idx_share]) if idx_share != -1 else None,
                "growth_value_5y_pct": _clean_num(row.iloc[idx_growth_5y]) if idx_growth_5y != -1 else None
            }
            records.append(record)
        except Exception:
            continue

    _save_csv(records, file_path, out_dir)
    return records

def parse_global_exports(file_path, out_dir=None):
    """ Parses 'global_exports.xls' (List of Exporters) """
    df = _get_table_df(file_path)
    if df is None or df.empty: return []

    cols = df.columns
    idx_exporter = 0
    idx_val = _find_col_idx(cols, ["value exported", "usd"])
    idx_share = _find_col_idx(cols, ["share", "%"])
    idx_growth_5y = _find_col_idx(cols, ["growth", "per annum"])
    
    records = []
    for _, row in df.iterrows():
        try:
            label = str(row.iloc[idx_exporter]).strip()
            if label.lower() in ['nan', '']: continue
            if label.lower() == 'total': label = 'World'

            record = {
                "exporter_country": label,
                "value_exported_usd": _clean_num(row.iloc[idx_val]) * 1000 if idx_val != -1 else None,
                "share_in_world_exports_pct": _clean_num(row.iloc[idx_share]) if idx_share != -1 else None,
                "growth_value_5y_pct": _clean_num(row.iloc[idx_growth_5y]) if idx_growth_5y != -1 else None
            }
            records.append(record)
        except Exception:
            continue

    _save_csv(records, file_path, out_dir)
    return records

def parse_global_imports(file_path, out_dir=None):
    """ Parses 'global_imports.xls' (List of Importers) """
    df = _get_table_df(file_path)
    if df is None or df.empty: return []

    cols = df.columns
    idx_importer = 0
    idx_val = _find_col_idx(cols, ["value imported", "usd"])
    idx_growth_5y = _find_col_idx(cols, ["growth", "per annum"])
    idx_growth_1y = _find_col_idx(cols, ["growth", "2022-2023", "2023-2024", "2024-2025"])
    idx_share = _find_col_idx(cols, ["share", "%"])
    idx_unit_val = _find_col_idx(cols, ["unit value"])

    records = []
    for _, row in df.iterrows():
        try:
            label = str(row.iloc[idx_importer]).strip()
            if label.lower() in ['nan', '']: continue
            if label.lower() == 'total': label = 'World'

            record = {
                "importer_country": label,
                "value_imported_usd": _clean_num(row.iloc[idx_val]) * 1000 if idx_val != -1 else None,
                "growth_value_5y_pct": _clean_num(row.iloc[idx_growth_5y]) if idx_growth_5y != -1 else None,
                "growth_value_1y_pct": _clean_num(row.iloc[idx_growth_1y]) if idx_growth_1y != -1 else None,
                "share_in_world_imports_pct": _clean_num(row.iloc[idx_share]) if idx_share != -1 else None,
                "unit_value_usd": _clean_num(row.iloc[idx_unit_val]) if idx_unit_val != -1 else None
            }
            records.append(record)
        except Exception:
            continue

    _save_csv(records, file_path, out_dir)
    return records

# -------------------------
# Orchestrator
# -------------------------

def _save_csv(records, original_path, out_dir):
    if out_dir and records:
        try:
            filename = os.path.basename(original_path).rsplit('.', 1)[0] + ".csv"
            out_path = os.path.join(out_dir, filename)
            pd.DataFrame(records).to_csv(out_path, index=False, encoding='utf-8-sig')
            logging.info(f"Saved parsed CSV to: {out_path}")
        except Exception as e:
            logging.warning(f"Failed to save CSV: {e}")

def parse_snapshot_excel(file_path: str, out_dir: str = None) -> list:
    logging.info(f"Processing file: {file_path}")
    if not os.path.exists(file_path): return []

    try:
        # Detect based on filename (most reliable for these standard downloads)
        fname = os.path.basename(file_path).lower()
        
        if "global_imports" in fname:
            return parse_global_imports(file_path, out_dir)
        elif "global_exports" in fname or "world_snapshot" in fname:
            return parse_global_exports(file_path, out_dir)
        elif "base_country" in fname:
            return parse_base_country_exports(file_path, out_dir)
        elif "target_market" in fname:
            return parse_target_market_suppliers(file_path, out_dir)

        # Fallback to content detection
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(4000).lower()

        if "list of importing markets" in content:
            if "exported by world" in content: return parse_global_imports(file_path, out_dir)
            return parse_base_country_exports(file_path, out_dir)
        elif "list of supplying markets" in content:
            return parse_target_market_suppliers(file_path, out_dir)
        elif "list of exporters" in content:
            return parse_global_exports(file_path, out_dir)
        elif "list of importers" in content:
            return parse_global_imports(file_path, out_dir)

        logging.error("Could not determine parser type.")
        return []

    except Exception as e:
        logging.error(f"Critical parsing error: {e}", exc_info=True)
        return []