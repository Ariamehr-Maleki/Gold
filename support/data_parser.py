# support/data_parser.py
import os
import pandas as pd
import logging
import re
from datetime import datetime 

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

def calculate_growth_from_timeseries(timeseries_data):
    """
    Calculate 5-year growth rate from time series data.
    timeseries_data: dict with year keys (strings) and values
    Returns growth percentage, or None if insufficient data
    """
    if not timeseries_data:
        return None
    
    # Sort years
    years = sorted([int(y) for y in timeseries_data.keys() if y.isdigit()])
    if len(years) < 2:
        return None
    
    start_year = years[0]
    end_year = years[-1]
    
    start_val = _clean_num(timeseries_data.get(str(start_year)))
    end_val = _clean_num(timeseries_data.get(str(end_year)))
    
    if start_val is None or end_val is None or start_val == 0:
        return None
    
    # Calculate CAGR (Compound Annual Growth Rate)
    growth_rate = ((end_val / start_val) ** (1 / (end_year - start_year)) - 1) * 100
    return round(growth_rate, 1)

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

            val_growth_5y = _clean_num(row.iloc[idx_growth_5y]) if idx_growth_5y != -1 else None
            
            record = {
                "partner_country": label,
                "value_imported_usd": _clean_num(row.iloc[idx_val]) * 1000 if idx_val != -1 else None,
                "trade_balance_usd": _clean_num(row.iloc[idx_balance]) * 1000 if idx_balance != -1 else None,
                "share_in_target_market_imports_pct": _clean_num(row.iloc[idx_share]) if idx_share != -1 else None,
                "quantity_imported": _clean_num(row.iloc[idx_qty]) if idx_qty != -1 else None,
                "quantity_unit": str(row.iloc[idx_unit]).strip() if idx_unit != -1 else "",
                "unit_value_usd": _clean_num(row.iloc[idx_unit_val]) if idx_unit_val != -1 else None,
                "growth_value_5y_pct": val_growth_5y,
                "growth_qty_5y_pct": None,  # Will be calculated from time series if available
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

def parse_time_series(file_path, out_dir=None):
    """
    Parses TradeMap Time Series Excel files.
    Robustly handles multi-row headers and HTML files with .xls extension.
    """
    if not os.path.exists(file_path): return []

    try:
        # Detect if it's HTML or actual Excel by reading first few bytes
        with open(file_path, 'rb') as f:
            header_bytes = f.read(512)
        
        is_html = b'<html' in header_bytes.lower() or b'<!doctype' in header_bytes.lower() or b'<table' in header_bytes.lower()
        
        if is_html:
            # It's an HTML file with .xls extension (TradeMap quirk)
            # FIX: Use header=0 to correctly capture <th> rows (which TradeMap uses for years), 
            # then demote that header to a data row.
            # Using header=None often causes <th> rows to be lost or consumed unexpectedly.
            dfs = pd.read_html(file_path, attrs={'id': 'ctl00_PageContent_MyGridView1'}, header=0)
            
            if not dfs:
                return []
            
            raw_df = dfs[0]
            
            # Demote the detected header (columns) to become the first row (index 0) of the DataFrame.
            # This ensures the heuristic scanning logic (which checks rows for years) finds the header text
            # exactly where it expects it, regardless of whether pandas thought it was a header or not.
            header_row = pd.DataFrame([raw_df.columns], columns=raw_df.columns)
            raw_df = pd.concat([header_row, raw_df], ignore_index=True)
            
            # Reset column names to numeric indices for consistent handling
            raw_df.columns = range(len(raw_df.columns))
            
            logging.debug(f"HTML DataFrame shape: {raw_df.shape}, columns: {list(raw_df.columns)}")
            logging.debug(f"First few rows of HTML DF:\n{raw_df.head(3)}")
        else:
            # It's an actual Excel file
            raw_df = pd.read_excel(file_path, sheet_name=0, header=None, engine='openpyxl')
        
        if raw_df.empty:
            return []
        
        # FAST PATH: simple header with embedded years (e.g., "Imported value in 2020")
        simple_year_cols = []
        for col in raw_df.iloc[0].values:
            if isinstance(col, str):
                if re.search(r'\b(20\d{2}|19\d{2})\b', col):
                    simple_year_cols.append(col)
        
        if len(simple_year_cols) >= 2:
            # Treat first row as header directly
            df = raw_df.iloc[1:].copy()
            df.columns = raw_df.iloc[0]
            df = df.dropna(how='all').reset_index(drop=True)
            
            # Now extract TS directly
            records = []
            for _, row in df.iterrows():
                label = str(row.iloc[0]).strip()
                if label.lower() in ['nan', '', 'total']:
                    label = 'World' if 'total' in label.lower() else None
                if not label:
                    continue
                
                ts_data = {}
                for col in df.columns[1:]:
                    year_match = re.search(r'\b(20\d{2}|19\d{2})\b', str(col))
                    if year_match:
                        year = year_match.group(1)
                        val = _clean_num(row[col])
                        if val is not None:
                            ts_data[year] = val
                
                if ts_data:
                    records.append({
                        "partner_country": label,
                        "time_series": ts_data,
                        "available_years": sorted(ts_data.keys())
                    })
            
            _save_csv(records, file_path, out_dir)
            logging.info(f"Successfully parsed SIMPLE TS for {len(records)} partners.")
            return records
        
        # Define a range of plausible years
        current_year = datetime.now().year
        valid_year_range = range(current_year - 15, current_year + 2)  # 2010 to 2026
        
        # 1. Check if we have multi-row headers (e.g., unit value time series with colspan)
        # Look for rows with years and rows with sub-headers like "Exported unit value"
        year_header_idx = -1
        subheader_idx = -1
        max_years_found = 0
        
        for idx, row in raw_df.iterrows():
            years_in_row = 0
            for val in row.values:
                try:
                    if pd.isna(val):
                        continue
                    year_int = int(float(val))
                    if year_int in valid_year_range:
                        years_in_row += 1
                except (ValueError, TypeError):
                    s_val = str(val).strip()
                    # Check if it's a pure 4-digit year
                    if s_val.isdigit() and len(s_val) == 4:
                        try:
                            if int(s_val) in valid_year_range:
                                years_in_row += 1
                        except:
                            pass
                    # Also check if the string contains a year (e.g., "Imported value in 2020")
                    else:
                        year_matches = re.findall(r'\b(20\d{2}|19\d{2})\b', s_val)
                        for year_str in year_matches:
                            if int(year_str) in valid_year_range:
                                years_in_row += 1
            
            if years_in_row > max_years_found:
                max_years_found = years_in_row
                year_header_idx = idx
            
            # Check for sub-headers (e.g., "Exported unit value", "Exported value", etc.)
            if subheader_idx == -1:
                row_str = ' '.join([str(v).lower() for v in row.values if pd.notna(v)])
                if any(keyword in row_str for keyword in ['exported value', 'exported unit value', 'quantity']):
                    subheader_idx = idx
        
        if year_header_idx == -1 or max_years_found < 2:
            logging.warning("Could not identify year header row in time series file.")
            year_header_idx = 0
        
        # 2. If we have a subheader row that comes after the year row, we have a multi-row header
        # The actual data starts after the subheader row
        if subheader_idx != -1 and subheader_idx > year_header_idx:
            # Multi-row header case: build column names from year + subheader combination
            df_data = raw_df.iloc[subheader_idx+1:].copy()
            
            # Get year row and subheader row
            year_row = raw_df.iloc[year_header_idx]
            sub_row = raw_df.iloc[subheader_idx]
            
            # Build meaningful column names: combine year with sub-header (skip "Unit" columns)
            new_cols = []
            for i in range(len(raw_df.columns)):
                year_val = str(year_row.iloc[i]).strip() if i < len(year_row) else ""
                sub_val = str(sub_row.iloc[i]).strip() if i < len(sub_row) else ""
                
                # Skip pure "Unit" columns and NaN columns
                if sub_val.lower() in ['unit', 'nan', ''] or year_val.lower() in ['nan', '']:
                    new_cols.append(None)
                else:
                    # Use year + sub_val as column name, or just the sub_val if year is empty
                    col_name = f"{year_val}_{sub_val}" if year_val and year_val.isdigit() else sub_val
                    new_cols.append(col_name)
            
            df_data.columns = new_cols
        else:
            # Simple single-row header case
            df_data = raw_df.iloc[year_header_idx+1:].copy()
            df_data.columns = raw_df.iloc[year_header_idx]
        
        df = df_data.dropna(how='all').reset_index(drop=True)
        
        # 3. Extract partner country name (usually first column) and time series values
        cols = df.columns
        partner_col_idx = 0
        
        # Find numeric value columns (exclude unit columns)
        year_cols = []
        value_col_indices = []
        
        for col_idx, col in enumerate(cols):
            if col is None:
                continue
            col_str = str(col).strip()
            
            # Skip "Unit" and empty columns
            if col_str.lower() in ['unit', 'nan', '']:
                continue
            
            # Try to extract year from column name
            year_match = None
            for y in valid_year_range:
                if str(y) in col_str:
                    year_match = str(y)
                    break
            
            if year_match:
                year_cols.append(year_match)
                value_col_indices.append(col_idx)
        
        # Remove duplicates while preserving order
        year_cols_unique = []
        seen = set()
        for y in year_cols:
            if y not in seen:
                year_cols_unique.append(y)
                seen.add(y)
        
        year_cols = sorted(year_cols_unique)
        
        records = []
        for _, row in df.iterrows():
            try:
                label = str(row.iloc[partner_col_idx]).strip() if partner_col_idx < len(row) else ""
                
                if label.lower() in ['nan', '', 'total']:
                    if 'world' in label.lower() or 'total' in label.lower():
                        label = 'World'
                    else:
                        continue
                
                # Extract time series values using identified value columns
                ts_data = {}
                for col_idx, year in zip(value_col_indices, year_cols):
                    if col_idx < len(row):
                        val = _clean_num(row.iloc[col_idx])
                        if val is not None:
                            ts_data[year] = val
                
                # Only add if we have some data
                if ts_data:
                    records.append({
                        "partner_country": label,
                        "time_series": ts_data,
                        "available_years": year_cols
                    })
            except Exception as e:
                logging.debug(f"Error processing row: {e}")
                continue

        _save_csv(records, file_path, out_dir)
        logging.info(f"Successfully parsed TS data for {len(records)} partners.")
        return records

    except Exception as e:
        logging.error(f"Error parsing time series: {e}")
        return []
    
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