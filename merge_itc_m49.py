import json
import re
import unicodedata

M49_FILE = "m49-list.json"
ITC_FILE = "extracted_country_codes.json"
OUT_FILE = "m49-list-with-itc.json"


# -----------------------------------------------------
# Normalization helpers
# -----------------------------------------------------

def normalize_country_name(name: str) -> str:
    """Normalize names so Iran (Islamic Republic of) == Iran, Islamic Republic of."""
    if not name:
        return ""

    # Remove accents
    name = unicodedata.normalize("NFKD", name)
    name = "".join(c for c in name if not unicodedata.combining(c))

    # Replace & remove punctuation
    name = name.replace("&", "and")
    name = re.sub(r"[(),']", " ", name)
    name = re.sub(r"[-]", " ", name)

    # Convert "Iran Islamic Republic of" & "Iran Republic Islamic" to same form
    name = name.replace("  ", " ")

    # Lowercase
    name = name.lower().strip()

    # Remove common fillers
    fillers = ["the ", "of ", "republic ", "state ", "states "]
    for f in fillers:
        name = name.replace(f, "")

    # Remove double spaces
    name = re.sub(r"\s+", " ", name).strip()

    return name


# Manual overrides for known tricky names
ALIASES = {
    "united states": "united states america",
    "usa": "united states america",
    "us": "united states america",
    "united states america": "united states america",

    "korea south": "south korea",
    "korea republic korea": "south korea",

    "korea north": "north korea",
    "korea democratic people s republic": "north korea",

    "iran islamic republic": "iran",
    "iran": "iran",

    "russian federation": "russia",
    "russia": "russia",
}


def alias(name: str) -> str:
    """Convert normalized name to alias if exists."""
    return ALIASES.get(name, name)


# -----------------------------------------------------
# Main merge logic
# -----------------------------------------------------

def load_json(path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def save_json(path, data):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=4)


def main():
    m49_data = load_json(M49_FILE)
    itc_data = load_json(ITC_FILE)

    # Build lookup with normalization
    itc_lookup = {}
    for item in itc_data:
        norm = alias(normalize_country_name(item["country"]))
        itc_lookup[norm] = str(item["code"]).strip()

    # Update each country
    for c in m49_data["countries"]:
        norm_m49 = alias(normalize_country_name(c["name"]))
        c["itcCode"] = itc_lookup.get(norm_m49, None)

    save_json(OUT_FILE, m49_data)
    print(f"Saved updated file → {OUT_FILE}")


if __name__ == "__main__":
    main()
