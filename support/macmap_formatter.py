# support/macmap_formatter.py

class MacMapReportBuilder:
    # Update __init__ to accept the new data
    def __init__(self, config, your_data, competitor_data, ntl_list, other_suppliers_data=None):
        self.config = config
        self.your_data = your_data
        self.competitor_data = competitor_data
        self.other_suppliers_data = other_suppliers_data or {} # <--- NEW
        self.ntl_list = ntl_list
        
        self.yc = config['your_country_id']
        self.tm = config['target_market_id']
        self.prod = config['hs_code']
        self.comp_ids = config.get('competitor_ids', [])

    def build(self):
        """Main method to construct the full JSON report."""
        
        first_code = self.ntl_list[0]['code'] if self.ntl_list else None
        base_info = self.your_data.get(first_code, {}) if first_code else {}
        
        tariff_table = self._build_tariff_table()
        has_advantage = self._check_advantage(tariff_table)
        
        agreements = base_info.get('identified_agreements', [])
        
        # TRQ Analysis
        trq_line = self._find_trq_line(base_info)
        trq_present = trq_line is not None
        
        remedies = base_info.get('trade_remedies', [])
        ntms = base_info.get('regulatory_requirements', [])

        # Process Links (RoO vs CoO)
        roo_text, coo_text, roo_links = self._process_rules_of_origin(base_info)

        report = {
            "Market_Access": {
                "_note": "Generated via scraping.",
                "Your_Country": self.yc,
                "Target_Market": self.tm,
                "Product": self.prod,

                # 1. Advantage Statement
                "Advantage_Statement": f"[{self.yc}] {'has' if has_advantage else 'does not have'} a preferential tariff advantage over key competitors in [{self.tm}] for [{self.prod}].",

                # 2. Other Suppliers Statement (NEW)
                "Other_Suppliers_Analysis": self._generate_other_suppliers_text(),

                # 3. RoO and CoO (UPDATED)
                "Rules_of_Origin_Compliance": {
                    "Statement": f"To benefit from preferential market access to [{self.tm}], exporters from [{self.yc}] must comply with Rules of Origin of the preferential trade agreement(s).",
                    "Rules_of_Origin_Link": roo_links[0]['url'] if roo_links else "Research required",
                    "Certificate_of_Origin_Info": coo_text or "The Certificate of Origin can be downloaded here (if available).",
                    "Obtaining_Info": "Contact local Chamber of Commerce for issuance details."
                },

                # 4. TRQ Details (UPDATED FIELDS)
                "Tariff_rate_quota": {
                    "Applied": "Yes" if trq_present else "No",
                    "Volume": trq_line.get('trq_details', 'N/A') if trq_present else "N/A",
                    "Application_Period": "See details (e.g., all year round)",
                    "Outside_Quota_Rate": self._find_outside_quota_rate(base_info), 
                    "Full_Details_Raw": trq_line.get('trq_details', '') if trq_present else ""
                },

                # 5. Other Duties
                "Other_Duties_And_Remedies": {
                    "Statement": f"Other duties applied by [{self.tm}] to imports of [{self.prod}] from [{self.yc}] include: {'; '.join([r['measure_type'] for r in remedies]) if remedies else 'No trade remedies identified.'}",
                    "Details": remedies
                },

                # 6. Table & NTMs
                "Tariff_Table": tariff_table,
                "Mandatory_market_access_requirements": ntms if ntms else ["No specific NTMs scraped."]
            }
        }
        return report

    def _generate_other_suppliers_text(self):
        """
        Analyzes the 'other' list to see who has preferential access.
        Relies on the first NTL code being present in the data.
        """
        if not self.other_suppliers_data or not self.ntl_list:
            return "No other top suppliers analyzed."

        suppliers_with_pref = []
        
        # We use the master list's first code as the key
        first_code = self.ntl_list[0]['code']
        
        for supplier_id, data_map in self.other_suppliers_data.items():
            # data_map will only contain this one key because of single_line_only=True
            s_info = data_map.get(first_code, {})
            
            s_tariffs = s_info.get('tariffs_detailed', [])
            if not s_tariffs: continue

            # Determine if they have a preference (Min Rate < MFN Rate)
            mfn_rate = 999.0
            min_rate = 999.0
            
            for t in s_tariffs:
                r = t.get('rate')
                if r is None: continue
                
                if t.get('is_mfn'):
                    mfn_rate = r
                
                if r < min_rate:
                    min_rate = r
            
            # If min_rate is effectively lower than MFN
            # (using a small epsilon for float comparison safety, though direct < usually works)
            if min_rate < mfn_rate:
                suppliers_with_pref.append(supplier_id)

        if suppliers_with_pref:
            return f"Apart from the top three suppliers, other top five suppliers facing preferential tariffs in [{self.tm}] include: {', '.join(suppliers_with_pref)}."
        else:
            return "None of the top five suppliers has preferential market access."
        
    def _find_trq_line(self, base_info):
        """Helper to extract the specific dictionary object containing TRQ info."""
        if 'tariffs_detailed' in base_info:
            for t in base_info['tariffs_detailed']:
                if t.get('has_trq'):
                    return t
        return None

    def _find_outside_quota_rate(self, base_info):
        """Attempts to find the MFN rate which is usually the outside quota rate."""
        if 'tariffs_detailed' in base_info:
            for t in base_info['tariffs_detailed']:
                if t.get('is_mfn'):
                    return t.get('rate_display', 'N/A')
        return "N/A"

    def _process_rules_of_origin(self, base_info):
        """Separates general RoO links from Certificate of Origin info."""
        roo_links = []
        coo_text = ""
        
        if 'tariffs_detailed' in base_info:
            for t in base_info['tariffs_detailed']:
                ag_details = t.get('agreement_details')
                if ag_details and 'links' in ag_details:
                    for l in ag_details['links']:
                        # Heuristic: Check title for "Certificate"
                        title_lower = l['title'].lower()
                        if "certificate" in title_lower or "proof" in title_lower:
                            coo_text += f" {l['title']}: {l['url']};"
                        else:
                            roo_links.append(l)

        # Remove duplicates
        unique_roo = [dict(t) for t in {tuple(d.items()) for d in roo_links}]
        
        roo_str = "These can be researched at: " + ", ".join([u['url'] for u in unique_roo])
        return roo_str, coo_text, unique_roo

    # ... [Keep _build_tariff_table, _get_min_rate_value, _get_best_line, _check_advantage as they were] ...
    
    # [You must include the existing methods here so the class is complete. 
    #  I am omitting them for brevity, but do not delete them from your file.]
    def _build_tariff_table(self):
        # ... (Same as previous file) ...
        rows = []
        for item in self.ntl_list:
            code = item['code']
            y_res = self.your_data.get(code, {})
            y_tariffs_list = y_res.get('tariffs_detailed', [])
            your_rate_val = self._get_min_rate_value(y_tariffs_list)
            your_rate_display = f"{your_rate_val}%" if your_rate_val is not None else "N/A"
            mfn_line = next((t for t in y_tariffs_list if t.get('is_mfn')), None)
            mfn_rate_display = mfn_line['rate_display'] if mfn_line else "N/A"

            comp_map = {}
            for i in range(3):
                key = f"Lowest_tariff_faced_by_Competitor_{chr(65+i)}"
                if i < len(self.comp_ids):
                    cid = self.comp_ids[i]
                    c_res = self.competitor_data.get(cid, {}).get(code, {})
                    c_list = c_res.get('tariffs_detailed', [])
                    c_val = self._get_min_rate_value(c_list)
                    c_display = f"{c_val}% ({cid})" if c_val is not None else f"N/A ({cid})"
                    comp_map[key] = c_display
                else:
                    comp_map[key] = "-"

            best_line = self._get_best_line(y_tariffs_list)
            notes = []
            if best_line:
                if best_line.get('has_trq'):
                    notes.append(f"Quota: {best_line.get('trq_details', 'Yes')}")
                ag_name = None
                if best_line.get('agreement_details') and 'name' in best_line['agreement_details']:
                    ag_name = best_line['agreement_details']['name']
                elif best_line.get('regime_name') and not best_line.get('is_mfn'):
                    ag_name = best_line['regime_name']
                if ag_name:
                     notes.append(f"Ref: {ag_name}")

            row = {
                "National_tariff_line_code_in_Target_Market": code,
                "Product_Description": item['desc'],
                "MFN_or_general_tariff": mfn_rate_display,
                "Lowest_tariff_faced_by_Your_Country": your_rate_display,
                "Notes": "; ".join(notes),
                **comp_map
            }
            rows.append(row)
        return rows

    def _get_min_rate_value(self, tariff_list):
        if not tariff_list: return None
        rates = [t['rate'] for t in tariff_list if t.get('rate') is not None]
        return min(rates) if rates else None

    def _get_best_line(self, tariff_list):
        if not tariff_list: return None
        sorted_list = sorted(tariff_list, key=lambda x: x['rate'] if x['rate'] is not None else 999999)
        return sorted_list[0] if sorted_list else None

    def _check_advantage(self, rows):
        for row in rows:
            try:
                y_str = row['Lowest_tariff_faced_by_Your_Country'].replace('%', '').strip()
                if y_str == "N/A": continue
                y_val = float(y_str)
                comp_vals = []
                for k, v in row.items():
                    if "Competitor" in k and v != "-":
                        val_part = v.split('%')[0].strip()
                        if val_part != "N/A":
                            comp_vals.append(float(val_part))
                if comp_vals and y_val < min(comp_vals):
                    return True
            except:
                continue
        return False