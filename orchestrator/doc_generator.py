import json
import os
import logging
import re
from datetime import datetime
import matplotlib.pyplot as plt
from docx import Document
from docx.shared import Inches, Pt
from docx.enum.text import WD_ALIGN_PARAGRAPH

# Configuration
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

class FactsheetGenerator:
    def __init__(self, json_path, output_dir):
        self.json_path = json_path
        self.output_dir = output_dir
        self.data = self._load_data()
        
        # Extract high-level sections for easier access
        self.meta = self.data.get('meta', {})
        self.summary = self.data.get('summary', {})
        self.market = self.data.get('market_size_and_growth', {})
        self.comp = self.data.get('competition_and_suppliers', {})
        self.access = self.data.get('market_access_conditions', {})
        self.history = self.data.get('historical_data', {})
        
        self.target_market = self.meta.get('importing_country', 'Target Market')
        self.your_country = self.meta.get('exporting_country', 'Your Country')
        self.hs_code = self.meta.get('product_hs6', 'N/A')
        
        # Prepare place to store calculated values
        self.replacements = {}

    def _load_data(self):
        if not os.path.exists(self.json_path):
            raise FileNotFoundError(f"JSON file not found at {self.json_path}")
        with open(self.json_path, 'r', encoding='utf-8') as f:
            return json.load(f)

    def safe_num(self, value, default=0.0):
        """Converts value to float safely. Handles lists, strings, and None."""
        if isinstance(value, list):
            # If it's a list (like unit values), take the last non-null item
            valid_items = [x for x in value if x is not None]
            return float(valid_items[-1]) if valid_items else default
        if value in [None, "N/A", "", "null"]:
            return default
        try:
            # Remove non-numeric chars like '$' or ',' if present
            clean_val = str(value).replace('$', '').replace(',', '').replace(' ', '')
            return float(clean_val)
        except (ValueError, TypeError):
            return default

    def _generate_charts(self):
        """Generates and saves charts to the output directory."""
        graphs_dir = os.path.join(self.output_dir, 'graphs')
        os.makedirs(graphs_dir, exist_ok=True)
        
        # 1. Import History Line Chart
        years = self.history.get('years', [])
        values = self.history.get('target_market_import_values_usd', [])
        line_path = os.path.join(graphs_dir, 'imports_line.png')

        if years and values and len(years) == len(values):
            plt.figure(figsize=(6, 3))
            # Convert to Millions for readability
            vals_m = [self.safe_num(v)/1000000 for v in values]
            plt.plot(years, vals_m, marker='o', linestyle='-', color='#0056b3', linewidth=2)
            plt.title(f"Imports of HS {self.hs_code} to {self.target_market}", fontsize=10)
            plt.ylabel("Value (USD Million)", fontsize=8)
            plt.grid(True, linestyle='--', alpha=0.5)
            plt.xticks(years, rotation=0, fontsize=8)
            plt.yticks(fontsize=8)
            plt.tight_layout()
            plt.savefig(line_path, dpi=150)
            plt.close()
        else:
            line_path = None

        # 2. Market Share Pie Chart
        suppliers = self.comp.get('all_suppliers', [])
        pie_path = os.path.join(graphs_dir, 'share_pie.png')
        
        if suppliers:
            # Sort and take top 5
            valid_s = [s for s in suppliers if self.safe_num(s.get('market_share_pct')) > 0]
            top_5 = sorted(valid_s, key=lambda x: self.safe_num(x['market_share_pct']), reverse=True)[:5]
            
            labels = [s['name'] for s in top_5]
            sizes = [self.safe_num(s['market_share_pct']) for s in top_5]
            
            # Calculate "Others"
            total_top = sum(sizes)
            if total_top < 100:
                labels.append("Others")
                sizes.append(100 - total_top)
            
            colors = ['#4e79a7', '#f28e2b', '#e15759', '#76b7b2', '#59a14f', '#edc948']
            plt.figure(figsize=(5, 3))
            plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140, colors=colors, textprops={'fontsize': 7})
            plt.title(f"Market Share in {self.target_market}", fontsize=9)
            plt.axis('equal')
            plt.tight_layout()
            plt.savefig(pie_path, dpi=150)
            plt.close()
        else:
            pie_path = None

        return line_path, pie_path

    def build_mappings(self):
        """Calculates all metrics and creates the dictionary for Word replacement."""
        
        # --- Data Extraction ---
        tm_imports = self.safe_num(self.market.get('target_market_total_imports_usd'))
        world_imports = self.safe_num(self.market.get('world_total_imports_usd')) or 1.0
        
        tm_cagr = self.safe_num(self.market.get('target_market_growth_cagr_5y_pct'))
        world_cagr = self.safe_num(self.market.get('world_market_growth_cagr_5y_pct'))
        tm_last_year_growth = self.safe_num(self.market.get('target_market_growth_last_year_pct'))

        # Find "Your Country" in supplier list
        suppliers = self.comp.get('all_suppliers', [])
        yc_data = next((s for s in suppliers if s.get('name') == self.your_country), {})
        
        yc_val = self.safe_num(yc_data.get('value_usd'))
        yc_share = self.safe_num(yc_data.get('market_share_pct'))
        yc_cagr = self.safe_num(yc_data.get('growth_cagr_pct'))
        
        # --- Unit Values (Handling Lists) ---
        uv_data_raw = self.data.get('unit_values', {}).get('target_market_avg_unit_value_usd')
        uv_market = self.safe_num(uv_data_raw) 
        
        uv_yc = self.safe_num(yc_data.get('unit_value_latest'))

        # --- Logic & Text Generation ---
        growth_compare = "higher" if tm_cagr > world_cagr else "lower"
        share_trend = "increasing" if tm_cagr > world_cagr else "decreasing"
        is_sustained = "sustained" if (tm_cagr > 0 and tm_last_year_growth > 0) else "not sustained"
        last_year_trend = "growing" if tm_last_year_growth > 0 else "contracting"
        yc_share_trend = "gained" if yc_cagr > tm_cagr else "lost"
        uv_compare = "higher than" if uv_yc > uv_market else "lower than"
        uv_trend = "appreciating" if tm_cagr > 0 else "fluctuating"
        conc_level = self.comp.get('concentration_level', 'unknown')

        # --- Dictionary Construction ---
        self.replacements = {
            # Header Info
            "[Name of Country]": self.target_market,
            "[Target Market]": self.target_market,
            "[Target market]": self.target_market,
            "[Your country]": self.your_country,
            "[Your Country]": self.your_country,
            "[product]": f"HS {self.hs_code}",
            "HS 281511": f"HS {self.hs_code}",
            
            # Summary Section
            "[world_rank]": str(self.summary.get('target_market_world_rank', 'N/A')),
            "[capital_city]": "See Country Profile", 
            "[population]": "See Country Profile",
            "[currency]": "N/A",
            
            # Size
            "[tm_total_imports]": f"{tm_imports:,.0f}",
            "[tm_share_of_world]": f"{(tm_imports / world_imports * 100):.2f}",
            "[imports_from_yc]": f"{yc_val:,.0f}",
            "[yc_share_of_tm]": f"{yc_share:.2f}",
            
            # Growth
            "[tm_growth_cagr]": f"{tm_cagr:.2f}",
            "[tm_vs_world_growth]": growth_compare,
            "[world_growth_cagr]": f"{world_cagr:.2f}",
            "[tm_share_trend]": share_trend,
            "[sustained / not sustained]": is_sustained,
            "[tm_last_year_trend]": last_year_trend,
            "[tm_last_year_growth]": f"{tm_last_year_growth:.2f}",
            "[yc_growth_cagr]": f"{yc_cagr:.2f}",
            "[yc_share_change]": yc_share_trend,
            
            # Unit Values
            "58,630 USD/ unit": f"{uv_market:,.0f} USD/unit",
            "[more than/less than]": uv_compare,
            "[appreciated/depreciated]": uv_trend,
            "[country X]": suppliers[0]['name'] if len(suppliers) > 0 else "N/A",
            "[country Y]": suppliers[-1]['name'] if len(suppliers) > 0 else "N/A",
            "[rather heterogeneous/somewhat homogeneous]": "heterogeneous" if len(suppliers) > 10 else "homogeneous",
            
            # Competition
            "[not concentrated / moderately concentrated / concentrated]": conc_level,
            "[your_region]": "your region",
        }

    def _process_placeholders(self, doc):
        """Iterates through paragraphs and tables to replace text."""
        def replace_in_text(text):
            for key, val in self.replacements.items():
                if key in text:
                    text = text.replace(key, str(val))
            return text

        for p in doc.paragraphs:
            if "[" in p.text:
                p.text = replace_in_text(p.text)

        for table in doc.tables:
            for row in table.rows:
                for cell in row.cells:
                    for p in cell.paragraphs:
                        if "[" in p.text:
                            p.text = replace_in_text(p.text)

    def _fill_tariff_table(self, doc):
        """Fills the Market Access/Tariff table."""
        target_table = None
        for t in doc.tables:
            if not t.rows: continue
            header_text = t.rows[0].cells[0].text.lower()
            if "tariff" in header_text or "code" in header_text:
                target_table = t
                break
        
        if not target_table:
            logger.warning("Tariff table not found in template.")
            return

        tariffs = self.access.get('customs_tariffs', [])
        
        for i in range(5):
            if i + 1 >= len(target_table.rows):
                if i < len(tariffs): target_table.add_row()
                else: break 
            
            row = target_table.rows[i + 1]
            if i < len(tariffs):
                item = tariffs[i]
                row.cells[0].text = self.hs_code
                desc = self.meta.get('product_description', 'Product')
                if len(row.cells) > 1: row.cells[1].text = desc[:50]
                
                rate = "N/A"
                for k, v in item.items():
                    if "Applied" in k or "MFN" in k:
                        rate = str(v)
                        break
                if len(row.cells) > 2: row.cells[2].text = rate
                for j in range(3, len(row.cells)):
                    row.cells[j].text = "-"
            else:
                for cell in row.cells: cell.text = ""

    def _fill_importers_table(self, doc):
        """Fills the Potential Business Partners table."""
        target_table = None
        for t in doc.tables:
            if not t.rows: continue
            if "company" in t.rows[0].cells[0].text.lower():
                target_table = t
                break
        
        if not target_table: return

        partners = self.data.get('potential_importers', [])
        
        for i in range(5):
            if i + 1 >= len(target_table.rows):
                if i < len(partners): target_table.add_row()
                else: break
            
            row = target_table.rows[i+1]
            if i < len(partners):
                p = partners[i]
                row.cells[0].text = p.get('name', 'N/A')
                if len(row.cells) > 1: row.cells[1].text = p.get('city', 'N/A')
                if len(row.cells) > 2: row.cells[2].text = p.get('website', 'N/A')
            else:
                for cell in row.cells: cell.text = ""

    def _insert_images(self, doc, line_path, pie_path):
        """Finds image placeholders and replaces them with generated graphs."""
        placeholders = {
            "[img_line_graph_placeholder]": line_path,
            "[img_pie_chart_placeholder]": pie_path
        }
        
        for p in doc.paragraphs:
            for ph, path in placeholders.items():
                if ph in p.text:
                    p.text = ""
                    if path and os.path.exists(path):
                        run = p.add_run()
                        run.add_picture(path, width=Inches(5.5))
                    else:
                        p.text = "[Graph Data Unavailable]"

    def process_document(self, template_path):
        logger.info("Loading template...")
        doc = Document(template_path)
        
        line_img, pie_img = self._generate_charts()
        self.build_mappings()
        
        # --- NEW: Save Mappings to JSON ---
        json_data_path = os.path.join(self.output_dir, 'factsheet_data.json')
        try:
            with open(json_data_path, 'w', encoding='utf-8') as f:
                json.dump(self.replacements, f, indent=4, ensure_ascii=False)
            logger.info(f"Factsheet data (JSON) saved to: {json_data_path}")
        except Exception as e:
            logger.error(f"Failed to save factsheet JSON: {e}")

        self._process_placeholders(doc)
        self._fill_tariff_table(doc)
        self._fill_importers_table(doc)
        self._insert_images(doc, line_img, pie_img)
        
        output_filename = f"Factsheet_{self.hs_code}_{self.target_market}.docx"
        output_filename = re.sub(r'[\\/*?:"<>|]', "", output_filename)
        save_path = os.path.join(self.output_dir, output_filename)
        
        doc.save(save_path)
        logger.info(f"Report saved to: {save_path}")

    def print_report(self):
        pass

def run(json_path, template_path, output_dir):
    gen = FactsheetGenerator(json_path, output_dir)
    gen.process_document(template_path)

if __name__ == "__main__":
    pass