# orchestrator/reporting.py
import json
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

def generate_final_output(data: Dict, path: str):
    """Writes the final, filled template to a JSON file."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def generate_mapping_report_json(report_data: Dict, path: str):
    """Writes the machine-readable mapping report to a JSON file."""
    with open(path, 'w', encoding='utf-8') as f:
        json.dump(report_data, f, indent=2, ensure_ascii=False)

def generate_mapping_report_md(report_data: Dict, path: str):
    """Generates a human-readable markdown report of the mapping process."""
    lines = [
        "# Mapping Report",
        f"\nGenerated on: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
    ]
    for field, report in sorted(report_data.items()):
        chosen = report['chosen_candidate']
        lines.append(f"## ` {field} `\n")
        lines.append(f"- **Winning Source**: `{chosen['scraper']}` (Priority: {chosen['priority']})")
        lines.append(f"- **Source Key**: `{chosen['source_path']}`")
        lines.append(f"- **Value**: `{str(chosen['value'])[:100]}`")
        
        if len(report['all_candidates']) > 1:
            lines.append("- **Other Candidates**:")
            for cand in report['all_candidates']:
                if cand != chosen:
                    lines.append(f"  - `{cand['scraper']}` (P: {cand['priority']}) with value: `{str(cand['value'])[:50]}`")
        lines.append("\n---\n")

    with open(path, 'w', encoding='utf-8') as f:
        f.write("\n".join(lines))

def generate_checklist_md(final_template: Dict, path: str):
    """Generates a checklist of fields that remain null in the final template."""
    unfilled_fields = []

    def find_null_fields(d: Any, current_path: str = ''):
        if isinstance(d, dict):
            for k, v in d.items():
                new_path = f"{current_path}.{k}" if current_path else k
                if isinstance(v, (dict, list)):
                    find_null_fields(v, new_path)
                elif v is None and not new_path.startswith('meta'):
                    unfilled_fields.append(new_path)
        elif isinstance(d, list):
            for i, item in enumerate(d):
                find_null_fields(item, f"{current_path}[{i}]")

    find_null_fields(final_template)

    with open(path, 'w', encoding='utf-8') as f:
        f.write("# Manual Review Checklist\n\n")
        f.write("The following fields in the template were not filled by the orchestrator and may require manual review:\n\n")
        if unfilled_fields:
            for field in sorted(unfilled_fields):
                f.write(f"- [ ] `{field}`\n")
        else:
            f.write("All fields were successfully mapped from a source!\n")