# support/macmap_parser.py

from bs4 import BeautifulSoup
import re
import logging

def clean_text(element):
    """Helper to safely extract and clean text."""
    if element:
        text = element.get_text(separator=" ", strip=True)
        return " ".join(text.split())
    return None

def parse_macmap_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Parse Header Info (Exporter, Importer, Product) - NEW
    header_info = _parse_header_info(soup)
    
    # 2. Parse Summary Boxes (Average Tariffs)
    summary_boxes = _parse_summary_boxes(soup)
    
    # 3. Parse Detailed Table
    tariff_data = _parse_detailed_tariff_table(soup)

    # 4. Categorize and Filter Agreement Names
    mfn_entries = [t for t in tariff_data if t.get('is_mfn')]
    pref_entries = [t for t in tariff_data if not t.get('is_mfn')]
    
    benefits_from = False
    
    # We use two sets to distinguish between specific names (CEPA) and generic ones (UAE)
    specific_agreements = set()
    generic_regimes = set()
    
    mfn_rate_val = 1000.0
    if mfn_entries and mfn_entries[0]['rate'] is not None:
        mfn_rate_val = mfn_entries[0]['rate']

    for p in pref_entries:
        # Check for specific Agreement Details first
        ag_details = p.get('agreement_details')
        if ag_details and 'name' in ag_details:
            specific_agreements.add(ag_details['name'])
        elif p.get('regime_name'):
            # Only fall back to regime name if no specific detail found
            clean_name = p['regime_name'].replace('Preferential tariff for ', '').strip()
            generic_regimes.add(clean_name)
        
        # Check advantage (Lower rate than MFN)
        if p['rate'] is not None and p['rate'] < mfn_rate_val:
            benefits_from = True

    # FINAL LOGIC: If we have specific names, ignore the generic country names
    if specific_agreements:
        final_agreements = list(specific_agreements)
    else:
        final_agreements = list(generic_regimes)

    return {
        "header_info": header_info, # <--- Added this to the return
        "summary_box_data": summary_boxes,
        "preferential_access_status": "benefits from" if benefits_from else "does not benefit from",
        "identified_agreements": final_agreements, 
        "tariffs_detailed": tariff_data,
        "trade_remedies": _parse_remedies_section(soup),
        "regulatory_requirements": _parse_ntm_section(soup)
    }

def _parse_header_info(soup):
    """
    Parses the top 'Overview' section to validate Exporter, Importer, and Product.
    """
    data = {"exporter": None, "importer": None, "product": None}
    
    # Look for the specific ID provided in your snippet
    wrapper = soup.find(id="overview-summary-wrapper")
    if not wrapper:
        # Fallback: try finding the class if ID is missing
        wrapper = soup.find(class_="overview-page-wrapper")
        
    if not wrapper: 
        return data

    # The data is organized in 'summary-group' divs
    groups = wrapper.find_all(class_="summary-group")
    
    for group in groups:
        heading_el = group.find(class_="summary-heading")
        text_el = group.find(class_="summary-text")
        
        if heading_el and text_el:
            heading = clean_text(heading_el).upper()
            text = clean_text(text_el)
            
            if "EXPORTING" in heading:
                data["exporter"] = text
            elif "IMPORTER" in heading:
                data["importer"] = text
            elif "PRODUCT" in heading:
                # The product text might be inside the ID 'collapseExample', but clean_text handles that
                data["product"] = text
                
    return data

def _parse_detailed_tariff_table(soup):
    section = soup.find(id="custom-duties-results")
    if not section: 
        return []

    rows = section.select("table tbody tr")
    tariff_lines = []
    current_tariff_obj = None

    for row in rows:
        row_id = str(row.get('id', ''))
        
        # --- TYPE 1: QUOTA ROW ---
        if 'quota-result' in row_id:
            if current_tariff_obj:
                quota_div = row.find(id=lambda x: x and 'quota-detail' in x)
                if quota_div:
                    text = clean_text(quota_div)
                    if text:
                        current_tariff_obj['trq_details'] = text
                        current_tariff_obj['has_trq'] = True
            continue

        # --- TYPE 2: AGREEMENT DETAILS ROW ---
        if 'fta-roo-result' in row_id:
            if current_tariff_obj:
                details = _extract_agreement_details(row)
                if details:
                    current_tariff_obj['agreement_details'] = details
            continue

        # --- TYPE 3: STANDARD TARIFF ROW ---
        cells = row.find_all('td', recursive=False)
        if len(cells) >= 3:
            regime_cell = cells[0]
            regime_text = clean_text(regime_cell)
            
            # Extract Rate
            rate_text_raw = clean_text(cells[1])
            rate_text = rate_text_raw.replace('%', '').strip() if rate_text_raw else ""
            
            try:
                if "free" in rate_text.lower(): rate_val = 0.0
                elif rate_text: rate_val = float(rate_text)
                else: rate_val = None
            except: rate_val = None

            ave_text = clean_text(cells[2]).replace('%', '').strip() if clean_text(cells[2]) else ""

            # Extract NTL Code link if available
            link = regime_cell.find('a', class_='tariff-regime-detail')
            ntl_code = None
            if link and link.has_attr('data-detail'):
                match = re.search(r'ntl=([0-9\.]+)', link['data-detail'])
                if match: ntl_code = match.group(1)

            is_mfn = "MFN" in regime_text if regime_text else False

            current_tariff_obj = {
                "type": "tariff_line",
                "ntl_code": ntl_code,
                "regime_name": regime_text,
                "rate_display": rate_text + "%" if rate_text and "free" not in rate_text.lower() else rate_text_raw,
                "rate": rate_val,
                "ave_display": ave_text + "%" if ave_text else "N/A",
                "is_mfn": is_mfn,
                "has_trq": False,
                "agreement_details": None
            }
            tariff_lines.append(current_tariff_obj)

    return tariff_lines

def _extract_agreement_details(row_element):
    """
    Parses the hidden details row. Uses recursive search to find content-rows.
    """
    data = {}
    agreement_div = row_element.find(class_="agreement-detail")
    if not agreement_div: return None

    # RECURSIVE FIND: The HTML is deeply nested.
    rows = agreement_div.find_all(class_="content-row")
    
    for r in rows:
        lbl_elem = r.find(class_="lbl")
        ctn_elem = r.find(class_="ctn")
        
        if not lbl_elem or not ctn_elem: continue
        
        lbl = clean_text(lbl_elem)
        ctn = clean_text(ctn_elem)

        if not lbl: continue

        # Case-insensitive check
        if "Name" in lbl: data['name'] = ctn
        elif "In force" in lbl: data['in_force'] = ctn
        elif "Type" in lbl: data['type'] = ctn
        elif "Member states" in lbl: data['members'] = ctn

    # Extract Links
    links = []
    anchors = agreement_div.find_all('a', href=True)
    for a in anchors:
        href = a['href']
        if ".pdf" in href or "findrulesoforigin" in href:
            text = clean_text(a) or "Link"
            links.append({"title": text, "url": href})
    
    if links: data['links'] = links

    return data if data else None

def _parse_summary_boxes(soup):
    summary = {"mfn_rate": None, "pref_rate": None}
    tariff_box = soup.find(id="overview-box-customs-tariffs")
    if tariff_box:
        infos = tariff_box.find_all(class_="customs-tariff-info")
        for info in infos:
            label = clean_text(info.find(class_="customs-tariff-rate-label"))
            rate = clean_text(info.find(class_="customs-tariff-rate-details"))
            if label:
                if "MFN" in label: summary["mfn_rate"] = rate
                if "Pref" in label or "PREF" in label.upper(): summary["pref_rate"] = rate
    return summary

def _parse_remedies_section(soup):
    container = soup.find(id="trade-remedy")
    if not container: return []
    txt = clean_text(container)
    if txt and "does not apply any trade remedy" in txt: return []
    remedies = []
    rows = container.select("table tbody tr")
    for row in rows:
        cols = row.find_all('td')
        if len(cols) > 2:
            remedies.append({
                "measure_type": clean_text(cols[1]),
                "status": clean_text(cols[2])
            })
    return remedies

def _parse_ntm_section(soup):
    container = soup.find(id="ntm-summary-results")
    if not container: return []
    ntms = []
    rows = container.find_all('tr', class_='toggle-trigger')
    
    for row in rows:
        # 1. Extract the Count
        count_div = row.find(class_='measure-count')
        count_str = clean_text(count_div) if count_div else "0"
        
        # 2. Extract the Text Description
        # Try finding the wrapper which contains the code + title
        wrapper = row.find(class_='measure-summary-wrapper')
        text_content = ""
        
        if wrapper:
            full_text = clean_text(wrapper)
            if full_text:
                # Remove "Learn more" clutter
                text_content = full_text.replace("Learn more", "").strip()
        else:
            # Fallback
            summary_div = row.find(class_='measure-summary')
            if summary_div:
                text_content = clean_text(summary_div).replace("Learn more", "").strip()

        # 3. Format: "(Count) Description"
        if text_content:
            # User requested the number "in front of" the agreement
            formatted_entry = f"({count_str}) {text_content}"
            ntms.append(formatted_entry)
            
    return ntms