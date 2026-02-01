# orchestrator/factsheet_builder.py

import json
import logging
import os
from datetime import datetime

logger = logging.getLogger("FactsheetBuilder")

class FactsheetBuilder:
    def __init__(self, final_report_data):
        self.data = final_report_data
        
        # Shortcuts
        self.tm = self.data.get("factsheet", {}).get("Quantitative_Export_Factsheet", {})
        self.snapshots = self.data.get("snapshots", {}) # Raw data for calculations
        self.trademap_meta = self.data.get("trademap_meta", {})
        
        self.mm = self.data.get("Market_Access", {})
        self.ep = self.data.get("Export_Potential", {})
        self.eping = self.data.get("SPS_TBT_Notifications", {})
        
        # Load Country Profiles
        self.country_profiles = self._load_country_profiles()

    def _load_country_profiles(self):
        path = os.path.join(os.getcwd(), "assets", "country_profiles.json")
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except: return {}
        return {}

    def _get(self, source, path, default=""):
        """Helper to get nested data safely."""
        keys = path.split('.')
        val = source
        for key in keys:
            if isinstance(val, dict):
                val = val.get(key)
            elif isinstance(val, list):
                try:
                    val = val[int(key)]
                except (IndexError, ValueError):
                    return default
            else:
                return default
            if val is None: return default
        return val

    def _calculate_global_rank(self, target_market_name):
        """
        Calculates rank from Global Imports snapshot.
        Skips 'World' (usually rank 1 in raw list).
        """
        # Get list of importers
        importers = self._get(self.snapshots, "global_imports.data", [])
        
        rank_counter = 0
        for row in importers:
            country = row.get("importer_country", "").lower()
            if country in ["world", "total"]:
                continue
            
            rank_counter += 1
            
            if country == target_market_name.lower():
                return str(rank_counter)
        
        return "N/A"

    def build(self):
        logger.info("Building presentation-ready Factsheet JSON...")

        product_code = self._get(self.tm, "Header.Product", "N/A")
        target_market = self._get(self.tm, "Header.Target_Market", "N/A")
        
        # 1. Official Product Name Logic
        # Priority: Scraped Name > Export Potential Name > HS Code
        official_name = self.trademap_meta.get("official_product_name")
        if not official_name:
             official_name = self._get(self.ep, "product", f"HS {product_code}")
        
        # 2. Rank Logic
        calculated_rank = self._calculate_global_rank(target_market)

        # 3. Country Profile Logic
        c_profile = self.country_profiles.get(target_market, {})

            
            # [HELPER FUNCTION TO CLEAN UNIT STRINGS]
        def _clean_unit_string(full_string):
            # Input: "USD / Tons" -> Output: "Tons"
            if "/" in full_string:
                return full_string.split("/", 1)[1].strip()
            return full_string.replace("USD", "").strip()

        # [HELPER FUNCTION TO CLEAN VALUE STRINGS]
        def _clean_value_string(full_string):
            # Input: "2,160 USD / Tons" -> Output: "2,160"
            if "USD" in str(full_string):
                return str(full_string).split("USD")[0].strip()
            return str(full_string)

        factsheet = {
            "Header": {
                "Header_Logo": "[LOGO_PATH]",
                "Product": product_code,
                "Target_Market": target_market,
                "Month_Year": datetime.now().strftime("%B %Y")
            },

            "Cover": {
                "Place_Your_Logo_Here_Repeat": "[LOGO_PATH]",
                "Product_Section_Title": f"Exporting {product_code}",
                "Target_Market_Name": target_market
            },

            "Introduction": {
                "Product_Name": official_name, # <--- UPDATED
                "HS_Code": product_code,
                "Your_Country": self._get(self.tm, "Total_exports_from_Your_country_in_year_to_the_world.Your_country"),
                "Target_Market": target_market
            },

            "Visuals": {
                "Product_Image_Good_Quality": "[IMAGE_PATH]",
                "World_or_Regional_Map_Highlighting_Target": "[MAP_PATH]"
            },

            "Trade_Overview": {
                "Total_Exports_From_Your_Country_To_World": {
                    "Year": self._get(self.tm, "Total_exports_from_Your_country_in_year_to_the_world.Year"),
                    "USD_Value": self._get(self.tm, "Total_exports_from_Your_country_in_year_to_the_world.USD_value")
                },
                "Rank_in_World_For_Imports_Of_This_Product": calculated_rank # <--- UPDATED
            },

            "Opportunity_Summary": {
                "Summary_Text": f"Opportunity analysis for exporting {product_code} to {target_market}.",
                "Capital_City": c_profile.get("Capital_City", "[Data Not Scraped]"),
                "Population": c_profile.get("Population", "[Data Not Scraped]"),
                "GDP_Per_Capita": c_profile.get("GDP_Per_Capita", "[Data Not Scraped]"),
                "Currency": c_profile.get("Currency", "[Data Not Scraped]"),
                "Languages": c_profile.get("Languages", "[Data Not Scraped]"),
                "Country_Profile_Link": f"https://www.trademap.org/Country_SelProductCountry.aspx?nvpm=1|{self._get(self.mm, 'Target_Market')}||||{product_code}"
            },

            "Size_of_the_Market": {
                "Year": self._get(self.tm, "Size_of_the_Market.Year"),
                "Target_Market_Imported_Value_From_World_USD": self._get(self.tm, "Size_of_the_Market.Imports_from_world_USD"),
                "World_Import_Share_Percent": self._get(self.tm, "Size_of_the_Market.Share_of_world_imports_percent"),
                "Target_Market_Imported_Value_From_Your_Country_USD": self._get(self.tm, "Size_of_the_Market.Imports_from_your_country_USD"),
                "Your_Country_Share_Of_Target_Imports_Percent": self._get(self.tm, "Size_of_the_Market.Share_of_Target_market_imports_percent")
            },

            # ... [Keep previous logic for Growth, Unit Value, Competition, Market Access, etc.] ...
             "Growth_of_the_Market": {
                "Five_Year_Growth_Rate_Target_Market_Percent": self._get(self.tm, "Growth_of_the_Market.Five_year_growth_rate_percent"),
                "Performance_Compared_To_World": self._get(self.tm, "Growth_of_the_Market.Better_than_or_worse"),
                "World_Imports_Growth_Rate_Percent": self._get(self.tm, "Growth_of_the_Market.World_growth_rate_percent"),
                "Target_Market_Share_Trend": self._get(self.tm, "Growth_of_the_Market.Target_market_share_trend"),
                "Most_Recent_Year_Period": "2023-2024",
                "Recent_Growth_Sustained_or_Not": "sustained" if "sustained" in self._get(self.tm, "Growth_of_the_Market.Market_growing_or_contracting", "") else "not sustained",
                "Recent_Growth_Direction": self._get(self.tm, "Growth_of_the_Market.Market_growing_or_contracting"),
                "Recent_Growth_Rate_Percent": self._get(self.tm, "Growth_of_the_Market.Recent_growth_rate_percent"),
                "Five_Year_Growth_Rate_Your_Country_Percent": self._get(self.tm, "Growth_of_the_Market.Imports_from_your_country_growth_rate_percent"),
                "Your_Country_Market_Share_Change": self._get(self.tm, "Growth_of_the_Market.Market_share_gained_or_lost")
            },
            "Growth_Visuals_and_Seasonality": {
                "Line_Graph_Target_Market_Imports_5_10_Years": "[GRAPH_IMAGE_PATH]",
                "Comments_On_Imports_Seasonality": "Detailed seasonality data requires monthly timeseries scraping."
            },

            "Unit_Value": {
                "Year": self._get(self.tm, "Size_of_the_Market.Year"),
                
                "Target_Market_Avg_Unit_Value": {
                    "Value_USD": _clean_value_string(self._get(self.tm, "Unit_Value.Average_unit_value")), 
                    # Clean unit to avoid "USD/ USD / Tons"
                    "Unit": _clean_unit_string(self._get(self.tm, "Unit_Value.Average_unit_value")) 
                },
                
                "Comparison_To_World_Unit_Value_Statement": self._get(self.tm, "Unit_Value.Compare_to_world_average"),
                
                "World_Unit_Value": {
                    "Value_USD": _clean_value_string(self._get(self.tm, "Unit_Value.World_unit_value")),
                    "Unit": _clean_unit_string(self._get(self.tm, "Unit_Value.World_unit_value"))
                },
                
                "Target_Market_Unit_Value_Trend": self._get(self.tm, "Unit_Value.Target_Market_Trend_5y"),
                
                # --- FIX 1: ADD MISSING WORLD TREND HERE ---
                "World_Unit_Value_Trend": self._get(self.tm, "Unit_Value.World_Trend_5y"), 
                # -------------------------------------------
                
                "Your_Country_Unit_Value_Paid_By_Target": {
                    "Value_USD": _clean_value_string(self._get(self.tm, "Unit_Value.Unit_value_paid_to_your_country")),
                    "Unit": _clean_unit_string(self._get(self.tm, "Unit_Value.Unit_value_paid_to_your_country"))
                },
                "Your_Country_Unit_Value_Position_Statement": self._get(self.tm, "Unit_Value.Compare_YC_to_Market_Average"),
                "Your_Country_Unit_Value_Trend": self._get(self.tm, "Unit_Value.Your_Country_Trend_5y"),
                
                "Top_Five_Suppliers_With_Appreciating_Unit_Value": self._get(self.tm, "Unit_Value.Top5_Suppliers_Appreciating", "").split('; '),
                
                "Top_Ten_Suppliers_Unit_Value_Range": {
                    "Range_Descriptor": self._get(self.tm, "Unit_Value.Heterogeneity_Analysis.range_description"),
                    
                    # --- FIX 2: CLEAN HIGH/LOW VALUES ---
                    "Highest_Unit_Value": {
                        # Previously included "USD / Tons" in the value
                        "Value_USD": _clean_value_string(self._get(self.tm, "Unit_Value.Heterogeneity_Analysis.Country_X_Value")),
                        "Unit": _clean_unit_string(self._get(self.tm, "Unit_Value.Heterogeneity_Analysis.Country_X_Value")),
                        "Country": self._get(self.tm, "Unit_Value.Heterogeneity_Analysis.Country_X_High")
                    },
                    "Lowest_Unit_Value": {
                        "Value_USD": _clean_value_string(self._get(self.tm, "Unit_Value.Heterogeneity_Analysis.Country_Y_Value")),
                        "Unit": _clean_unit_string(self._get(self.tm, "Unit_Value.Heterogeneity_Analysis.Country_Y_Value")),
                        "Country": self._get(self.tm, "Unit_Value.Heterogeneity_Analysis.Country_Y_Low")
                    },
                    "Market_Heterogeneity_Statement": self._get(self.tm, "Unit_Value.Heterogeneity_Analysis.market_nature")
                },
                "Unit_Value_Note": "Unit values are implied from trade values and quantities."
            },

            "Competition": {
                "Market_Concentration_Level": self._get(self.tm, "Competition.Summary_Text_Data.Concentration_Label"),
                "Top_Three_Suppliers": [
                    {
                        "Supplier": item.get("name"),
                        "Market_Share_Percent": item.get("share_pct")
                    } 
                    for item in self._get(self.tm, "Competition.Top_3_Exporters_Details", [])
                ],
                "Pie_Chart_Last_Year_Market_Shares": "[GRAPH_IMAGE_PATH]",
                "Top_Ten_Suppliers_Gaining_Share": self._get(self.tm, "Competition.Market_Share_Increasers_Top10", []),
                "Other_Suppliers_From_Your_Region": [
                    self._get(self.tm, "Competition.Regional_Competitors_Similiar_Distance.Supplier_X"),
                    self._get(self.tm, "Competition.Regional_Competitors_Similiar_Distance.Supplier_Y"),
                    self._get(self.tm, "Competition.Regional_Competitors_Similiar_Distance.Supplier_Z")
                ]
            },

            "Market_Access": {
                "Preferential_Market_Access_Status": "benefits" if "benefit" in self._get(self.mm, "your_country_has_or_does_not_have_a_preferential_tariff_advantage...", "") else "does not benefit",
                "Relevant_Preferential_Trade_Agreements": self._get(self.mm, "Relevant_preferential_trade_agreements", "None").split(';'),
                "Tariff_Table": self._get(self.mm, "Tariff_Table", []),
                "Short_Tariff_Analysis": self._get(self.mm, "Short_analysis_of_tariffs_and_tariff_rate_quotas_if_applicable_for_example"),
                "Tariff_Analysis_Details": {
                    "Your_Country_Preferential_Tariff_Advantage_Status": self._get(self.mm, "your_country_has_or_does_not_have_a_preferential_tariff_advantage_over_key_competitors_in_target_market_for_product"),
                    "Other_Top_Five_Suppliers_With_Preferential_Tariffs": [], # Not currently extracted explicitly as list in MM output
                    "None_Of_Top_Five_Has_Prefernces_Statement": "See Analysis",
                    "Rules_Of_Origin_Notes_And_Certificate_Of_Origin_Info": self._get(self.mm, "Rules_Of_Origin_and_Certificate_Of_Origin_information"),
                    "Tariff_Rate_Quota": {
                        "Applied": self._get(self.mm, "Tariff_rate_quota.Target_market_applies_a_tariff_rate_quota_on_imports_of_product"),
                        "Quota_Volume": self._get(self.mm, "Tariff_rate_quota.Quota_details"),
                        "Application_Period": "N/A",
                        "Outside_Quota_Tariff_Rate": "N/A"
                    },
                    "Other_Duties_Trade_Remedies_Info": self._get(self.mm, "Other_duties_applied_by_Target_market_to_imports_of_product_from_Your_country")
                }
            },

            "Non_Tariff_Measures": {
                "Mandatory_Market_Access_Requirements_List": self._get(self.mm, "Mandatory_market_access_requirements_non_tariff_measures.Requirements_list", []),
                "Potential_New_Non_Tariff_Measures": {
                    "Description_and_Links": f"Found {len(self._get(self.eping, 'notifications', []))} notifications.",
                    "Concern_Explanation": "Notifications regarding SPS/TBT can imply upcoming regulatory changes.",
                    "Eping_Check_Fallback_Sentence_If_No_Notifications": "No recent SPS/TBT notifications found in ePing." if not self._get(self.eping, 'notifications') else ""
                }
            },

            "Potential_Business_Partners": [
                {"Company_Name": "See TradeMap Companies List", "City": "-", "Website": "-"}
            ],

            "Other_Promising_Markets_By_2025": {
                "Region_Name": "Global",
                "Regional_Markets_List_And_Justification": [
                    f"Unrealized Potential: {self._get(self.ep, 'unrealized_potential')}"
                ],
                "Global_Markets_List_And_Justification": [
                    "See Export Potential Map for full diversification list."
                ]
            },

            "Key_Insights": {
                "Final_Recommendations": "Review competition prices and comply with identified NTMs."
            },

            "Data_Sources": [
                "ITC Trade Map",
                "ITC Market Access Map",
                "ITC Export Potential Map",
                "ePing"
            ],

            "Contact_Information": {
                "Organization_Website": "www.intracen.org",
                "Email_Address": "marketanalysis@intracen.org",
                "Phone_Number": "+41 22 730 6111"
            },

            "Footer": {
                "Footer_Logo": "[LOGO_PATH]"
            }
        }

        return factsheet