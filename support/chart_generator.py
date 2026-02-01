# support/chart_generator.py

import matplotlib.pyplot as plt
import pandas as pd
import os
import logging

def generate_chart_from_json(ts_data: list, output_path: str, title: str):
    """
    Generates a line chart from 'target_market_value_ts' data.
    """
    try:
        if not ts_data:
            return None

        # 1. Convert JSON to DataFrame
        rows = []
        for entry in ts_data:
            row = {'Partner': entry.get('partner_country')}
            # Flatten the time_series dictionary {'2020': 123, '2021': 456} into columns
            ts = entry.get('time_series', {})
            row.update(ts)
            rows.append(row)
        
        df = pd.DataFrame(rows)
        if df.empty: return None

        # 2. Sort columns (Years)
        year_cols = sorted([c for c in df.columns if str(c).isdigit()])
        if not year_cols: return None

        # Ensure numeric
        for y in year_cols:
            df[y] = pd.to_numeric(df[y], errors='coerce').fillna(0)

        # 3. Get Top 10 Partners by latest year (for target market, all are relevant partners)
        latest_year = year_cols[-1]
        plot_df = df.sort_values(by=latest_year, ascending=False).head(10)

        # 5. Plot all partner countries
        plt.figure(figsize=(10, 6))
        for _, row in plot_df.iterrows():
            label = row['Partner']
            values = row[year_cols].values
            plt.plot(year_cols, values, label=label, linewidth=2, marker='o')

        plt.title(title)
        plt.xlabel("Year")
        plt.ylabel("Value (USD)")
        plt.legend()
        plt.grid(True, linestyle=':', alpha=0.6)
        
        # Format Y Axis (Comma separators)
        plt.gca().get_yaxis().set_major_formatter(plt.FuncFormatter(lambda x, p: format(int(x), ',')))

        # 6. Save
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, bbox_inches='tight', dpi=100)
        plt.close()

        logging.info(f"Chart generated: {output_path}")
        return output_path

    except Exception as e:
        logging.error(f"Chart generation failed: {e}")
        return None