"""
Quantitative Export Factsheet Assembler

Merges parsed snapshot data (world, target market, your country) 
into a populated Factsheet JSON structure.

Core idea: Only populate sections we CAN fill from the 3 Excels.
Everything else remains empty/untouched.
"""

import json
from typing import Dict, List, Optional, Any
from support.spider_core import logging


class FactsheetAssembler:
    """Assembles a populated Factsheet JSON from parsed snapshot data."""
    
    def __init__(self, config: Dict[str, str]):
        """
        Args:
            config: dict with keys:
                - your_country: str (e.g., "Italy")
                - target_market: str (e.g., "Germany")
                - product_name: str (e.g., "Product X")
                - hs_code: str (e.g., "123456")
                - year: str (e.g., "2024")
        """
        self.config = config
        self.logger = logging
        
    def build(
        self,
        world_data: List[Dict[str, Any]],
        target_data: List[Dict[str, Any]],
        your_country_data: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """
        Build populated Factsheet JSON.
        
        Args:
            world_data: Parsed world imports (from world_snapshot.xls)
            target_data: Parsed target market imports (from target_country.xls)
            your_country_data: Parsed your country exports (from your_country_exports.xls)
            
        Returns:
            Populated Factsheet JSON dict
        """
        return {
            "Quantitative_Export_Factsheet": {
                "Header": self._build_header(),
                "The_Product": self._build_the_product(),
                "Target_Market_-_Name_of_Country": self._build_target_market(),
                "Total_exports_from_Your_country_in_year_to_the_world": 
                    self._build_total_exports(your_country_data),
                "Rank_in_World_for_Imports_of_this_Product": 
                    self._build_world_rank(world_data),
                "Size_of_the_Market": 
                    self._build_market_size(world_data, target_data),
                "Growth_of_the_Market": 
                    self._build_market_growth(world_data, target_data, your_country_data),
                "Unit_Value": 
                    self._build_unit_value(target_data, world_data),
                "Competition": 
                    self._build_competition(target_data),
                "Data_sources": self._build_data_sources()
            }
        }
    
    # ========================================================================
    # SECTION BUILDERS
    # ========================================================================
    
    def _build_header(self) -> Dict[str, str]:
        """Header from config."""
        return {
            "Product": self.config.get("product_name", ""),
            "Target_Market": self.config.get("target_market", ""),
            "Month_Year": self.config.get("year", ""),
            "Logo_1": "",
            "Logo_2": ""
        }
    
    def _build_the_product(self) -> Dict[str, str]:
        """Product info from config."""
        return {
            "Product": self.config.get("product_name", ""),
            "HS_Code": self.config.get("hs_code", "")
        }
    
    def _build_target_market(self) -> Dict[str, str]:
        """Target market name."""
        return {
            "Target_market": self.config.get("target_market", "")
        }
    
    def _build_total_exports(self, your_country_data: List[Dict]) -> Dict[str, Any]:
        """
        Your country's total exports to the world.
        
        Finds "World" entry in your_country_data.
        """
        world_entry = self._find_world_entry(your_country_data)
        
        return {
            "Your_country": self.config.get("your_country", ""),
            "Year": self.config.get("year", ""),
            "USD_value": self._format_usd(
                world_entry["value_usd"] if world_entry else 0
            )
        }
    
    def _build_world_rank(self, world_data: List[Dict]) -> Dict[str, Any]:
        """
        Your country's rank in world imports of this product.
        
        Finds target_market in world_data and extracts its rank.
        """
        target_in_world = self._find_country_in_data(
            world_data, 
            self.config.get("target_market", "")
        )
        
        rank = None
        if target_in_world:
            rank = target_in_world.get("rank")
            # Try to convert to int if possible
            try:
                rank = int(rank) if rank and str(rank).isdigit() else rank
            except (ValueError, TypeError):
                pass
        
        return {
            "Rank": rank
        }
    
    def _build_market_size(
        self, 
        world_data: List[Dict], 
        target_data: List[Dict]
    ) -> Dict[str, Any]:
        """
        Size of target market:
        - World imports of product
        - Target market share of world
        - Your country exports to target market
        - Your country share in target market
        """
        world_total = self._find_world_entry(world_data)
        target_total = self._find_world_entry(target_data)
        your_in_target = self._find_country_in_data(
            target_data,
            self.config.get("your_country", "")
        )
        
        target_market_name = self.config.get("target_market", "")
        your_country_name = self.config.get("your_country", "")
        
        # Find target market's share in world
        target_in_world = self._find_country_in_data(world_data, target_market_name)
        target_share_world = target_in_world.get("share_pct", 0) if target_in_world else 0
        
        return {
            "Year": self.config.get("year", ""),
            "Target_market": target_market_name,
            "Product": self.config.get("product_name", ""),
            "Imports_from_world_USD": self._format_usd(
                world_total["value_usd"] if world_total else 0
            ),
            "Share_of_world_imports_percent": self._format_percentage(target_share_world),
            "Imports_from_your_country_USD": self._format_usd(
                your_in_target["value_usd"] if your_in_target else 0
            ),
            "Your_country": your_country_name,
            "Share_of_Target_market_imports_percent": self._format_percentage(
                your_in_target.get("share_pct", 0) if your_in_target else 0
            )
        }
    
    def _build_market_growth(
        self,
        world_data: List[Dict],
        target_data: List[Dict],
        your_country_data: List[Dict]
    ) -> Dict[str, Any]:
        """
        Market growth rates:
        - Target market's 5-year and recent growth
        - Your country's exports growth to target market
        """
        target_in_world = self._find_country_in_data(
            world_data,
            self.config.get("target_market", "")
        )
        your_in_target = self._find_country_in_data(
            target_data,
            self.config.get("your_country", "")
        )
        
        return {
            "Target_market": self.config.get("target_market", ""),
            "Five_year_growth_rate_percent": self._format_percentage(
                target_in_world.get("growth_5y_pct", 0) if target_in_world else 0
            ),
            "Recent_growth_rate_percent": self._format_percentage(
                target_in_world.get("growth_last_year_pct", 0) if target_in_world else 0
            ),
            "Your_country": self.config.get("your_country", ""),
            "Imports_from_your_country_growth_rate_percent": self._format_percentage(
                your_in_target.get("growth_5y_pct", 0) if your_in_target else 0
            )
        }
    
    def _build_unit_value(
        self,
        target_data: List[Dict],
        world_data: List[Dict]
    ) -> Dict[str, Any]:
        """
        Unit value comparison:
        - Target market's unit value for this product
        - World average unit value
        - Is target's unit value higher or lower?
        """
        target_world = self._find_world_entry(target_data)
        global_world = self._find_world_entry(world_data)
        
        target_uv = target_world.get("unit_value", 0) if target_world else 0
        global_uv = global_world.get("unit_value", 0) if global_world else 0
        
        comparison = ""
        if global_uv and target_uv:
            comparison = "more than" if target_uv > global_uv else "less than"
        
        return {
            "Target_market": self.config.get("target_market", ""),
            "Year": self.config.get("year", ""),
            "Average_unit_value": self._format_unit_value(target_uv),
            "World_unit_value": self._format_unit_value(global_uv),
            "More_than_or_less_than_world": comparison
        }
    
    def _build_competition(self, target_data: List[Dict]) -> Dict[str, Any]:
        """
        Competition landscape:
        - Top 3 suppliers to target market
        - Market concentration level
        """
        # Filter out "World" and "Total"
        competitors = [
            item for item in target_data
            if item.get("label", "").lower() not in ["world", "total", "aggregation"]
        ]
        
        # Sort by share, get top 3
        top_suppliers = sorted(
            competitors,
            key=lambda x: x.get("share_pct", 0),
            reverse=True
        )[:3]
        
        # Determine market concentration
        concentration = self._assess_concentration(top_suppliers)
        
        top_3 = {}
        for idx, supplier in enumerate(top_suppliers, 1):
            top_3[f"Supplier_{idx}"] = {
                "Name": supplier.get("label", ""),
                "Market_share_percent": self._format_percentage(
                    supplier.get("share_pct", 0)
                )
            }
        
        return {
            "Target_market": self.config.get("target_market", ""),
            "Market_concentration": concentration,
            "Top_3_exporters": top_3 if top_3 else {}
        }
    
    def _build_data_sources(self) -> Dict[str, str]:
        """Static data source."""
        return {
            "Sources": "ITC Trade Map"
        }
    
    # ========================================================================
    # HELPERS
    # ========================================================================
    
    def _find_world_entry(self, data: List[Dict]) -> Optional[Dict]:
        """Find the 'World' or 'Total' entry in parsed data."""
        if not data:
            return None
        
        for item in data:
            label = item.get("label", "").lower()
            if label in ["world", "total"]:
                return item
        
        return None
    
    def _find_country_in_data(self, data: List[Dict], country: str) -> Optional[Dict]:
        """Find a specific country in parsed data."""
        if not data or not country:
            return None
        
        country_lower = country.lower()
        for item in data:
            if item.get("label", "").lower() == country_lower:
                return item
        
        return None
    
    def _assess_concentration(self, top_suppliers: List[Dict]) -> str:
        """
        Assess market concentration based on top 3 suppliers' share.
        
        Heuristic:
        - High (>70%): Highly concentrated
        - 50-70%: Moderately concentrated
        - 30-50%: Fragmented
        - <30%: Highly fragmented
        """
        if not top_suppliers:
            return "Unknown"
        
        total_share = sum(s.get("share_pct", 0) for s in top_suppliers)
        
        if total_share > 70:
            return "highly concentrated"
        elif total_share > 50:
            return "moderately concentrated"
        elif total_share > 30:
            return "fragmented"
        else:
            return "highly fragmented"
    
    def _format_usd(self, value: float) -> str:
        """Format numeric value as USD."""
        if not value or value == 0:
            return ""
        
        if value >= 1_000_000_000:
            return f"USD {value / 1_000_000_000:.2f}B"
        elif value >= 1_000_000:
            return f"USD {value / 1_000_000:.2f}M"
        else:
            return f"USD {value:,.0f}"
    
    def _format_percentage(self, value: float) -> str:
        """Format numeric value as percentage."""
        if not value or value == 0:
            return ""
        
        return f"{value:.1f} %"
    
    def _format_unit_value(self, value: float) -> str:
        """Format unit value (assumes USD/kg or similar)."""
        if not value or value == 0:
            return ""
        
        return f"{value:.2f} USD/kg"


def build_quantitative_export_factsheet(
    config: Dict[str, str],
    world_data: List[Dict[str, Any]],
    target_data: List[Dict[str, Any]],
    your_country_data: List[Dict[str, Any]]
) -> Dict[str, Any]:
    """
    Main entry point: Build a populated Factsheet JSON.
    
    Args:
        config: Configuration with product, market, country info
        world_data: Parsed world imports snapshot
        target_data: Parsed target market imports snapshot
        your_country_data: Parsed your country exports snapshot
        
    Returns:
        Populated Factsheet JSON dict
    """
    assembler = FactsheetAssembler(config)
    return assembler.build(world_data, target_data, your_country_data)
