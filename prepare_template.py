import argparse
import os
import re
import logging
from docx import Document

# Setup basic logging for clear feedback
logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')

def prepare_template(original_path, output_path):
    """
    Reads an original DOCX template with human-readable placeholders and
    converts it into a machine-readable template by replacing them with
    structured keys.
    """
    if not os.path.exists(original_path):
        logging.error(f"FATAL: Original template not found at '{original_path}'")
        return

    # MAPPING FOR COMPLEX/AMBIGUOUS PLACEHOLDERS
    # These are processed first to avoid errors. The order is important.
    # (Original Text, New Text)
    complex_replacements = [
        # Size of Market
        ("In [year] [Target market] imported USD [value] of [product]s from the world", "In [year] [target_market] imported USD [tm_total_imports] of [product_name]s from the world"),
        ("represented [share] % of world imports of the product", "represented [tm_share_of_world] % of world imports of the product"),
        ("imported USD [value] of the product from [your country]", "imported USD [imports_from_yc] of the product from [your_country]"),
        ("means [your country] has a [share] % of [Target market]’s imports", "means [your_country] has a [yc_share_of_tm] % of [target_market]’s imports"),
        # Growth of Market
        ("grew by [growth rate] % per annum. This market performance was [better than / worse]", "grew by [tm_growth_cagr] % per annum. This market performance was [tm_vs_world_growth]"),
        ("world’s growth in imports of [product], which grew by [growth rate] %", "world’s growth in imports of [product_name], which grew by [world_growth_cagr] %"),
        ("[Target market] share in world imports of [product] has been [increasing / decreasing]", "[target_market] share in world imports of [product_name] has been [tm_share_trend]"),
        ("market [growing / contracting] by [growth rate] %", "market [tm_last_year_trend] by [tm_last_year_growth] %"),
        ("[Target market]’s imports from [your country] grew by [growth rate] % per annum", "[target_market]’s imports from [your_country] grew by [yc_growth_cagr] % per annum"),
        ("means [your country] [gained / lost] market share", "means [your_country] [yc_share_change] market share"),
        # Competition
        ("supply to [target market]’s market for [product] is [not concentrated / moderately concentrated / concentrated]", "supply to [target_market]’s market for [product_name] is [concentration]"),
        ("top three exporters, [supplier 1]; [supplier 2]; [supplier 3]", "top three exporters, [s1_name]; [s2_name]; [s3_name]"),
        ("market shares of [value] %, [value] % and [value] % respectively", "market shares of [s1_share] %, [s2_share] % and [s3_share] % respectively"),
        ("market share over the last five years include [supplier A]; [supplier B]; [supplier C]", "market share over the last five years include [suppliers_gaining_share]"),
        ("suppliers from [your region] include: [supplier X]; [supplier Y]; [supplier Z]", "suppliers from [your_region] include: [regional_competitors]"),
        # Market Access Table (example for the first row)
        ("[00.00.00.00.00]\t[product description]", "[tariff.0.code]\t[tariff.0.description]"),
    ]

    # MAPPING FOR SIMPLE, UNAMBIGUOUS PLACEHOLDERS
    simple_replacements = {
        '[Product]': '[product_name]',
        '[Target Market]': '[target_market]',
        '[Month Year]': '[month_year]',
        '[00.00.00]': '[hs_code]',
        '[Your Country]': '[your_country]',
        '[rank]': '[world_rank]',
        '[enter city]': '[capital_city]',
        '[latest data]': '[population]', # Assuming order: Pop, GDP, Currency, Lang
        # Add more if needed, but the complex ones handle most tricky cases
    }
    
    doc = Document(original_path)

    def perform_replacements(element):
        """Recursively performs replacements in paragraphs and table cells."""
        # Process paragraphs
        for p in element.paragraphs:
            # First, handle complex, full-sentence replacements
            for old_text, new_text in complex_replacements:
                if old_text in p.text:
                    p.text = p.text.replace(old_text, new_text)
                    logging.info(f"Replaced complex phrase: '{old_text}'")
            
            # Second, handle simple, single-word replacements
            for old, new in simple_replacements.items():
                if old in p.text:
                    p.text = p.text.replace(old, new)
                    logging.info(f"Replaced simple placeholder: '{old}' -> '{new}'")

        # Recurse into tables
        for table in element.tables:
            for row in table.rows:
                for cell in row.cells:
                    perform_replacements(cell)

    logging.info(f"Starting preparation of template: '{original_path}'")
    perform_replacements(doc)

    doc.save(output_path)
    logging.info(f"✅ Success! Prepared template saved to: '{output_path}'")

if __name__ == '__main__':
    parser = argparse.ArgumentParser(
        description="Converts a DOCX template with human-readable placeholders into a machine-readable version.",
        formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument(
        "--original",
        required=True,
        help="Path to the original .docx template with placeholders like '[Product]'."
    )
    parser.add_argument(
        "--output",
        required=True,
        help="Path to save the new, machine-readable .docx template (e.g., 'factsheet_prepared.docx')."
    )

    args = parser.parse_args()
    prepare_template(args.original, args.output)