import math
from datetime import datetime
from typing import Dict, List, Any, Optional

class FactsheetAssembler:
    """
    Assembles the 'Quantitative_Export_Factsheet' section of the report
    based on TradeMap data.
    """

    def __init__(self, config: Dict[str, str]):
        self.config = config
        self.target_market = config.get("target_market_name", "Target Market")
        self.your_country = config.get("your_country_name", "Your Country")
        self.product_name = config.get("product_name", config.get("hs_code", ""))
        self.hs_code = config.get("hs_code", "")
        
    def build(self, world_data: List[Dict], target_data: List[Dict], your_country_data: List[Dict], companies_data: List[Dict] = None) -> Dict[str, Any]:
        """
        Main build method.
        """
        # --- Pre-calculate Lookups ---
        # 1. World Row in Target Market Data (Target Market's imports from World)
        row_tm_world = self._find_row(target_data, "partner_country", "World")
        
        # 2. Your Country Row in Target Market Data (Target Market's imports from You)
        row_tm_yc = self._find_row(target_data, "partner_country", self.your_country)
        
        # 3. World Row in Global Imports (World's total imports)
        row_global_world = self._find_row(world_data, "importer_country", "World")
        
        # 4. Target Market Row in Global Imports (Target Market's rank/share in world)
        row_global_tm = self._find_row(world_data, "importer_country", self.target_market)

        # 5. World Row in Your Country Exports (Your total exports to world)
        row_yc_world_exports = self._find_row(your_country_data, "partner_country", "World")

        return {
            "Header": {
                "Header_Logo": "", # Placeholder
                "Product": self.hs_code,
                "Target_Market": self.target_market,
                "Month_Year": datetime.now().strftime("%B %Y")
            },
            "Cover": {
                "Place_Your_Logo_Here_Repeat": "",
                "Product_Section_Title": f"Product: {self.product_name}",
                "Target_Market_Name": self.target_market
            },
            "Introduction": {
                "Product_Name": self.product_name,
                "HS_Code": self.hs_code,
                "Your_Country": self.your_country,
                "Target_Market": self.target_market
            },
            "Visuals": {
                "Product_Image_Good_Quality": "", 
                "World_or_Regional_Map_Highlighting_Target": ""
            },
            "Trade_Overview": self._build_trade_overview(row_yc_world_exports, row_global_tm),
            "Opportunity_Summary": {
                "Summary_Text": f"Opportunity analysis for {self.your_country} exporting {self.hs_code} to {self.target_market}.",
                "Capital_City": "", # TradeMap doesn't provide this, leaving empty for template
                "Population": "",
                "GDP_Per_Capita": "",
                "Currency": "",
                "Languages": "",
                "Country_Profile_Link": f"https://www.trademap.org/Country_SelProductCountry.aspx?nvpm=1|{self.config.get('target_market_id','')}"
            },
            "Size_of_the_Market": self._build_market_size(row_tm_world, row_global_world, row_tm_yc),
            "Growth_of_the_Market": self._build_market_growth(row_tm_world, row_global_world, row_tm_yc),
            "Growth_Visuals_and_Seasonality": {
                "Line_Graph_Target_Market_Imports_5_10_Years": "[GRAPH_PLACEHOLDER]",
                "Comments_On_Imports_Seasonality": "Seasonality data requires monthly timeseries analysis."
            },
            "Unit_Value": self._build_unit_value(row_tm_world, row_global_world, row_tm_yc, target_data),
            "Competition": self._build_competition(target_data, row_tm_yc),
            
            # --- Placeholders for Other Scrapers ---
            # These will be merged by the Orchestrator/Report Builder
            "Market_Access": {}, 
            "Non_Tariff_Measures": {},
            
            "Potential_Business_Partners": self._build_companies(companies_data),
            "Other_Promising_Markets_By_2025": {
                "Region_Name": "Global",
                "Regional_Markets_List_And_Justification": ["Analysis required based on Export Potential Map"],
                "Global_Markets_List_And_Justification": ["Analysis required based on Export Potential Map"]
            },
            "Key_Insights": {
                "Final_Recommendations": "Review unit value competitiveness and market access requirements."
            },
            "Data_Sources": ["ITC Trade Map"],
            "Contact_Information": {
                "Organization_Website": "",
                "Email_Address": "",
                "Phone_Number": ""
            },
            "Footer": {
                "Footer_Logo": ""
            }
        }

    # --- Section Builders ---

    def _build_trade_overview(self, yc_world_row, global_tm_row):
        return {
            "Total_Exports_From_Your_Country_To_World": {
                "Year": "2024", # Ideally dynamic
                "USD_Value": self._fmt_usd(yc_world_row.get("value_exported_usd")) if yc_world_row else "N/A"
            },
            "Rank_in_World_For_Imports_Of_This_Product": str(int(global_tm_row.get("ranking_in_world_imports", 0))) if global_tm_row else "N/A"
        }

    def _build_market_size(self, tm_world, global_world, tm_yc):
        tm_val = tm_world.get("value_imported_usd", 0) if tm_world else 0
        global_val = global_world.get("value_imported_usd", 0) if global_world else 1 # Avoid div/0
        yc_val = tm_yc.get("value_imported_usd", 0) if tm_yc else 0
        
        return {
            "Year": "2024",
            "Target_Market_Imported_Value_From_World_USD": self._fmt_usd(tm_val),
            "World_Import_Share_Percent": f"{(tm_val / global_val * 100):.1f} %",
            "Target_Market_Imported_Value_From_Your_Country_USD": self._fmt_usd(yc_val),
            "Your_Country_Share_Of_Target_Imports_Percent": f"{tm_yc.get('share_in_target_market_imports_pct', 0):.1f} %" if tm_yc else "0.0 %"
        }

    def _build_market_growth(self, tm_world, global_world, tm_yc):
        tm_growth_5y = tm_world.get("growth_value_5y_pct", 0) if tm_world else 0
        world_growth_5y = global_world.get("growth_value_5y_pct", 0) if global_world else 0
        tm_growth_1y = tm_world.get("growth_value_1y_pct", 0) if tm_world else 0
        yc_growth_5y = tm_yc.get("growth_value_5y_pct", 0) if tm_yc else 0
        
        return {
            "Five_Year_Growth_Rate_Target_Market_Percent": f"{tm_growth_5y} %",
            "Performance_Compared_To_World": "better than" if tm_growth_5y > world_growth_5y else "worse than",
            "World_Imports_Growth_Rate_Percent": f"{world_growth_5y} %",
            "Target_Market_Share_Trend": "increasing" if tm_growth_5y > world_growth_5y else "decreasing",
            "Most_Recent_Year_Period": "2023-2024",
            "Recent_Growth_Sustained_or_Not": "sustained" if (tm_growth_5y > 0 and tm_growth_1y > 0) else "not sustained",
            "Recent_Growth_Direction": "growing" if tm_growth_1y > 0 else "contracting",
            "Recent_Growth_Rate_Percent": f"{tm_growth_1y} %",
            "Five_Year_Growth_Rate_Your_Country_Percent": f"{yc_growth_5y} %",
            "Your_Country_Market_Share_Change": "gained" if yc_growth_5y > tm_growth_5y else "lost"
        }

    def _build_unit_value(self, tm_world, global_world, tm_yc, all_suppliers):
        # 1. Basics
        tm_uv = tm_world.get("unit_value_usd", 0) if tm_world else 0
        world_uv = global_world.get("unit_value_usd", 0) if global_world else 0
        yc_uv = tm_yc.get("unit_value_usd", 0) if tm_yc else 0
        unit = tm_world.get("quantity_unit", "Unit") if tm_world else "Unit"

        # 2. Trends
        # Heuristic: if Value Growth > Qty Growth, UV is appreciating
        def get_trend(row):
            if not row: return "N/A"
            val_g = row.get("growth_value_5y_pct", 0)
            qty_g = row.get("growth_qty_5y_pct", 0)
            return "appreciating" if val_g > qty_g else "depreciating"

        tm_trend = get_trend(tm_world)
        yc_trend = get_trend(tm_yc)

        # 3. Top 5 Appreciating Suppliers
        # Filter valid suppliers
        suppliers = [s for s in all_suppliers if s.get("partner_country") not in ["World", "Total", "nan"]]
        top_5_appreciating = []
        for s in suppliers:
             if get_trend(s) == "appreciating":
                 top_5_appreciating.append(s.get("partner_country"))
             if len(top_5_appreciating) >= 5: break

        # 4. Heterogeneity (Range Analysis of Top 10)
        top_10 = sorted(suppliers, key=lambda x: x.get("value_imported_usd", 0), reverse=True)[:10]
        valid_uvs = [s for s in top_10 if s.get("unit_value_usd")]
        
        highest_s = max(valid_uvs, key=lambda x: x["unit_value_usd"]) if valid_uvs else {}
        lowest_s = min(valid_uvs, key=lambda x: x["unit_value_usd"]) if valid_uvs else {}
        
        is_hetero = False
        if highest_s and lowest_s:
            if lowest_s["unit_value_usd"] > 0:
                ratio = highest_s["unit_value_usd"] / lowest_s["unit_value_usd"]
                is_hetero = ratio > 2.0
        
        return {
            "Year": "2024",
            "Target_Market_Avg_Unit_Value": {
                "Value_USD": f"{tm_uv:,.0f}",
                "Unit": unit
            },
            "Comparison_To_World_Unit_Value_Statement": "more than" if tm_uv > world_uv else "less than",
            "World_Unit_Value": {
                "Value_USD": f"{world_uv:,.0f}",
                "Unit": unit
            },
            "Target_Market_Unit_Value_Trend": tm_trend,
            "Your_Country_Unit_Value_Paid_By_Target": {
                 "Value_USD": f"{yc_uv:,.0f}",
                 "Unit": unit
            },
            "Your_Country_Unit_Value_Position_Statement": "higher" if yc_uv > tm_uv else "lower",
            "Your_Country_Unit_Value_Trend": yc_trend,
            "Top_Five_Suppliers_With_Appreciating_Unit_Value": top_5_appreciating,
            "Top_Ten_Suppliers_Unit_Value_Range": {
                "Range_Descriptor": "wide" if is_hetero else "narrow",
                "Highest_Unit_Value": {
                    "Value_USD": f"{highest_s.get('unit_value_usd',0):,.0f}",
                    "Unit": unit,
                    "Country": highest_s.get("partner_country", "N/A")
                },
                "Lowest_Unit_Value": {
                    "Value_USD": f"{lowest_s.get('unit_value_usd',0):,.0f}",
                    "Unit": unit,
                    "Country": lowest_s.get("partner_country", "N/A")
                },
                "Market_Heterogeneity_Statement": "rather heterogeneous" if is_hetero else "somewhat homogeneous"
            },
            "Unit_Value_Note": "Unit values are implied from trade value and quantity."
        }

    def _build_competition(self, all_suppliers, tm_yc):
        # Filter exclusions
        valid_suppliers = [
            s for s in all_suppliers 
            if s.get("partner_country") not in ["World", "Total", "nan"]
            and s.get("value_imported_usd") is not None
        ]
        
        # Sort by Share
        sorted_s = sorted(valid_suppliers, key=lambda x: x.get("share_in_target_market_imports_pct", 0), reverse=True)
        top_3 = sorted_s[:3]
        
        # Concentration
        top3_share_sum = sum(s.get("share_in_target_market_imports_pct", 0) for s in top_3)
        conc_label = "concentrated" if top3_share_sum > 60 else "moderately concentrated" if top3_share_sum > 35 else "fragmented"

        # Gainers (Growth > Market Growth)
        # We need market growth again
        market_growth = next((s.get("growth_value_5y_pct", 0) for s in all_suppliers if s.get("partner_country") == "World"), 0)
        gainers = []
        for s in sorted_s[:10]:
            if s.get("growth_value_5y_pct", -999) > market_growth:
                gainers.append(s.get("partner_country"))

        # Regional (Simple Distance Proxy)
        yc_dist = tm_yc.get("avg_distance_km") if tm_yc else None
        regional = []
        if yc_dist:
             # Find countries with distance close to YC (+- 1000km)
             for s in sorted_s:
                 dist = s.get("avg_distance_km")
                 if dist and abs(dist - yc_dist) < 1500 and s.get("partner_country") != self.your_country:
                     regional.append(s.get("partner_country"))
        
        return {
            "Market_Concentration_Level": conc_label,
            "Top_Three_Suppliers": [
                {
                    "Supplier": s.get("partner_country"),
                    "Market_Share_Percent": f"{s.get('share_in_target_market_imports_pct', 0):.1f}"
                } for s in top_3
            ],
            "Pie_Chart_Last_Year_Market_Shares": "[CHART_PLACEHOLDER]",
            "Top_Ten_Suppliers_Gaining_Share": gainers,
            "Other_Suppliers_From_Your_Region": regional[:5]
        }

    def _build_companies(self, companies_data):
        if not companies_data:
            return []
        
        # Clean and map
        output = []
        for c in companies_data[:10]:
            output.append({
                "Company_Name": c.get("company_name", ""),
                "City": c.get("city", ""),
                "Website": c.get("website", "")
            })
        return output

    # --- Helpers ---
    def _find_row(self, dataset, key_field, value):
        if not dataset: return None
        for row in dataset:
            if row.get(key_field, "").lower() == value.lower():
                return row
        return None

    def _fmt_usd(self, val):
        if val is None: return "N/A"
        return f"USD {val:,.0f}"

def build_quantitative_export_factsheet(config, world_data, target_data, your_country_data, companies_data=None):
    assembler = FactsheetAssembler(config)
    return assembler.build(world_data, target_data, your_country_data, companies_data)