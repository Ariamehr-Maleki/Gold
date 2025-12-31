# scrapers/factsheet_generator.py

import logging
from datetime import datetime

logger = logging.getLogger("FactsheetGenerator")

class FactsheetGenerator:
    def __init__(self, parsed_data, config):
        self.data = parsed_data
        self.config = config
        
        # Datasets
        self.base_exports = parsed_data["snapshots"].get("base_country_global_exports", {}).get("data", [])
        self.target_suppliers = parsed_data["snapshots"].get("target_market_suppliers", {}).get("data", [])
        self.global_imports = parsed_data["snapshots"].get("global_imports", {}).get("data", [])
        
        # Key Rows
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
        """Determines if Unit Value is appreciating or depreciating."""
        if not row: return "N/A"
        g_val = row.get("growth_value_5y_pct")
        g_qty = row.get("growth_qty_5y_pct")
        
        if g_val is None or g_qty is None: return "N/A"
        return "appreciating" if g_val > g_qty else "depreciating"

    def generate(self):
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
        uv_tm = self.row_world_in_target.get("unit_value_usd") if self.row_world_in_target else None
        unit_type = self.row_world_in_target.get("quantity_unit", "Unit") if self.row_world_in_target else "Unit"
        uv_world = self.row_world_global_imports.get("unit_value_usd") if self.row_world_global_imports else None
        
        uv_compare = "N/A"
        if uv_tm is not None and uv_world is not None:
            uv_compare = "more than" if uv_tm > uv_world else "less than"

        tm_uv_trend = self._get_trend(self.row_world_in_target)
        world_uv_trend = self._get_trend(self.row_world_global_imports)

        uv_yc = self.row_yc_in_target.get("unit_value_usd") if self.row_yc_in_target else None
        uv_yc_compare = "higher" if (uv_yc or 0) > (uv_tm or 0) else "lower"
        
        yc_trend_raw = self._get_trend(self.row_yc_in_target)
        yc_trend_past = "appreciated" if yc_trend_raw == "appreciating" else "depreciated" if yc_trend_raw == "depreciating" else "N/A"

        # --- ANALYSIS: Top Suppliers, Trends, and Heterogeneity ---
        sorted_suppliers = sorted(
            [x for x in self.target_suppliers if x.get("partner_country") not in ["World", "Total", "nan"]],
            key=lambda k: k.get("value_imported_usd", 0) or 0,
            reverse=True
        )

        # A. Appreciating Suppliers (Top 5)
        top_5 = sorted_suppliers[:5]
        appreciating_suppliers = [
            s.get("partner_country") for s in top_5 if self._get_trend(s) == "appreciating"
        ]
        appreciating_suppliers_str = "; ".join(appreciating_suppliers) if appreciating_suppliers else "None"

        # B. Heterogeneity (Top 10) -> COUNTRY X and COUNTRY Y
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

        # C. Regional Competitors -> SUPPLIER X, Y, Z
        # Proxy: Find suppliers with similar "Average distance" to Your Country
       # 1. Market Share Increasers (Top 10 Suppliers)
        # Definition: A supplier increases share if their growth > total market growth
        market_growth_5y = self.row_world_in_target.get("growth_value_5y_pct") if self.row_world_in_target else 0
        top_10 = sorted_suppliers[:10]
        
        increasers_list = []
        for s in top_10:
            s_growth = s.get("growth_value_5y_pct")
            # If supplier growth is defined and greater than market growth
            if s_growth is not None and market_growth_5y is not None:
                if s_growth > market_growth_5y:
                    increasers_list.append(s.get("partner_country"))

        # 2. Regional Competitors (Supplier X, Y, Z)
        # Proxy: Find suppliers with "Average distance" similar to "Your Country"
        supplier_x, supplier_y, supplier_z = "N/A", "N/A", "N/A"
        
        yc_dist = self.row_yc_in_target.get("avg_distance_km")
        
        if yc_dist:
            # Filter: Not 'Your Country', Must have Distance
            potential_neighbors = [
                s for s in sorted_suppliers 
                if s.get("partner_country") != self.config.get("your_country_name") 
                and s.get("avg_distance_km") is not None
            ]
            
            # Sort by difference in distance (Smallest delta = closest geographically relative to target)
            potential_neighbors.sort(key=lambda k: abs((k.get("avg_distance_km") or 0) - yc_dist))
            
            if len(potential_neighbors) > 0: supplier_x = potential_neighbors[0].get("partner_country")
            if len(potential_neighbors) > 1: supplier_y = potential_neighbors[1].get("partner_country")
            if len(potential_neighbors) > 2: supplier_z = potential_neighbors[2].get("partner_country")
        else:
            # Fallback if your country has no distance data (e.g. neighboring country with 0 distance or error)
            supplier_x = "Distance data unavailable"

        # 3. Top 3 Market Share (for text filling)
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
                # ... (Keep Header, Total_exports, Size, Growth, Unit_Value sections unchanged) ...
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
                    "Target_Market_Trend_5y": tm_uv_trend,
                    "World_Trend_5y": world_uv_trend,
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

                # --- UPDATED COMPETITION SECTION ---
                "Competition": {
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
                # -----------------------------------
            }
        }
        
        return factsheet