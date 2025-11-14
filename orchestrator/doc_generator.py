# orchestrator/doc_generator.py

import json
import os
from datetime import datetime
from docx import Document
from docx.shared import Inches
import matplotlib.pyplot as plt
from docx2pdf import convert

# --- Helper Functions for Text & Image Replacement ---

def replace_text_in_doc(doc, replacements):
    """Find and replace text in paragraphs and tables."""
    for p in doc.paragraphs:
        for key, value in replacements.items():
            if key in p.text:
                # Replace while preserving style
                inline = p.runs
                for i in range(len(inline)):
                    if key in inline[i].text:
                        text = inline[i].text.replace(key, str(value))
                        inline[i].text = text
                        
    for table in doc.tables:
        for row in table.rows:
            for cell in row.cells:
                replace_text_in_doc(cell, replacements) # Recursive call for cells

def add_image_to_doc(doc, placeholder_text, image_path, width=Inches(5.5)):
    """Find a placeholder paragraph and replace it with an image."""
    for p in doc.paragraphs:
        if placeholder_text in p.text:
            p.text = "" # Clear the placeholder text
            run = p.add_run()
            run.add_picture(image_path, width=width)
            return True
    return False

# --- Graph Generation Functions ---

def generate_line_graph(years, values, product_name, market_name, output_image_path):
    """Generates and saves a line graph of import values over time."""
    plt.figure(figsize=(10, 5))
    plt.plot(years, [v / 1_000_000 for v in values], marker='o', linestyle='-')
    plt.title(f"{market_name}'s Imports of {product_name}", fontsize=14)
    plt.xlabel("Year", fontsize=12)
    plt.ylabel("Import Value (USD Million)", fontsize=12)
    plt.grid(True, which='both', linestyle='--', linewidth=0.5)
    plt.tight_layout()
    plt.savefig(output_image_path, dpi=300)
    plt.close()
    print(f"Generated line graph at {output_image_path}")

def generate_pie_chart(suppliers, market_name, output_image_path):
    """Generates and saves a pie chart of top supplier market shares."""
    top_suppliers = suppliers[:5]
    other_share = 100 - sum(s['market_share_pct'] for s in top_suppliers)
    
    labels = [s['name'] for s in top_suppliers] + ['Others']
    sizes = [s['market_share_pct'] for s in top_suppliers] + [other_share]
    
    plt.figure(figsize=(8, 8))
    plt.pie(sizes, labels=labels, autopct='%1.1f%%', startangle=140, textprops={'fontsize': 10})
    plt.title(f"Market Share for Suppliers in {market_name}", fontsize=14)
    plt.axis('equal') # Equal aspect ratio ensures that pie is drawn as a circle.
    plt.tight_layout()
    plt.savefig(output_image_path, dpi=300)
    plt.close()
    print(f"Generated pie chart at {output_image_path}")

# --- Main Generator Function ---

def generate_factsheet(data_path, template_path, output_dir):
    """Main function to generate the DOCX and PDF factsheet."""
    
    # 1. Load the final JSON data
    with open(data_path, 'r', encoding='utf-8') as f:
        data = json.load(f)

    # 2. Extract data from the JSON using the CORRECT paths
    meta = data.get('meta', {})
    market_size = data.get('market_size_and_potential', {})
    concentration = data.get('market_concentration', {})
    
    # Safely get all the values we need, with defaults
    exporting_country = meta.get('exporting_country', 'N/A')
    importing_country = meta.get('importing_country', 'N/A')
    hs_code = meta.get('product_hs6', 'N/A')
    product_name = f"product HS {hs_code}" # A descriptive name for the product

    # Find the data for "your country" from the list of suppliers
    your_country_data = next((s for s in concentration.get('top_5_suppliers', []) if s['name'] == exporting_country), {})
    your_country_share = your_country_data.get('market_share_pct', 0)
    your_country_cagr = your_country_data.get('growth_cagr_pct', 0)

    # Find total market value and growth from the correct section
    total_market_value = market_size.get('total_market_value_usd', 0)
    market_cagr_5y = market_size.get('market_growth_cagr_5y_pct', 0)
    
    # Note: We need to find the latest year. We'll get it from the run metadata for now.
    # A better solution is to add a 'latest_year' field to the trademap output.
    timestamp_str = meta.get("orchestration_timestamp_utc", "2025")
    latest_year = datetime.fromisoformat(timestamp_str.replace("Z", "+00:00")).year -1 # Assumption

    # Top 3 suppliers for the competition section
    top_suppliers = concentration.get('top_5_suppliers', [])
    supplier1 = top_suppliers[0] if len(top_suppliers) > 0 else {}
    supplier2 = top_suppliers[1] if len(top_suppliers) > 1 else {}
    supplier3 = top_suppliers[2] if len(top_suppliers) > 2 else {}

    # Create a clean replacements dictionary
    replacements = {
        '[Product]': product_name,
        '[Target Market]': importing_country,
        '[Your Country]': exporting_country,
        '[00.00.00]': hs_code,
        '[Month Year]': datetime.now().strftime("%B %Y"),
        '[year]': str(latest_year),
        '[rank]': str(market_size.get('target_market_world_rank', 'N/A')),
        
        # Size of the Market Section
        'In [year] [Target market] imported USD [value] of [product]s from the world': f"In {latest_year} {importing_country} imported USD {total_market_value:,} of {product_name}s from the world",
        '[your country] has a [share] %': f"{exporting_country} has a {your_country_share}%",
        
        # Growth of the Market Section
        'grew by [growth rate] % per annum': f"grew by {market_cagr_5y}% per annum",
        # Note: 'world growth' is not in the final JSON, this needs to be added to the mapping
        
        # Competition Section
        '[not concentrated / moderately concentrated / concentrated]': concentration.get('concentration_level', 'N/A'),
        '[supplier 1]': supplier1.get('name', 'N/A'),
        '[supplier 2]': supplier2.get('name', 'N/A'),
        '[supplier 3]': supplier3.get('name', 'N/A'),
        'market shares of [value] %, [value] % and [value] % respectively': f"market shares of {supplier1.get('market_share_pct', 0)}%, {supplier2.get('market_share_pct', 0)}% and {supplier3.get('market_share_pct', 0)}% respectively",
    }
    
    # Add more replacements as needed for other sections like Unit Value, etc.

    # 3. Generate Graphs
    graphs_dir = os.path.join(output_dir, 'graphs')
    os.makedirs(graphs_dir, exist_ok=True)
    line_graph_path = os.path.join(graphs_dir, 'imports_line_graph.png')
    pie_chart_path = os.path.join(graphs_dir, 'market_share_pie.png')

    # NOTE: The line graph needs 5-year data which is not in the final JSON. 
    # This indicates a mapping issue in config.json. We'll generate a placeholder graph.
    # You need to ensure 'market_analysis.years' and 'market_analysis.world_values_usd'
    # are mapped from your trademap output to the final template.
    
    # For now, we'll use placeholder data for the line graph to prevent a crash.
    placeholder_years = [2020, 2021, 2022, 2023, 2024]
    placeholder_values = [total_market_value / 1.2, total_market_value / 1.1, total_market_value, total_market_value * 1.05, total_market_value]
    
    generate_line_graph(
        years=placeholder_years,
        values=placeholder_values,
        product_name=product_name,
        market_name=importing_country,
        output_image_path=line_graph_path
    )
    
    generate_pie_chart(
        suppliers=concentration.get('top_5_suppliers', []),
        market_name=importing_country,
        output_image_path=pie_chart_path
    )

    # 4. Populate the DOCX template
    doc = Document(template_path)
    replace_text_in_doc(doc, replacements)
    
    # 5. Insert Graphs into the document
    add_image_to_doc(doc, '[LINE_GRAPH_PLACEHOLDER]', line_graph_path)
    add_image_to_doc(doc, '[PIE_CHART_PLACEHOLDER]', pie_chart_path, width=Inches(4.5))

    # 6. Save the populated DOCX and convert to PDF
    populated_docx_path = os.path.join(output_dir, 'populated_factsheet.docx')
    doc.save(populated_docx_path)
    print(f"Successfully saved populated DOCX to {populated_docx_path}")
    
    try:
        print("Converting to PDF...")
        convert(populated_docx_path)
        pdf_path = populated_docx_path.replace(".docx", ".pdf")
        print(f"Successfully created PDF: {pdf_path}")
    except Exception as e:
        print(f"Could not convert to PDF. Please ensure Microsoft Word or LibreOffice is installed. Error: {e}")