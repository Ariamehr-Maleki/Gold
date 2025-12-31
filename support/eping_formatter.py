import pandas as pd
from datetime import datetime

class EPingReportBuilder:
    def __init__(self, config, data_input):
        self.config = config
        # Handle input whether it's the full dict or just the list of notifications
        if isinstance(data_input, dict):
            self.raw_data = data_input.get("notifications", [])
        elif isinstance(data_input, list):
            self.raw_data = data_input
        else:
            self.raw_data = []

    def _clean_str(self, val):
        """
        Converts value to string, returning an empty string if the value 
        is None, NaN, or the string 'nan'.
        """
        if val is None or pd.isna(val):
            return ""
        
        s = str(val).strip()
        
        # Check for literal "nan" string which pandas sometimes leaves behind
        if s.lower() == 'nan':
            return ""
            
        return s

    def _clean_date(self, date_val):
        """Converts Excel dates to YYYY-MM-DD string, or empty string if missing."""
        if pd.isna(date_val) or date_val is None:
            return ""
        
        s_val = str(date_val).strip()
        if not s_val or s_val.lower() == 'nan':
            return ""

        try:
            # Handle standard pandas timestamps or string dates
            return pd.to_datetime(date_val).strftime('%Y-%m-%d')
        except:
            # If parsing fails, just return the string (sanitized)
            return s_val

    def _get_link(self, item):
        """Prioritizes English links, falls back to French/Spanish."""
        # Check EN, then FR, then ES
        for lang in ['EN', 'FR', 'ES']:
            key = f"Link to notification({lang})"
            val = item.get(key)
            cleaned_val = self._clean_str(val)
            if cleaned_val:
                return cleaned_val
        
        # Fallback to the generic 'Notified document' if others are empty
        fallback = item.get("Notified document")
        return self._clean_str(fallback)

    def build(self):
        notifications = []
        
        # Iterate through the raw data (rows from the Excel file)
        for item in self.raw_data:
            notif = {
                "symbol": self._clean_str(item.get("Document symbol")),
                "country": self._clean_str(item.get("Notifying Member")),
                "title": self._clean_str(item.get("Title")),
                "description": self._clean_str(item.get("Description")),
                "product_description": self._clean_str(item.get("Products covered")),
                "hs_codes": self._clean_str(item.get("HS code(s)")),
                "objectives": self._clean_str(item.get("Objectives")),
                "distribution_date": self._clean_date(item.get("Distribution date")),
                "comment_deadline": self._clean_date(item.get("Final date for comments")),
                "url": self._get_link(item)
            }
            notifications.append(notif)

        # Structure the final JSON for the template
        return {
            "meta": {
                "generated_at": datetime.now().strftime("%Y-%m-%d"),
                "hs_code_scraped": self.config.get("hs_code", "N/A"),
                "target_market": self.config.get("target_market_name", "Target Market"),
                "your_country": self.config.get("your_country_name", "Your Country")
            },
            "notifications": notifications
        }