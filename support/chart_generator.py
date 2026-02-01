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


def generate_pie_chart_market_shares(suppliers_data: list, output_path: str, title: str):
    """
    Generates a pie chart showing market shares of suppliers (last year data).
    
    Args:
        suppliers_data: List of supplier dicts with 'partner_country' and 'share_in_target_market_imports_pct'
        output_path: Path to save the pie chart image
        title: Title for the pie chart
    
    Returns:
        output_path if successful, None otherwise
    """
    try:
        if not suppliers_data:
            logging.warning("No supplier data provided for pie chart generation")
            return None
        
        # 1. Extract supplier names and market share percentages
        labels = []
        sizes = []
        colors = []
        
        # Color palette for pie slices
        color_palette = [
            '#FF6B6B', '#4ECDC4', '#45B7D1', '#FFA07A', '#98D8C8',
            '#F7DC6F', '#BB8FCE', '#85C1E2', '#F8B88B', '#ABEBC6',
            '#D7DBDD', '#AED6F1'
        ]
        
        # Sort by market share (descending)
        sorted_suppliers = sorted(
            [s for s in suppliers_data if s.get('partner_country') not in ['World', 'Total', 'nan']],
            key=lambda x: float(x.get('share_in_target_market_imports_pct', 0) or 0),
            reverse=True
        )
        
        # Collect top suppliers and group others if necessary
        if len(sorted_suppliers) > 10:
            # Keep top 10 individually, group rest as "Others"
            top_suppliers = sorted_suppliers[:10]
            other_share = sum([float(s.get('share_in_target_market_imports_pct', 0) or 0) 
                             for s in sorted_suppliers[10:]])
            
            for supplier in top_suppliers:
                labels.append(supplier.get('partner_country', 'Unknown'))
                sizes.append(float(supplier.get('share_in_target_market_imports_pct', 0) or 0))
            
            if other_share > 0:
                labels.append('Others')
                sizes.append(other_share)
        else:
            # Use all suppliers
            for supplier in sorted_suppliers:
                labels.append(supplier.get('partner_country', 'Unknown'))
                sizes.append(float(supplier.get('share_in_target_market_imports_pct', 0) or 0))
        
        # Assign colors
        colors = color_palette[:len(labels)]
        
        # 2. Create pie chart
        fig, ax = plt.subplots(figsize=(12, 8))
        
        wedges, texts, autotexts = ax.pie(
            sizes,
            labels=labels,
            autopct='%1.1f%%',
            startangle=90,
            colors=colors,
            textprops={'fontsize': 10}
        )
        
        # Enhance text formatting
        for autotext in autotexts:
            autotext.set_color('white')
            autotext.set_fontweight('bold')
            autotext.set_fontsize(9)
        
        # Enhance labels
        for text in texts:
            text.set_fontsize(10)
        
        ax.set_title(title, fontsize=14, fontweight='bold', pad=20)
        
        # 3. Save pie chart
        os.makedirs(os.path.dirname(output_path), exist_ok=True)
        plt.savefig(output_path, bbox_inches='tight', dpi=100)
        plt.close()
        
        logging.info(f"Pie chart generated: {output_path}")
        return output_path
    
    except Exception as e:
        logging.error(f"Pie chart generation failed: {e}")
        return None