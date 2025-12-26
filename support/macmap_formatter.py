# support/macmap_formatter.py

class MacMapReportBuilder:
    def __init__(self, config, your_data, competitor_data, ntl_list):
        self.config = config
        self.your_data = your_data
        self.competitor_data = competitor_data
        self.ntl_list = ntl_list
        
        # Unpack config for easier access
        self.yc = config['your_country_id']
        self.tm = config['target_market_id']
        self.prod = config['hs_code']
        self.comp_ids = config.get('competitor_ids', [])

    def build(self):
        """Main method to construct the full JSON report."""
        
        # 1. Analyze high-level status (using the first NTL line as a proxy for general status)
        first_code = self.ntl_list[0]['code'] if self.ntl_list else None
        base_info = self.your_data.get(first_code, {}) if first_code else {}
        
        # 2. Build the detailed table
        tariff_table = self._build_tariff_table()
        
        # 3. Determine Advantage Logic
        has_advantage = self._check_advantage(tariff_table)
        
        # 4. Extract Agreements & TRQs
        agreements = base_info.get('identified_agreements', [])
        trq_info = base_info.get('trq_info', {})
        remedies = base_info.get('trade_remedies', [])
        ntms = base_info.get('regulatory_requirements', [])

        # 5. Populate the Template
        report = {
            "Market_Access": {
                "_note": "Developer note: Literal template mirror of the Market Access section.",

                "Your_Country": self.yc,
                "Target_Market": self.tm,
                "Product": self.prod,

                "Your_Country_benefits_from_or_does_not_benefit_from_preferential_market_access_in_Target_Market_for_Product": 
                    base_info.get('preferential_access_status', 'does not benefit from'),

                "Relevant_preferential_trade_agreements": 
                    ", ".join(agreements) if agreements else "None identified",

                "Tariff_Table": tariff_table,

                "Short_analysis_of_tariffs_and_tariff_rate_quotas_if_applicable_for_example": 
                    self._generate_short_analysis(base_info, has_advantage),

                "your_country_has_or_does_not_have_a_preferential_tariff_advantage_over_key_competitors_in_target_market_for_product": 
                    "has" if has_advantage else "does not have",

                "Apart_from_the_top_three_suppliers_other_top_five_suppliers_facing_preferential_tariffs_in_target_market_include": 
                    "[Requires separate Trade Statistics Data]",

                "None_of_the_top_five_suppliers_has_preferential_market_access": 
                    "Verify with Trade Data.",

                "Rules_of_Origin_and_Certificate_of_Origin_information": 
                    self._generate_roo_text(base_info),

                "Tariff_rate_quota": {
                    "Target_market_applies_a_tariff_rate_quota_on_imports_of_product": 
                        "Yes" if trq_info.get('has_trq') else "No",
                    "Quota_volume": 
                        "See details in tariff table or 'Other duties' section" if trq_info.get('has_trq') else "N/A",
                    "Applied_period": 
                        "See official regulation" if trq_info.get('has_trq') else "N/A",
                    "Outside_quota_tariff_rate": 
                        "Check Tariff Table (General/MFN Rate)" if trq_info.get('has_trq') else "N/A"
                },

                "Other_duties_applied_by_Target_market_to_imports_of_product_from_Your_country": 
                    "; ".join([f"{r['measure_type']} ({r['status']})" for r in remedies]) if remedies else "No trade remedies identified.",

                "Mandatory_market_access_requirements_non_tariff_measures": {
                    "Summary_sentence": f"To export [{self.prod}] to [{self.tm}], exporters from [{self.yc}] need to comply with mandatory market access requirements (non-tariff measures).",
                    "Requirements_list": ntms if ntms else ["No specific NTMs scraped."],
                    "Web_links_to_further_sources": "Check MacMap or Local Ministry Website"
                }
            }
        }
        return report

    def _build_tariff_table(self):
        rows = []
        for item in self.ntl_list:
            code = item['code']
            y_res = self.your_data.get(code, {})
            y_tariffs = y_res.get('tariffs', [])

            # Get Your Rate
            your_rate = self._get_min_rate(y_tariffs)
            
            # Get MFN Rate
            mfn_line = next((t for t in y_tariffs if t.get('is_mfn')), None)
            mfn_rate = mfn_line['tariff_rate'] if mfn_line else y_res.get('summary', {}).get('mfn_rate', "N/A")

            # Build Competitor Columns
            comp_map = {}
            for i in range(3): # We need A, B, C
                key = f"Lowest_tariff_faced_by_Competitor_{chr(65+i)}" # A, B, C
                if i < len(self.comp_ids):
                    cid = self.comp_ids[i]
                    c_data = self.competitor_data.get(cid, {}).get(code, {})
                    val = self._get_min_rate(c_data.get('tariffs', []))
                    comp_map[key] = f"{val} ({cid})"
                else:
                    comp_map[key] = "-"

            row = {
                "National_tariff_line_code_in_Target_Market": code,
                "Product_Description": item['desc'],
                "MFN_or_general_tariff": mfn_rate,
                "Lowest_tariff_faced_by_Your_Country": your_rate,
                **comp_map
            }
            rows.append(row)
        return rows

    def _check_advantage(self, rows):
        """Returns True if Your Country has a lower rate than ALL competitors in ANY row."""
        for row in rows:
            try:
                y_val = self._parse_rate(row['Lowest_tariff_faced_by_Your_Country'])
                
                # Collect competitor rates
                comp_vals = []
                for k in row:
                    if "Competitor" in k and row[k] != "-":
                        # Value format might be "5.0 (China)", split it
                        val_str = row[k].split('(')[0].strip()
                        c_val = self._parse_rate(val_str)
                        if c_val is not None: comp_vals.append(c_val)
                
                if y_val is not None and comp_vals:
                    # Advantage = Your Rate < Min Competitor Rate
                    if y_val < min(comp_vals):
                        return True
            except:
                continue
        return False

    def _get_min_rate(self, tariffs):
        if not tariffs: return "N/A"
        rates = []
        for t in tariffs:
            val = self._parse_rate(t.get('tariff_rate'))
            if val is not None: rates.append(val)
        return str(min(rates)) if rates else "N/A"

    def _parse_rate(self, rate_str):
        """Safely converts string rate to float for comparison."""
        if not rate_str or rate_str == "N/A": return None
        try:
            # Handle "10%" or "10" or "Free"
            clean = rate_str.lower().replace('%', '').strip()
            if "free" in clean: return 0.0
            return float(clean)
        except:
            return None

    def _generate_short_analysis(self, base_info, has_advantage):
        adv_text = "has a preferential advantage" if has_advantage else "does not have a distinct tariff advantage"
        trq_text = "Subject to Tariff Rate Quotas." if base_info.get('trq_info', {}).get('has_trq') else "No TRQs identified."
        return f"[{self.yc}] {adv_text} in [{self.tm}] for this product. {trq_text}"

    def _generate_roo_text(self, base_info):
        links = base_info.get('rules_of_origin_links', [])
        link_text = f" Links: {', '.join(links)}" if links else ""
        return f"To benefit from preferential market access to [{self.tm}], exporters from [{self.yc}] must comply with Rules of Origin.{link_text}"