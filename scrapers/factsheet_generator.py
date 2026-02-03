# scrapers/factsheet_generator.py

import logging
import os
from datetime import datetime
# Import the new utilities
from support.chart_generator import generate_chart_from_json, generate_pie_chart_market_shares
from support.country_info_service import CountryInfoService

logger = logging.getLogger("FactsheetGenerator")

class FactsheetGenerator:
    # UPDATED INIT: Accept output_dir
    def __init__(self, parsed_data, config, output_dir="."):
        self.data = parsed_data
        self.config = config
        self.output_dir = output_dir
        
        # NEW: Load Time Series Data (target market imports by partner country)
        self.ts_data = parsed_data["snapshots"].get("target_market_value_ts", {}).get("data", [])

        # --- EXISTING SNAPSHOT DATASETS ---
        self.base_exports = parsed_data["snapshots"].get("base_country_global_exports", {}).get("data", [])
        self.target_suppliers = parsed_data["snapshots"].get("target_market_suppliers", {}).get("data", [])
        self.global_imports = parsed_data["snapshots"].get("global_imports", {}).get("data", [])
        
        # --- NEW TIME SERIES DATASETS ---
        # Used for "Appreciating/Depreciating" 5-year trends
        self.world_uv_ts = parsed_data["snapshots"].get("world_unit_value_ts", {}).get("data", [])
        self.target_uv_ts = parsed_data["snapshots"].get("target_market_unit_value_ts", {}).get("data", [])

        # --- KEY ROWS (Snapshot based) ---
        self.row_world_in_base = self._find_row(self.base_exports, "partner_country", "World")
        self.row_target_in_base = self._find_row(self.base_exports, "partner_country", self.config.get("target_market_name", ""))
        
        self.row_world_in_target = self._find_row(self.target_suppliers, "partner_country", "World")
        self.row_yc_in_target = self._find_row(self.target_suppliers, "partner_country", self.config.get("your_country_name", ""))
        
        self.row_world_global_imports = self._find_row(self.global_imports, "importer_country", "World")

    def _find_row(self, dataset, key, value):
        if not value: return None
        for row in dataset:
            if str(row.get(key, "")).lower() == str(value).lower():
                return row
        return None

    def _format_usd(self, val):
        if val is None: return "N/A"
        return f"{val:,.0f}"

    def _format_pct(self, val):
        if val is None: return "N/A"
        return f"{val:.1f}"

    def _get_trend(self, row):
        """Legacy trend check based on static 5-year growth column (Fallback)."""
        if not row: return "N/A"
        g_val = row.get("growth_value_5y_pct")
        g_qty = row.get("growth_qty_5y_pct")
        
        if g_val is None or g_qty is None: return "N/A"
        return "appreciating" if g_val > g_qty else "depreciating"

    def _calculate_trend_text(self, ts_row_data):
        """
        NEW: Calculates 5-year trend from Time Series row data.
        Returns: "appreciating", "depreciating", or "stable"
        """
        if not ts_row_data or not ts_row_data.get("time_series"):
            return "N/A"
        
        ts = ts_row_data["time_series"]
        years = sorted(ts.keys())
        
        if len(years) < 2: return "N/A"
        
        # Compare Start Year vs End Year
        start_year = years[0]
        end_year = years[-1]
        
        # Only calculate if we have a span of at least 3 years to call it a trend
        if int(end_year) - int(start_year) >= 2:
            start_val = ts[start_year]
            end_val = ts[end_year]
            
            if end_val > start_val: return "appreciating"
            elif end_val < start_val: return "depreciating"
            else: return "stable"
            
        return "N/A"

    def generate(self):

        # --- NEW SECTION: CHART GENERATION ---
        graph_path = "[GRAPH_PLACEHOLDER]"
        pie_chart_path = "[CHART_PLACEHOLDER]"
        
        # --- Country basic info (separate service) ---
        country_service = CountryInfoService()
        target_country_info = country_service.get_country_profile(
            self.config.get("target_market_name")
        )


        if self.ts_data:
            try:
                # Define Filename
                p_code = self.config.get("hs_code", "product")
                t_market = self.config.get("target_market_id", "market")
                filename = f"chart_{p_code}_{t_market}.png"
                
                # Define Full Path
                full_path = os.path.join(self.output_dir, "images", filename)
                
                # Generate
                generated = generate_chart_from_json(
                    self.ts_data, 
                    full_path, 
                    title=f"Import Trends (5 Years): {self.config.get('target_market_name', 'Target Market')}"
                )
                
                if generated:
                    # Store absolute path for the Doc Generator
                    graph_path = os.path.abspath(generated)
            except Exception as e:
                logger.error(f"Error triggering chart generation: {e}")
        
        # --- PIE CHART GENERATION: Market Shares ---
        if self.target_suppliers:
            try:
                # Define Filename for pie chart
                p_code = self.config.get("hs_code", "product")
                t_market = self.config.get("target_market_id", "market")
                pie_filename = f"pie_chart_{p_code}_{t_market}.png"
                
                # Define Full Path
                pie_full_path = os.path.join(self.output_dir, "images", pie_filename)
                
                # Generate pie chart
                generated_pie = generate_pie_chart_market_shares(
                    self.target_suppliers,
                    pie_full_path,
                    title=f"Market Shares of Main Suppliers: {self.config.get('target_market_name', 'Target Market')}"
                )
                
                if generated_pie:
                    # Store absolute path for the Doc Generator
                    pie_chart_path = os.path.abspath(generated_pie)
            except Exception as e:
                logger.error(f"Error triggering pie chart generation: {e}")
        # -------------------------------------------------

        # 1. TOTAL EXPORTS
        total_exports = self.row_world_in_base.get("value_exported_usd") if self.row_world_in_base else None
        rank_val = self.row_target_in_base.get("ranking_in_world_imports") if self.row_target_in_base else "N/A"

        # 2. MARKET SIZE
        tm_imp_val = self.row_world_in_target.get("value_imported_usd") if self.row_world_in_target else None
        global_imp_total = self.row_world_global_imports.get("value_imported_usd") if self.row_world_global_imports else None
        
        tm_share_world = None
        if tm_imp_val and global_imp_total:
            tm_share_world = (tm_imp_val / global_imp_total) * 100
        else:
             tm_share_world = self.row_target_in_base.get("share_in_world_imports_pct") if self.row_target_in_base else None

        tm_imp_from_yc = self.row_yc_in_target.get("value_imported_usd") if self.row_yc_in_target else None
        yc_share_in_tm = self.row_yc_in_target.get("share_in_target_market_imports_pct") if self.row_yc_in_target else None

        # 3. MARKET GROWTH
        tm_growth_5y = self.row_world_in_target.get("growth_value_5y_pct") if self.row_world_in_target else None
        world_growth_5y = self.row_world_global_imports.get("growth_value_5y_pct") if self.row_world_global_imports else None
        
        better_worse = "N/A"
        if tm_growth_5y is not None and world_growth_5y is not None:
            better_worse = "better than" if tm_growth_5y > world_growth_5y else "worse than"

        share_trend = "increasing" if (tm_growth_5y or 0) > (world_growth_5y or 0) else "decreasing"
        
        tm_growth_1y = self.row_world_in_target.get("growth_value_1y_pct") if self.row_world_in_target else None
        growing_contracting = "growing" if (tm_growth_1y or 0) > 0 else "contracting"
        sustained = "sustained" if (tm_growth_5y or 0) > 0 and (tm_growth_1y or 0) > 0 else "not sustained"

        yc_growth_5y = self.row_yc_in_target.get("growth_value_5y_pct") if self.row_yc_in_target else None
        gained_lost = "N/A"
        if yc_growth_5y is not None and tm_growth_5y is not None:
            gained_lost = "gained" if yc_growth_5y > tm_growth_5y else "lost"

        # 4. UNIT VALUE
        # A. Static Values (Snapshot)
        uv_tm = self.row_world_in_target.get("unit_value_usd") if self.row_world_in_target else None
        unit_type = self.row_world_in_target.get("quantity_unit", "Unit") if self.row_world_in_target else "Unit"
        uv_world = self.row_world_global_imports.get("unit_value_usd") if self.row_world_global_imports else None
        
        uv_compare = "N/A"
        if uv_tm is not None and uv_world is not None:
            uv_compare = "more than" if uv_tm > uv_world else "less than"
        
        # B. Time Series Trends (New Logic)
        # 1. Target Market UV Trend (using TS data)
        tm_uv_ts_row = self._find_row(self.target_uv_ts, "partner_country", "World") or \
                       self._find_row(self.target_uv_ts, "partner_country", "Total")
        tm_uv_trend_text = self._calculate_trend_text(tm_uv_ts_row)
        
        # 2. World UV Trend (using TS data)
        world_uv_ts_row = self._find_row(self.world_uv_ts, "partner_country", "World") or \
                          self._find_row(self.world_uv_ts, "partner_country", "Total")
        world_uv_trend_text = self._calculate_trend_text(world_uv_ts_row)

        # 3. Your Country UV (Static & Trend)
        uv_yc = self.row_yc_in_target.get("unit_value_usd") if self.row_yc_in_target else None
        uv_yc_compare = "higher" if (uv_yc or 0) > (uv_tm or 0) else "lower"
        
        # Use TS for Your Country Trend
        yc_uv_ts_row = self._find_row(self.target_uv_ts, "partner_country", self.config.get("your_country_name"))
        yc_trend_past = self._calculate_trend_text(yc_uv_ts_row)

        # C. Heterogeneity & Top Suppliers
        sorted_suppliers = sorted(
            [x for x in self.target_suppliers if x.get("partner_country") not in ["World", "Total", "nan"]],
            key=lambda k: k.get("value_imported_usd", 0) or 0,
            reverse=True
        )

        # 1. Top 5 Suppliers with Appreciating UV (Cross-referencing Snapshot Top 5 with TS Trends)
        top_5_by_value = sorted_suppliers[:5]
        top_5_appreciating = []
        
        for s in top_5_by_value:
            s_name = s.get("partner_country")
            # Find this supplier in the TS data
            s_ts_row = self._find_row(self.target_uv_ts, "partner_country", s_name)
            if self._calculate_trend_text(s_ts_row) == "appreciating":
                top_5_appreciating.append(s_name)

        appreciating_suppliers_str = "; ".join(top_5_appreciating) if top_5_appreciating else "None"

        # 2. Heterogeneity (Top 10)
        top_10 = sorted_suppliers[:10]
        country_x, country_y = "N/A", "N/A"
        val_x, val_y = 0, 0
        market_nature = "N/A"
        range_desc = "N/A"

        if top_10:
            valid_uvs = [s for s in top_10 if s.get("unit_value_usd") is not None]
            if valid_uvs:
                max_supplier = max(valid_uvs, key=lambda k: k["unit_value_usd"])
                min_supplier = min(valid_uvs, key=lambda k: k["unit_value_usd"])
                
                # Assign Country X (High) and Country Y (Low)
                country_x = max_supplier.get("partner_country")
                val_x = max_supplier["unit_value_usd"]
                country_y = min_supplier.get("partner_country")
                val_y = min_supplier["unit_value_usd"]
                
                is_wide = val_x > (2.0 * val_y) if val_y > 0 else True
                range_desc = "wide" if is_wide else "narrow"
                market_nature = "rather heterogeneous" if is_wide else "somewhat homogeneous"

        # 5. COMPETITION
        # A. Market Share Increasers (Top 10 Suppliers)
        market_growth_5y = self.row_world_in_target.get("growth_value_5y_pct") if self.row_world_in_target else 0
        top_10 = sorted_suppliers[:10]
        
        increasers_list = []
        for s in top_10:
            s_growth = s.get("growth_value_5y_pct")
            # If supplier growth is defined and greater than market growth
            if s_growth is not None and market_growth_5y is not None:
                if s_growth > market_growth_5y:
                    increasers_list.append(s.get("partner_country"))

        # B. Regional Competitors
        supplier_x, supplier_y, supplier_z = "N/A", "N/A", "N/A"
        yc_dist = self.row_yc_in_target.get("avg_distance_km") if self.row_yc_in_target else None
        
        if yc_dist:
            potential_neighbors = [
                s for s in sorted_suppliers 
                if s.get("partner_country") != self.config.get("your_country_name") 
                and s.get("avg_distance_km") is not None
            ]
            potential_neighbors.sort(key=lambda k: abs((k.get("avg_distance_km") or 0) - yc_dist))
            
            if len(potential_neighbors) > 0: supplier_x = potential_neighbors[0].get("partner_country")
            if len(potential_neighbors) > 1: supplier_y = potential_neighbors[1].get("partner_country")
            if len(potential_neighbors) > 2: supplier_z = potential_neighbors[2].get("partner_country")
        else:
            supplier_x = "Distance data unavailable"

        # C. Concentration (Top 3)
        top_3 = sorted_suppliers[:3]
        top_3_details = []
        for s in top_3:
            top_3_details.append({
                "name": s.get("partner_country"),
                "share_pct": self._format_pct(s.get("share_in_target_market_imports_pct"))
            })
            
        sum_share = sum([s.get("share_in_target_market_imports_pct", 0) for s in top_3])
        conc_text = "concentrated" if sum_share > 65 else "moderately concentrated" if sum_share > 35 else "not concentrated"


        # --- CONSTRUCT JSON ---
        factsheet = {
            "Quantitative_Export_Factsheet": {
                "Header": {
                    "Product": self.config.get("product_name"),
                    "Target_Market": self.config.get("target_market_name"),
                    "Month_Year": datetime.now().strftime("%B %Y")
                },
                "Total_exports_from_Your_country_in_year_to_the_world": {
                     "Your_country": self.config.get("your_country_name"),
                     "Year": "2024",
                     "USD_value": f"USD {self._format_usd(total_exports)}",
                     "Rank_in_world": str(int(rank_val)) if isinstance(rank_val, (int, float)) else "N/A"
                },
                "Size_of_the_Market": {
                    "Year": "2024",
                    "Target_market": self.config.get("target_market_name"),
                    "Imports_from_world_USD": f"USD {self._format_usd(tm_imp_val)}",
                    "Share_of_world_imports_percent": f"{self._format_pct(tm_share_world)} %",
                    "Imports_from_your_country_USD": f"USD {self._format_usd(tm_imp_from_yc)}",
                    "Share_of_Target_market_imports_percent": f"{self._format_pct(yc_share_in_tm)} %"
                },
                "Growth_of_the_Market": {
                    "Five_year_growth_rate_percent": f"{self._format_pct(tm_growth_5y)} %",
                    "Better_than_or_worse": better_worse,
                    "World_growth_rate_percent": f"{self._format_pct(world_growth_5y)} %",
                    "Target_market_share_trend": share_trend,
                    "Market_growing_or_contracting": growing_contracting,
                    "Recent_growth_rate_percent": f"{self._format_pct(tm_growth_1y)} %",
                    "Imports_from_your_country_growth_rate_percent": f"{self._format_pct(yc_growth_5y)} %",
                    "Market_share_gained_or_lost": gained_lost
                },
                "Unit_Value": {
                    "Average_unit_value": f"{self._format_usd(uv_tm)} USD / {unit_type}",
                    "Compare_to_world_average": uv_compare,
                    "World_unit_value": f"{self._format_usd(uv_world)} USD / {unit_type}",
                    "Target_Market_Trend_5y": tm_uv_trend_text,
                    "World_Trend_5y": world_uv_trend_text,
                    "Unit_value_paid_to_your_country": f"{self._format_usd(uv_yc)} USD / {unit_type}",
                    "Compare_YC_to_Market_Average": uv_yc_compare,
                    "Your_Country_Trend_5y": yc_trend_past,
                    "Top5_Suppliers_Appreciating": appreciating_suppliers_str,
                    "Heterogeneity_Analysis": {
                        "range_description": range_desc,
                        "Country_X_High": country_x,
                        "Country_X_Value": f"{self._format_usd(val_x)} USD / {unit_type}",
                        "Country_Y_Low": country_y,
                        "Country_Y_Value": f"{self._format_usd(val_y)} USD / {unit_type}",
                        "market_nature": market_nature
                    }
                },
                "Growth_Visuals_and_Seasonality": {
                    "Line_Graph_Target_Market_Imports_5_10_Years": graph_path,
                    "Comments_On_Imports_Seasonality": "Seasonality data requires monthly timeseries analysis."
                },
                "Competition": {
                    "Pie_Chart_Last_Year_Market_Shares": pie_chart_path,
                    "Summary_Text_Data": {
                        "Concentration_Label": conc_text,
                        "Top_3_Suppliers": [s['name'] for s in top_3_details],
                        "Top_3_Shares": [s['share_pct'] for s in top_3_details]
                    },
                    "Top_3_Exporters_Details": top_3_details,
                    "Market_Share_Increasers_Top10": increasers_list,
                    "Regional_Competitors_Similiar_Distance": {
                         "Your_Country_Distance_km": yc_dist,
                         "Supplier_X": supplier_x,
                         "Supplier_Y": supplier_y,
                         "Supplier_Z": supplier_z
                    }
                }
            }
        }
        
        return factsheet