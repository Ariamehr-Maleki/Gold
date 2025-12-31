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
    Converts TradeMap formatted numbers (strings with spaces, units, 'No quantity') to float.
    Returns None if conversion fails.
    """
    if pd.isna(x) or x is None:
        return None
    
    s = str(x).strip()
    
    # Common TradeMap non-numeric placeholders
    if s.lower() in ['', '-', 'n.a.', 'na', 'no quantity', 'nan', 'no quantity']:
        return None
    
    # Remove thousands separators (spaces, non-breaking spaces) and % signs
    # TradeMap uses \xa0 (non-breaking space) often
    s = s.replace('\xa0', '').replace(' ', '').replace(',', '').replace('%', '')
    
    try:
        return float(s)
    except ValueError:
        return None

def _get_table_df(file_path):
    """
    Reads the HTML file and extracts the main data table (id: ctl00_PageContent_MyGridView1).
    Uses header=1 because TradeMap uses the first row for grouping headers.
    """
    try:
        # header=1 usually aligns with the metric names (Value, Quantity, etc.)
        tables = pd.read_html(file_path, attrs={'id': 'ctl00_PageContent_MyGridView1'}, header=1)
        if tables:
            df = tables[0]
            # Clean empty rows
            df = df.dropna(how='all').reset_index(drop=True)
            return df
    except Exception as e:
        logging.error(f"Error reading HTML table from {file_path}: {e}")
    return None

# -------------------------
# Specific Parsers
# -------------------------

# support/data_parser.py

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
        # header=0 implies the first row of the table contains the column names
        dfs = pd.read_html(
            file_path, 
            attrs={'id': 'ctl00_PageContent_MyGridView1'}, 
            header=0,
            encoding='utf-8' # or 'latin-1' if utf-8 fails
        )
        
        if dfs:
            df = dfs[0]
        
        # Validation
        if df is None or df.empty:
            logging.warning(f"No company data found in {file_path}")
            return []

        # CLEANUP: Normalize column names
        # remove spaces, lowercase, remove parens
        df.columns = [
            str(c).strip().lower()
            .replace(' ', '_')
            .replace('(', '')
            .replace(')', '') 
            for c in df.columns
        ]
        
        records = []
        for _, row in df.iterrows():
            # Extract Company Name
            c_name = row.get("company_name")
            if not c_name or str(c_name).lower() == 'nan': 
                continue

            # Extract details based on your HTML headers
            record = {
                "company_name": str(c_name).strip(),
                "country": str(row.get("country", "")).strip(),
                "city": str(row.get("city", "")).strip(),
                "website": str(row.get("website", "")).strip(),
                
                # Numeric fields (handle NaNs)
                "products_traded": _clean_num(row.get("number_of_product_or_service_categories_traded")),
                "employees": _clean_num(row.get("number_of_employees")),
                "turnover_usd": _clean_num(row.get("turnover_usd"))
            }

            # Basic cleanup for "nan" strings in text fields
            for key in ["country", "city", "website"]:
                if record[key].lower() == "nan":
                    record[key] = ""

            records.append(record)
        
        # Save parsed version
        _save_csv(records, file_path, out_dir)
        logging.info(f"Successfully parsed {len(records)} companies.")
        return records

    except Exception as e:
        logging.error(f"Error parsing companies HTML/Excel: {e}")
        return []
    
def parse_base_country_exports(file_path, out_dir=None):
    """ Parses 'base_country_exports.html' """
    df = _get_table_df(file_path)
    if df is None: return []
    records = []
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip()
        # FIX: Keep Total/World, only skip strictly NaN/bad rows
        if label.lower() in ['nan', '']: continue 
        if label.lower() == 'total': label = 'World'

        record = {
            "partner_country": label,
            "value_exported_usd": _clean_num(row.iloc[1]) * 1000 if _clean_num(row.iloc[1]) is not None else None,
            "trade_balance_usd": _clean_num(row.iloc[2]) * 1000 if _clean_num(row.iloc[2]) is not None else None,
            "share_in_base_country_exports_pct": _clean_num(row.iloc[3]),
            "quantity_exported": _clean_num(row.iloc[4]),
            "quantity_unit": str(row.iloc[5]).strip(),
            "unit_value_usd": _clean_num(row.iloc[6]),
            "growth_value_5y_pct": _clean_num(row.iloc[7]),
            "growth_qty_5y_pct": _clean_num(row.iloc[8]),
            "growth_value_1y_pct": _clean_num(row.iloc[9]),
            "ranking_in_world_imports": _clean_num(row.iloc[10]),
            "share_in_world_imports_pct": _clean_num(row.iloc[11]),
            "tariff_faced_pct": _clean_num(row.iloc[15]) if len(row) > 15 else None
        }
        records.append(record)
    _save_csv(records, file_path, out_dir)
    return records

def parse_target_market_suppliers(file_path, out_dir=None):
    """ Parses 'target_market_suppliers.html' """
    df = _get_table_df(file_path)
    if df is None: return []

    # --- ADDED: Dynamic column detection for Distance ---
    dist_col_idx = -1
    for idx, col_name in enumerate(df.columns):
        if "distance" in str(col_name).lower():
            dist_col_idx = idx
            break
    # ----------------------------------------------------

    records = []
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip()
        if label.lower() in ['nan', '']: continue
        if label.lower() == 'total': label = 'World'

        record = {
            "partner_country": label,
            "value_imported_usd": _clean_num(row.iloc[1]) * 1000 if _clean_num(row.iloc[1]) is not None else None,
            "trade_balance_usd": _clean_num(row.iloc[2]) * 1000 if _clean_num(row.iloc[2]) is not None else None,
            "share_in_target_market_imports_pct": _clean_num(row.iloc[3]),
            "quantity_imported": _clean_num(row.iloc[4]),
            "quantity_unit": str(row.iloc[5]).strip(),
            "unit_value_usd": _clean_num(row.iloc[6]),
            "growth_value_5y_pct": _clean_num(row.iloc[7]),
            "growth_qty_5y_pct": _clean_num(row.iloc[8]),
            "growth_value_1y_pct": _clean_num(row.iloc[9]),
            "ranking_in_world_exports": _clean_num(row.iloc[10]),
            "share_in_world_exports_pct": _clean_num(row.iloc[11]),
            "avg_distance_km": _clean_num(row.iloc[dist_col_idx]) if dist_col_idx != -1 else None,
            "tariff_applied_pct": _clean_num(row.iloc[15]) if len(row) > 15 else None
        }
        records.append(record)
    _save_csv(records, file_path, out_dir)
    return records

def parse_global_exports(file_path, out_dir=None):
    """ 
    Parses 'global_exports.html' (List of Exporters)
    Formerly parse_world_snapshot
    """
    df = _get_table_df(file_path)
    if df is None: return []
    records = []
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip()
        if label.lower() in ['nan', '']: continue
        if label.lower() == 'total': label = 'World'

        record = {
            "exporter_country": label,
            "value_exported_usd": _clean_num(row.iloc[1]) * 1000 if _clean_num(row.iloc[1]) is not None else None,
            "trade_balance_usd": _clean_num(row.iloc[2]) * 1000 if _clean_num(row.iloc[2]) is not None else None,
            "quantity_exported": _clean_num(row.iloc[3]),
            "quantity_unit": str(row.iloc[4]).strip(),
            "unit_value_usd": _clean_num(row.iloc[5]),
            "growth_value_5y_pct": _clean_num(row.iloc[6]),
            "growth_qty_5y_pct": _clean_num(row.iloc[7]),
            "growth_value_1y_pct": _clean_num(row.iloc[8]),
            "share_in_world_exports_pct": _clean_num(row.iloc[9]),
            "avg_distance_km": _clean_num(row.iloc[10]),
            "concentration_index": _clean_num(row.iloc[11])
        }
        records.append(record)
    _save_csv(records, file_path, out_dir)
    return records

def parse_global_imports(file_path, out_dir=None):
    """
    Parses 'global_imports.html' (List of Importers).
    CORRECTED MAPPING based on HTML structure:
    0: Importers
    1: Value
    2: Balance
    3: Quantity (No Share column here)
    4: Unit
    5: Unit Value
    6: Growth Val 5y
    7: Growth Qty 5y
    8: Growth Val 1y
    9: Share in World
    """
    df = _get_table_df(file_path)
    if df is None: return []

    records = []
    
    for _, row in df.iterrows():
        label = str(row.iloc[0]).strip()
        
        # Keep World/Total, skip nan
        if label.lower() in ['nan', '']: continue
        if label.lower() == 'total': label = 'World'

        record = {
            "importer_country": label,
            "value_imported_usd": _clean_num(row.iloc[1]) * 1000 if _clean_num(row.iloc[1]) is not None else None,
            "trade_balance_usd": _clean_num(row.iloc[2]) * 1000 if _clean_num(row.iloc[2]) is not None else None,
            "quantity_imported": _clean_num(row.iloc[3]),
            "quantity_unit": str(row.iloc[4]).strip(),
            # [FIX] Unit Value is Index 5
            "unit_value_usd": _clean_num(row.iloc[5]),
            # [FIX] Growth Val 5y is Index 6
            "growth_value_5y_pct": _clean_num(row.iloc[6]),
            "growth_qty_5y_pct": _clean_num(row.iloc[7]),
            "growth_value_1y_pct": _clean_num(row.iloc[8]),
            "share_in_world_imports_pct": _clean_num(row.iloc[9]),
            "avg_distance_km": _clean_num(row.iloc[10]) if len(row) > 10 else None,
            "concentration_index": _clean_num(row.iloc[11]) if len(row) > 11 else None,
            "tariff_faced_pct": _clean_num(row.iloc[12]) if len(row) > 12 else None
        }
        records.append(record)

    _save_csv(records, file_path, out_dir)
    return records

def parse_global_imports(file_path, out_dir=None):
    """
    Parses global importers table from TradeMap HTML.
    Matches real column order from the page.
    """
    df = _get_table_df(file_path)
    if df is None or df.empty:
        return []

    records = []

    for _, row in df.iterrows():
        importer = str(row.iloc[0]).strip()
        if not importer or importer.lower() == 'nan':
            continue

        record = {
            "importer_country": importer,

            # USD thousand → USD
            "value_imported_usd": (
                _clean_num(row.iloc[1]) * 1000
                if _clean_num(row.iloc[1]) is not None else None
            ),
            "trade_balance_usd": (
                _clean_num(row.iloc[2]) * 1000
                if _clean_num(row.iloc[2]) is not None else None
            ),

            "quantity_imported": _clean_num(row.iloc[3]),
            "quantity_unit": str(row.iloc[4]).strip(),

            "unit_value_usd": _clean_num(row.iloc[5]),

            "growth_value_5y_pct": _clean_num(row.iloc[6]),
            "growth_qty_5y_pct": _clean_num(row.iloc[7]),
            "growth_value_1y_pct": _clean_num(row.iloc[8]),

            "share_in_world_imports_pct": _clean_num(row.iloc[9]),

            "avg_distance_km": _clean_num(row.iloc[10]) if len(row) > 10 else None,
            "concentration_index": _clean_num(row.iloc[11]) if len(row) > 11 else None,
            "avg_tariff_pct": _clean_num(row.iloc[12]) if len(row) > 12 else None,
        }

        records.append(record)

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
            # Handle legacy name 'world_snapshot' as global exports
            return parse_global_exports(file_path, out_dir)
        elif "base_country" in fname:
            return parse_base_country_exports(file_path, out_dir)
        elif "target_market" in fname:
            return parse_target_market_suppliers(file_path, out_dir)

        # Fallback to content detection
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            content = f.read(4000).lower()

        if "list of importing markets for the product exported by" in content:
            if "exported by world" in content: return parse_global_imports(file_path, out_dir)
            return parse_base_country_exports(file_path, out_dir)
        elif "list of supplying markets for the product imported by" in content:
            return parse_target_market_suppliers(file_path, out_dir)
        elif "list of exporters for the selected product" in content:
            return parse_global_exports(file_path, out_dir)
        elif "list of importers for the selected product" in content:
            return parse_global_imports(file_path, out_dir)

        logging.error("Could not determine parser type.")
        return []

    except Exception as e:
        logging.error(f"Critical parsing error: {e}", exc_info=True)
        return []