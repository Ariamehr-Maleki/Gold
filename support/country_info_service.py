# support/country_info_service.py

import requests
import time
from datetime import datetime
from urllib.parse import quote
import logging

logger = logging.getLogger("CountryInfoService")


class CountryInfoService:
    def __init__(self, timeout=10, retries=2):
        self.timeout = timeout
        self.retries = retries

    # -------------------- low-level HTTP --------------------
    def _get(self, url):
        for attempt in range(self.retries + 1):
            try:
                r = requests.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    return r
                return r
            except requests.RequestException as e:
                logger.debug(f"HTTP error: {e}")
                if attempt < self.retries:
                    time.sleep(0.5 * (2 ** attempt))
        return None

    # -------------------- REST Countries --------------------
    def _fetch_restcountries(self, country_name):
        if not country_name:
            return {}

        url = f"https://restcountries.com/v3.1/name/{quote(country_name)}?fullText=true"
        r = self._get(url)

        if not r or r.status_code != 200:
            # fallback to fuzzy match
            url = f"https://restcountries.com/v3.1/name/{quote(country_name)}"
            r = self._get(url)
            if not r or r.status_code != 200:
                return {}

        data = r.json()
        if not isinstance(data, list) or not data:
            return {}

        c = data[0]

        currencies = c.get("currencies", {})
        languages = c.get("languages", {})

        return {
            "capital": (c.get("capital") or [None])[0],
            "population": c.get("population"),
            "currency": ", ".join(
                [f"{v.get('name')} ({k})" for k, v in currencies.items()]
            ) if currencies else None,
            "languages": ", ".join(languages.values()) if languages else None,
            "iso2": (c.get("cca2") or "").lower(),
            "profile_link": c.get("maps", {}).get("googleMaps")
        }

    # -------------------- World Bank --------------------
    def _fetch_worldbank_latest(self, iso2, indicator):
        if not iso2:
            return None, None

        current_year = datetime.now().year
        url = (
            f"http://api.worldbank.org/v2/country/{iso2}/indicator/"
            f"{indicator}?format=json&per_page=100&date=2010:{current_year}"
        )

        r = self._get(url)
        if not r or r.status_code != 200:
            return None, None

        payload = r.json()
        if not isinstance(payload, list) or len(payload) < 2:
            return None, None

        for row in payload[1]:
            if row and row.get("value") is not None:
                return row["value"], row["date"]

        return None, None

    # -------------------- PUBLIC API --------------------
    def get_country_profile(self, country_name):
        """
        Single public method.
        Returns a normalized dict with country info.
        """
        result = {
            "capital_city": "N/A",
            "population": "N/A",
            "population_year": "N/A",
            "gdp_per_capita_usd": "N/A",
            "gdp_per_capita_year": "N/A",
            "currency": "N/A",
            "languages": "N/A",
            "country_profile_link": "N/A"
        }

        rc = self._fetch_restcountries(country_name)

        if rc:
            result["capital_city"] = rc.get("capital") or "N/A"
            result["currency"] = rc.get("currency") or "N/A"
            result["languages"] = rc.get("languages") or "N/A"
            result["country_profile_link"] = rc.get("profile_link") or "N/A"

        iso2 = rc.get("iso2") if rc else None

        # GDP per capita
        gdp, gdp_year = self._fetch_worldbank_latest(iso2, "NY.GDP.PCAP.CD")
        if gdp is not None:
            result["gdp_per_capita_usd"] = f"{gdp:,.2f}"
            result["gdp_per_capita_year"] = gdp_year

        # Population (World Bank preferred)
        pop, pop_year = self._fetch_worldbank_latest(iso2, "SP.POP.TOTL")
        if pop is not None:
            result["population"] = f"{int(pop):,}"
            result["population_year"] = pop_year
        elif rc.get("population"):
            result["population"] = f"{int(rc['population']):,}"

        return result
