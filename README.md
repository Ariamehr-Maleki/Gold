***

# Automated Trade Data Analysis Suite

This project is a sophisticated orchestration engine designed to automate the collection, aggregation, and analysis of international trade data. It launches a suite of scrapers to gather information from various specialized sources, merges the data into a unified structure, and generates a comprehensive quantitative factsheet in both DOCX and PDF formats.

## Key Features

- **Multi-Source Data Aggregation**:
    - **TradeMap**: Detailed import/export values, market size, growth trends, supplier lists, and company contact data.
    - **MacMap**: Market access conditions, customs tariffs (MFN vs Preferential), and regulatory requirements (NTMs).
    - **Export Potential Map**: Unrealized export potential analysis.
    - **ePing**: Latest SPS/TBT regulatory alerts and notifications.
- **Visual Analytics**: Automatically generates line charts for trade trends and pie charts for market share analysis.
- **Intelligent Automation**:
    - **Parallel Execution**: Runs scrapers concurrently for speed.
    - **CAPTCHA Solving**: Integrated OCR (using `ddddocr` and `Tesseract`) to handle TradeMap login and verification barriers automatically.
    - **Robust Navigation**: Custom Selenium logic to handle dynamic .aspx form states and popups.
- **User Interfaces**:
    - **Web Dashboard**: A Streamlit-based UI for easy configuration, visualization, and one-click downloading.
    - **CLI**: A command-line interface for advanced batch processing and automation.
- **Automated Reporting**: Generates a professional **Quantitative Factsheet** (`.docx`/`.pdf`), a raw data JSON bundle, and audit logs.

## System Architecture

The project follows a modular orchestrator pattern with two entry points (`app.py` or `main.py`).

```
+----------------+      +----------------+
|    app.py      |      |    main.py     |
| (Streamlit UI) |      | (CLI Backend)  |
+-------+--------+      +--------+-------+
        |                        |
        +----------+-------------+
                   |
        +----------v----------------+      +--------------------+
        |   Orchestrator Engine     |----->|   Scraper Scripts  |
        | (orchestrator/engine.py)  |      | (scrapers/*.py)    |
        +-------------+-------------+      +----------+---------+
                      |                               | (Selenium/Requests)
                      |                               v
+---------------------v-----+            +--------------------------+
| Data Mapping & Merging    |<-----------| Raw Scraper Outputs      |
| (factsheet_assembler.py)  |            | (JSON, Excel snapshots)  |
+-------------+-------------+            +--------------------------+
              |
              v
+-----------------------------+      +-----------------------+
| Reports & Visuals           |----->| Final Output Folder   |
| (doc_generator, charts)     |      | (ZIP, PDF, DOCX, JSON)|
+-----------------------------+      +-----------------------+
```

## Project File Structure

```text
.
├── app.py                            # Streamlit Web UI entry point
├── main.py                           # CLI entry point
├── config/
│   ├── config.json                   # Master config: scrapers, priorities
│   ├── run_config.json               # Default input parameters
│   └── template.json                 # Final data structure schema
├── orchestrator/
│   ├── engine.py                     # Core logic
│   ├── utils.py                      # Logging and helpers
│   └── ...
├── scrapers/                         # Individual extraction scripts
│   ├── trademap_scraper.py
│   ├── macmap_scraper.py
│   ├── potential_scraper.py
│   └── eping_scraper.py
├── support/                          # Shared libraries
│   ├── spider_core.py                # Selenium base class + Captcha solving
│   ├── data_downloader.py            # TradeMap specific navigation
│   ├── data_parser.py                # HTML/Excel table parsing logic
│   ├── chart_generator.py            # Matplotlib chart creation
│   ├── factsheet_assembler.py        # Logic to build the final report structure
│   ├── macmap_formatter.py           # MacMap specific formatting
│   └── country_info_service.py       # API calls for population/GDP
├── geckodriver.exe                   # Firefox WebDriver
├── requirements.txt                  # Python dependencies
└── Quantitative_Factsheet_Template.docx  # Word template
```

## Setup and Installation

### Prerequisites
1.  **Python 3.8+**
2.  **Mozilla Firefox** browser installed.
3.  **GeckoDriver**: Ensure `geckodriver.exe` is in the project root or system PATH.
4.  **OCR Tools** (for CAPTCHA solving):
    *   **Tesseract OCR**: Install [Tesseract](https://github.com/UB-Mannheim/tesseract/wiki) and ensure the executable path is correct in `support/spider_core.py`.

### Installation Steps

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd <repository-directory>
    ```

2.  **Create virtual environment:**
    ```bash
    python -m venv venv
    # Windows
    venv\Scripts\activate
    # Mac/Linux
    source venv/bin/activate
    ```

3.  **Install dependencies:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set TradeMap Credentials:**
    The scraper requires valid credentials to access data. Set them as environment variables:
    
    *Windows (PowerShell):*
    ```powershell
    $env:TRADEMAP_USER="your_email@example.com"
    $env:TRADEMAP_PASS="your_password"
    ```
    *Mac/Linux:*
    ```bash
    export TRADEMAP_USER="your_email@example.com"
    export TRADEMAP_PASS="your_password"
    ```

## How to Run

### Option 1: Web Interface (Recommended)
The Streamlit dashboard offers the easiest way to run the tool, visualize progress, and download results.

1.  Run the app:
    ```bash
    streamlit run app.py
    ```
2.  Open your browser to the URL shown (usually `http://localhost:8501`).
3.  Enter the **HS Code**, **Your Country**, and **Target Market**.
4.  Click **Run Orchestration**.
5.  Once complete, download the **Full Output ZIP** or the Factsheet JSON directly.

### Option 2: Command Line (Advanced)
Use the CLI for automated scripts or server environments.

**Basic Run:**
```bash
python main.py
```
*Uses settings from `config/run_config.json`.*

**Run with Overrides:**
```bash
python main.py \
    --hs-code "090111" \
    --your-country-name "Rwanda" \
    --target-market-name "France" \
    --timeout 900
```



## Output Directory Structure

For every run, a timestamped folder is created (e.g., `runs/20251117_103000/`):

-   **`factsheet_data.json`**: The clean, structured data used to populate the Word template.
-   **`final_reportNew.json`**: The raw aggregated data from all sources.
-   **`Factsheet_[Market]_[HSCode].docx`**: The final quantitative report.
-   **`scraper_results/`**: Folder containing the raw JSON output from every scraper.
-   **`logs/`**: Detailed execution logs (`trademap.log`, `macmap.log`).
-   **`graphs/`**: Generated `.png` charts used in the report.
