# orchestrator/doc_generator.py (Corrected for Final Template)

import json
import os
from datetime import datetime
from docx import Document
from docx.shared import Inches
import matplotlib.pyplot as plt
from docx2pdf import convert
import logging

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')

def sanitize_filename(filename):
    """Removes characters that are invalid in Windows filenames."""
    # Ensure filename is a string before cleaning
    return "".join(c for c in str(filename) if c not in r'<>:"/\|?*')

# --- Helper Functions (Unchanged from before) ---

def replace_text_in_doc(doc, replacements):
    for p in doc.paragraphs:
        for key, value in replacements.items():
            if key in p.text:
                inline = p.runs
                for i in range(len(inline)):
                    if key in inline[i].text:
                        text = inline[i].text.replace(key, str(value))
                        inline[i].text = text
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                replace_text_in_doc(cell, replacements)

def add_image_to_doc(doc, placeholder_text, image_path, width=Inches(5.5)):
    for p in doc.paragraphs:
        if placeholder_text in p.text:
            p.text = ""
            run = p.add_run()
            try:
                run.add_picture(image_path, width=width)
                return True
            except FileNotFoundError:
                logging.error(f"Image not found at {image_path}.")
                return False
    return False

def generate_line_graph(years, values, product_name, market_name, output_image_path):
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
    if not suppliers:
        logging.warning("Pie chart generation skipped: no supplier data.")
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


# --- Main Generator Function (Refactored to match FINAL template) ---

def generate_factsheet(data_path, template_path, output_dir):
    """Main function to generate the DOCX and PDF factsheet."""
    logging.info(f"Loading final data from {data_path}")
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 2. Extract data from the JSON using the CORRECT paths from the final template.json
    meta = data.get('meta', {})
    summary = data.get('summary', {})
    market_data = data.get('market_size_and_growth', {})
    competition = data.get('competition_and_suppliers', {})
    historical = data.get('historical_data', {})

    exporting_country = meta.get('exporting_country', 'N/A')
    importing_country = meta.get('importing_country', 'N/A')
    hs_code = meta.get('product_hs6', 'N/A')
    product_name = f"product HS {hs_code}"
    years = historical.get('years', [])
    latest_year = years[-1] if years else datetime.now().year - 1

    total_exports_from_your_country = summary.get('your_country_total_exports_usd', 0)
    target_market_world_rank = summary.get('target_market_world_rank', 'N/A')
    target_market_total_imports = market_data.get('target_market_total_imports_usd', 0)
    world_total_imports = market_data.get('world_total_imports_usd', 0)
    
    target_market_world_share = round((target_market_total_imports / world_total_imports) * 100, 2) if world_total_imports else 0

    all_suppliers = competition.get('all_suppliers', [])
    your_country_data = next((s for s in all_suppliers if s.get('name') == exporting_country), {})
    your_country_value_in_market = your_country_data.get('value_usd', 0)
    your_country_share_in_market = your_country_data.get('market_share_pct', 0)
    your_country_cagr_in_market = your_country_data.get('growth_cagr_pct', 0)

    top_3_suppliers = all_suppliers[:3]
    supplier1 = top_3_suppliers[0] if len(top_3_suppliers) > 0 else {}
    supplier2 = top_3_suppliers[1] if len(top_3_suppliers) > 1 else {}
    supplier3 = top_3_suppliers[2] if len(top_3_suppliers) > 2 else {}

    market_cagr_5y = market_data.get('target_market_growth_cagr_5y_pct', 0)
    world_import_cagr = market_data.get('world_market_growth_cagr_5y_pct', 0)
    market_growth_last_year = market_data.get('target_market_growth_last_year_pct', 0)
    concentration_level = competition.get('concentration_level', 'N/A')

    # 3. Create a comprehensive replacements dictionary
    # New dictionary for doc_generator.py, matching your specific .docx template
    replacements = {
        '[product_name]': product_name.replace("product HS ", ""), # remove the prefix
        '[target_market]': importing_country,
        '[month_year]': datetime.now().strftime("%B %Y"),
        '[hs_code]': hs_code,
        '[your_country]': exporting_country,
        'USD [value]': f"USD {total_exports_from_your_country:,}",
        '[world_rank]': str(target_market_world_rank),
        'USD [tm_total_imports]': f"USD {target_market_total_imports:,}",
        '[tm_share_of_world]': str(target_market_world_share),
        'USD [imports_from_yc]': f"USD {your_country_value_in_market:,}",
        '[yc_share_of_tm]': str(your_country_share_in_market),
        '[tm_growth_cagr]': str(market_cagr_5y),
        '[world_growth_cagr]': str(world_import_cagr),
        '[tm_last_year_growth]': str(market_growth_last_year),
        '[yc_growth_cagr]': str(your_country_cagr_in_market),
        '[s1_name]': supplier1.get('name', 'N/A'),
        '[s2_name]': supplier2.get('name', 'N/A'),
        '[s3_name]': supplier3.get('name', 'N/A'),
        '[s1_share]': str(supplier1.get('market_share_pct', 0)),
        '[s2_share]': str(supplier2.get('market_share_pct', 0)),
        '[s3_share]': str(supplier3.get('market_share_pct', 0)),
        
        # You will also need to handle these dynamic phrases:
        # '[tm_vs_world_growth]', '[tm_share_trend]', '[sustained / not sustained]', 
        # '[tm_last_year_trend]', '[yc_share_change]'
        # We will handle these with simple logic right after the dict.
    }

    # --- Add this logic right below the replacements dictionary ---
    replacements['[tm_vs_world_growth]'] = "better" if market_cagr_5y > world_import_cagr else "worse"
    replacements['[tm_share_trend]'] = "increasing" if (market_cagr_5y > world_import_cagr) else "decreasing"
    replacements['[sustained / not sustained]'] = "sustained" if abs(market_growth_last_year) >= abs(market_cagr_5y) else "not sustained"
    replacements['[tm_last_year_trend]'] = "growing" if market_growth_last_year >= 0 else "contracting"
    replacements['[yc_share_change]'] = "gained" if your_country_cagr_in_market > market_cagr_5y else "lost"
    replacements['[suppliers_gaining_share]'] = "; ".join(competition.get('suppliers_gaining_share', []))
    replacements['[regional_competitors]'] = "; ".join([s['name'] for s in competition.get('regional_competitors', [])])
        
    graphs_dir = os.path.join(output_dir, 'graphs')
    os.makedirs(graphs_dir, exist_ok=True)
    line_graph_path = os.path.join(graphs_dir, 'imports_line_graph.png')
    pie_chart_path = os.path.join(graphs_dir, 'market_share_pie.png')

    generate_line_graph(
        years=historical.get('years', []),
        values=historical.get('target_market_import_values_usd', []),
        product_name=product_name,
        market_name=importing_country,
        output_image_path=line_graph_path
    )
    generate_pie_chart(
        suppliers=all_suppliers,
        market_name=importing_country,
        output_image_path=pie_chart_path
    )

    doc = Document(template_path)
    replace_text_in_doc(doc, replacements)
    add_image_to_doc(doc, "[Line graph of target market's total imports of the selected product in the last 5-10 years]", line_graph_path)
    add_image_to_doc(doc, "[Pie graph showing last year's market shares of", pie_chart_path, width=Inches(4.5))
    safe_market_name = sanitize_filename(importing_country)
    safe_hs_code = sanitize_filename(hs_code)
    populated_docx_path = os.path.join(output_dir, f'Factsheet_{safe_market_name}_{safe_hs_code}.docx')
    doc.save(populated_docx_path)
    logging.info(f"Successfully saved populated DOCX to {populated_docx_path}")
    
    try:
        logging.info("Attempting to convert DOCX to PDF...")
        convert(populated_docx_path)
    except Exception as e:
        logging.error(f"Could not convert to PDF: {e}")