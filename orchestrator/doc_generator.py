# orchestrator/doc_generator.py (Refactored)

import json
import os
from datetime import datetime
from docx import Document
from docx.shared import Inches
import matplotlib.pyplot as plt
from docx2pdf import convert
import logging

# It's good practice to have a logger in this file as well.
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

# --- Helper Functions (Unchanged) ---

def replace_text_in_doc(doc, replacements):
    """Find and replace text in paragraphs and tables."""
    for p in doc.paragraphs:
        # Handle simple replacements
        for key, value in replacements.items():
            if key in p.text:
                inline = p.runs
                for i in range(len(inline)):
                    if key in inline[i].text:
                        text = inline[i].text.replace(key, str(value))
                        inline[i].text = text

    # Handle replacements in tables
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                # Recursive call for cells
                replace_text_in_doc(cell, replacements)

def add_image_to_doc(doc, placeholder_text, image_path, width=Inches(5.5)):
    """Find a placeholder paragraph and replace it with an image."""
    for p in doc.paragraphs:
        if placeholder_text in p.text:
            p.text = ""  # Clear the placeholder text
            run = p.add_run()
            try:
                run.add_picture(image_path, width=width)
                return True
            except FileNotFoundError:
                logging.error(f"Image not found at {image_path}. Cannot add it to the document.")
                return False
    return False

# --- Graph Generation Functions (Unchanged) ---

def generate_line_graph(years, values, product_name, market_name, output_image_path):
    """Generates and saves a line graph of import values over time."""
    if not years or not values or len(years) != len(values):
        logging.warning("Line graph generation skipped due to invalid years or values.")
        return
    plt.figure(figsize=(10, 5))
    plt.plot(years, [v / 1_000_000 for v in values], marker='o', linestyle='-')
    plt.title(f"{market_name}'s Imports of {product_name}", fontsize=14)
    plt.xlabel("Year", fontsize=12)
    plt.ylabel("Import Value (USD Million)", fontsize=12)
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.tight_layout()
    plt.savefig(output_image_path, dpi=300)
    plt.close()
    logging.info(f"Generated line graph at {output_image_path}")

def generate_pie_chart(suppliers, market_name, output_image_path):
    """Generates and saves a pie chart of top supplier market shares."""
    if not suppliers:
        logging.warning("Pie chart generation skipped because no supplier data was provided.")
        return
    top_suppliers = suppliers[:5]
    other_share = max(0, 100 - sum(s.get('market_share_pct', 0) for s in top_suppliers))

    labels = [s.get('name', 'N/A') for s in top_suppliers] + ['Others']
    sizes = [s.get('market_share_pct', 0) for s in top_suppliers] + [other_share]

    plt.figure(figsize=(8, 8))
    plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140, textprops={'fontsize': 10})
    plt.title(f"Market Share for Suppliers in {market_name}", fontsize=14)
    plt.axis('equal')
    plt.tight_layout()
    plt.savefig(output_image_path, dpi=300)
    plt.close()
    logging.info(f"Generated pie chart at {output_image_path}")


# --- Main Generator Function (Refactored) ---

def generate_factsheet(data_path, template_path, output_dir):
    """Main function to generate the DOCX and PDF factsheet."""

    # 1. Load the final JSON data
    logging.info(f"Loading final data from {data_path}")
    try:
        with open(data_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except (FileNotFoundError, json.JSONDecodeError) as e:
        logging.critical(f"Failed to load or parse data file: {e}")
        return

    # 2. Consolidate Data Extraction from different JSON sections
    # Using .get() with default empty dicts/lists prevents KeyErrors
    meta = data.get('meta', {})
    config = data.get('config', {})
    market_analysis = data.get('market_analysis', {})
    importer_ranking = data.get('importer_ranking', {})
    your_country_exports = data.get('your_country_total_exports', {})
    world_comparison = data.get('world_comparison_data', {})

    # Basic Info
    exporting_country = config.get('your_country', 'N/A')
    importing_country = config.get('target_market', 'N/A')
    hs_code = config.get('hs_code', 'N/A')
    product_name = f"product HS {hs_code}"
    latest_year = market_analysis.get('latest_year', datetime.now().year - 1)

    # Key Figures for the report
    total_exports_from_your_country = your_country_exports.get('value_usd', 0)
    target_market_world_rank = importer_ranking.get('target_market_world_rank', 'N/A')
    target_market_total_imports = market_analysis.get('total_value_usd', 0)
    world_total_imports = importer_ranking.get('world_total_imports_usd', 0)
    
    # --- FIX: Calculate share of world imports ---
    target_market_world_share = 0
    if world_total_imports > 0:
        target_market_world_share = round((target_market_total_imports / world_total_imports) * 100, 2)
    
    # Supplier and Competition Data
    all_suppliers = market_analysis.get('suppliers_full_list', [])
    your_country_data = next((s for s in all_suppliers if s.get('name') == exporting_country), {})
    your_country_value_in_market = your_country_data.get('value_usd', 0)
    your_country_share_in_market = your_country_data.get('market_share_pct', 0)
    your_country_cagr_in_market = your_country_data.get('growth_cagr_pct', 0)

    top_3_suppliers = all_suppliers[:3]
    supplier1 = top_3_suppliers[0] if len(top_3_suppliers) > 0 else {}
    supplier2 = top_3_suppliers[1] if len(top_3_suppliers) > 1 else {}
    supplier3 = top_3_suppliers[2] if len(top_3_suppliers) > 2 else {}

    # Growth Data
    market_cagr_5y = market_analysis.get('market_growth_cagr_pct', 0)
    world_import_cagr = world_comparison.get('world_import_growth_cagr_pct', 0)
    market_growth_last_year = market_analysis.get('market_growth_last_year_pct', 0)
    concentration_level = market_analysis.get('concentration', 'N/A')

    # 3. Create a comprehensive replacements dictionary
    replacements = {
        # --- Introduction & Summary ---
        '[Product]': product_name,
        '[Target Market]': importing_country,
        '[Your Country]': exporting_country,
        '[00.00.00]': hs_code,
        '[Month Year]': datetime.now().strftime("%B %Y"),
        '[year]': str(latest_year),
        'USD [value]': f"USD {total_exports_from_your_country:,}",
        '[rank]': str(target_market_world_rank),
        
        # --- Size of the Market Section (now with calculated world share) ---
        'In [year] [Target market] imported USD [value] of [product]s from the world':
            f"In {latest_year} {importing_country} imported USD {target_market_total_imports:,} of {product_name}s from the world",
        'which represented [share] % of world imports':
            f"which represented {target_market_world_share}% of world imports of the product",
        '[Target market] imported USD [value] of the product from [your country]':
            f"{importing_country} imported USD {your_country_value_in_market:,} of the product from {exporting_country}",
        'means [your country] has a [share] %':
            f"means {exporting_country} has a {your_country_share_in_market}%",
        
        # --- Growth of the Market Section ---
        "grew by [growth rate] % per annum": f"grew by {market_cagr_5y}% per annum", # First instance
        "world’s growth in imports of [product], which grew by [growth rate] %":
            f"world’s growth in imports of {product_name}, which grew by {world_import_cagr}%",
        "the market [growing / contracting] by [growth rate] %":
            f"the market {'growing' if market_growth_last_year >= 0 else 'contracting'} by {market_growth_last_year}%",
        "The value of [Target market]’s imports from [your country] grew by [growth rate] % per annum":
             f"The value of {importing_country}’s imports from {exporting_country} grew by {your_country_cagr_in_market}% per annum",
        
        # --- Competition Section ---
        '[not concentrated / moderately concentrated / concentrated]': concentration_level,
        '[supplier 1]': supplier1.get('name', 'N/A'),
        '[supplier 2]': supplier2.get('name', 'N/A'),
        '[supplier 3]': supplier3.get('name', 'N/A'),
        'market shares of [value] %, [value] % and [value] % respectively':
            f"market shares of {supplier1.get('market_share_pct', 0)}%, {supplier2.get('market_share_pct', 0)}% and {supplier3.get('market_share_pct', 0)}% respectively",
    }
    
    # 4. Generate Graphs using real data
    graphs_dir = os.path.join(output_dir, 'graphs')
    os.makedirs(graphs_dir, exist_ok=True)
    line_graph_path = os.path.join(graphs_dir, 'imports_line_graph.png')
    pie_chart_path = os.path.join(graphs_dir, 'market_share_pie.png')

    # --- FIX: Use actual data from the JSON for the line graph ---
    generate_line_graph(
        years=market_analysis.get('years', []),
        values=market_analysis.get('world_values_usd', []),
        product_name=product_name,
        market_name=importing_country,
        output_image_path=line_graph_path
    )
    
    generate_pie_chart(
        suppliers=all_suppliers,
        market_name=importing_country,
        output_image_path=pie_chart_path
    )

    # 5. Populate the DOCX template
    logging.info(f"Loading DOCX template from {template_path}")
    doc = Document(template_path)
    
    replace_text_in_doc(doc, replacements)
    
    # 6. Insert Graphs into the document
    logging.info("Adding generated graphs to the document...")
    if not add_image_to_doc(doc, '[LINE_GRAPH_PLACEHOLDER]', line_graph_path):
        logging.warning("Could not find '[LINE_GRAPH_PLACEHOLDER]' in the document.")
        
    if not add_image_to_doc(doc, '[PIE_CHART_PLACEHOLDER]', pie_chart_path, width=Inches(4.5)):
        logging.warning("Could not find '[PIE_CHART_PLACEHOLDER]' in the document.")


    # 7. Save the populated DOCX and convert to PDF
    populated_docx_path = os.path.join(output_dir, f'Factsheet_{importing_country}_{hs_code}.docx')
    doc.save(populated_docx_path)
    logging.info(f"Successfully saved populated DOCX to {populated_docx_path}")
    
    try:
        logging.info("Attempting to convert DOCX to PDF...")
        convert(populated_docx_path)
        pdf_path = populated_docx_path.replace(".docx", ".pdf")
        logging.info(f"Successfully created PDF: {pdf_path}")
    except Exception as e:
        logging.error(f"Could not convert to PDF. Please ensure Microsoft Word or a compatible program is installed. Error: {e}")