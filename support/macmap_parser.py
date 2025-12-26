# support/macmap_parser.py

from bs4 import BeautifulSoup
import re
import logging

def clean_text(element):
    """Helper to safely extract and clean text."""
    if element:
        return " ".join(element.get_text(separator=" ").split())
    return None

def parse_macmap_html(html_content):
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # 1. Parse Summary Boxes (MFN/Pref Rates)
    summary_boxes = _parse_summary_boxes(soup)
    
    # 2. Parse Tariffs & Detect TRQs
    tariffs_raw, trq_info = _parse_tariff_section(soup) 
    
    # 3. Parse Remedies & NTMs
    remedies = _parse_remedies_section(soup)
    ntms = _parse_ntm_section(soup)

    # 4. Extract Agreements & RoO
    tariff_lines = []
    agreements = set()
    roo_links = []

    for item in tariffs_raw:
        if item['type'] == 'tariff_line':
            tariff_lines.append(item)
        elif item['type'] == 'agreement_detail':
            details = item.get('details', {})
            real_name = details.get('Agreement Name')
            if real_name: agreements.add(real_name)
            if 'RoO_Link' in details: roo_links.append(details['RoO_Link'])

    # 5. Determine Status
    # Logic: Benefits if an agreement is found OR if the summary box shows a Pref rate < MFN
    benefits_from = False
    if len(agreements) > 0:
        benefits_from = True
    elif summary_boxes.get('pref_rate') and summary_boxes.get('mfn_rate'):
         # Simple check if text differs, better logic relies on float comparison in scraper
         if summary_boxes['pref_rate'] != summary_boxes['mfn_rate']:
             benefits_from = True

    return {
        "summary": summary_boxes,
        "preferential_access_status": "benefits from" if benefits_from else "does not benefit from",
        "identified_agreements": list(agreements),
        "rules_of_origin_links": list(set(roo_links)),
        "tariffs": tariff_lines,
        "trq_info": trq_info,
        "trade_remedies": remedies,
        "regulatory_requirements": ntms
    }

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

def _parse_tariff_section(soup):
    section = soup.find(id="custom-duties-results")
    if not section: return [], {"has_trq": False, "details": []}

    rows = section.select("table tbody tr")
    results = []
    trq_found = False
    trq_details = []
    
    for row in rows:
        if not row.get_text(strip=True): continue

        # --- CASE A: Agreement Detail Block ---
        agreement_div = row.find(class_="result-fta")
        if agreement_div:
            agreement_info = {}
            content_rows = agreement_div.find_all(class_="content-row")
            for cr in content_rows:
                lbl = clean_text(cr.find(class_="lbl"))
                ctn_elem = cr.find(class_="ctn")
                ctn = clean_text(ctn_elem)
                
                if lbl:
                    if "Name" in lbl: agreement_info["Agreement Name"] = ctn
                    elif "In force" in lbl: agreement_info["In Force"] = ctn
                    
                    # Try to find Rules of Origin Link
                    link = ctn_elem.find('a') if ctn_elem else None
                    if link and "origin" in link.get('href', ''):
                        agreement_info['RoO_Link'] = link['href']

            if agreement_info:
                results.append({"type": "agreement_detail", "details": agreement_info})
            continue

        # --- CASE B: Standard Tariff Row ---
        cells = row.find_all('td', recursive=False)
        if len(cells) >= 3:
            regime = clean_text(cells[0])
            rate = clean_text(cells[1]).replace('%', '')
            
            # TRQ Detection
            if "quota" in regime.lower() or "iqtr" in regime.lower():
                trq_found = True
                trq_details.append(f"{regime}: {rate}")

            link = row.find('a', class_='tariff-regime-detail')
            ntl_code = None
            if link and link.has_attr('data-detail'):
                match = re.search(r'ntl=([0-9\.]+)', link['data-detail'])
                if match: ntl_code = match.group(1)

            is_mfn = "MFN" in regime if regime else False

            results.append({
                "type": "tariff_line",
                "national_tariff_line": ntl_code,
                "regime_name": regime,
                "tariff_rate": rate,
                "is_mfn": is_mfn
            })

    return results, {"has_trq": trq_found, "details": trq_details}

def _parse_remedies_section(soup):
    container = soup.find(id="trade-remedy")
    if not container: return []
    if "does not apply any trade remedy" in clean_text(container): return []

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
        summary_wrapper = row.find(class_='measure-summary-wrapper')
        if not summary_wrapper: continue
        full_title = clean_text(summary_wrapper)
        ntms.append(full_title)
    return ntms