# Automated Trade Data Analysis Suite

This project is a sophisticated orchestration engine designed to automate the collection, aggregation, and analysis of international trade data. It launches a suite of scrapers to gather information from various specialized sources, merges the data into a unified structure, and generates a comprehensive quantitative factsheet in both DOCX and PDF formats.

## Key Features

- **Multi-Source Data Aggregation**: Scrapes data from multiple websites:
    - **TradeMap**: For detailed import/export values, market size, growth trends, and supplier lists.
    - **MacMap**: For market access conditions like customs tariffs and regulatory requirements.
    - **Export Potential Map**: For unrealized export potential analysis.
    - **ePing**: For the latest regulatory alerts and notifications.
- **Parallel Execution**: Runs scrapers concurrently to significantly speed up data collection.
- **Configuration-Driven**: The entire process is controlled by simple JSON configuration files, allowing easy modification of scrapers, data points, and run parameters.
- **Robust Data Mapping**: A priority-based system merges data from different sources into a final, clean template, ensuring the most reliable data is used.
- **Automated Reporting**: Generates multiple outputs for each run:
    - A master `final_report.json` with all aggregated data.
    - Human-readable Markdown reports for process auditing.
    - A professional, chart--_enhanced **Quantitative Factsheet** in `.docx` and `.pdf` formats.

## System Architecture

The project follows a modular orchestrator pattern.

```
+----------------+      +---------------------------+      +--------------------+
|   main.py      |----->|   Orchestrator Engine     |----->|   Scraper Scripts  |
| (Entrypoint)   |      |  (orchestrator/engine.py) |      | (scrapers/*.py)    |
+----------------+      +-------------+-------------+      +----------+---------+
       ^                        | (Runs in Parallel)             | (Selenium)
       |                        |                                |
+------+----------+      +------v-------+      +----------------v-----------------+
|  run_config.json|      | Mapping &    |      |  Individual Scraper Outputs      |
|  (Input Params) |      | Merging Logic|----->|  (trademap.json, macmap.json...) |
+-----------------+      +--------------+      +----------------------------------+
                                |
                                v
+----------------------+      +--------------------+      +--------------------+
|  final_report.json   |<-----|   Reporting        |----->|  mapping_report.md |
|  (Aggregated Data)   |      | (orchestrator/*)   |      +--------------------+
+----------------------+      +---------+----------+
                                        |
                                        v
                               +---------------------+
                               |  Factsheet (.docx)  |
                               |  Factsheet (.pdf)   |
                               +---------------------+
```

1.  **`main.py`**: The entry point. It parses command-line arguments and `run_config.json` to define the parameters for the run (e.g., HS code, target country).
2.  **Orchestrator Engine**: The core logic that reads `config.json` to know *which* scrapers to run. It launches each scraper as an isolated subprocess, either sequentially or in parallel.
3.  **Scrapers**: Individual Python scripts that use Selenium to navigate a specific website, perform searches, and download data, saving their findings to a dedicated JSON output file.
4.  **Mapping & Merging**: After the scrapers finish, the orchestrator loads their JSON outputs. Using the `mappings` rules in `config.json`, it populates a master `template.json` structure.
5.  **Reporting**: Finally, the orchestrator generates all output files, including the final JSON, markdown audit reports, and the Word/PDF factsheets.

## Setup and Installation

**Prerequisites:**
*   Python 3.8+
*   Mozilla Firefox browser installed.
*   `geckodriver.exe` (Firefox WebDriver) placed in the project's root directory.

**Installation Steps:**

1.  **Clone the repository:**
    ```bash
    git clone <your-repository-url>
    cd <repository-directory>
    ```

2.  **Create and activate a virtual environment (recommended):**
    ```bash
    python -m venv venv
    # On Windows
    venv\Scripts\activate
    # On macOS/Linux
    source venv/bin/activate
    ```

3.  **Install the required Python packages:**
    ```bash
    pip install -r requirements.txt
    ```

4.  **Set up TradeMap credentials:**
    The TradeMap scraper requires login credentials. Set them as environment variables to avoid hardcoding:
    ```bash
    # On Windows (Command Prompt)
    set TRADEMAP_USER="your_email@example.com"
    set TRADEMAP_PASS="your_password"

    # On Windows (PowerShell)
    $env:TRADEMAP_USER="your_email@example.com"
    $env:TRADEMAP_PASS="your_password"

    # On macOS/Linux
    export TRADEMAP_USER="your_email@example.com"
    export TRADEMAP_PASS="your_password"
    ```

5.  **Ensure the factsheet template is present:**
    The file `Quantitative_Factsheet_Template.docx` must be in the project's root directory.

## How to Run

The primary entry point is `main.py`. You can configure a run by editing `config/run_config.json` or by overriding parameters via the command line.

**1. Basic Run (using `run_config.json`)**

Modify `config/run_config.json` to specify your desired HS code and countries. Then, simply run:
```bash
python main.py
```
All outputs will be saved to a new timestamped folder inside the `./runs/` directory.

**2. Overriding Parameters via Command Line**

You can override any parameter from the `run_config.json` file directly from the command line. This is useful for automated scripts or quick tests.

```bash
python main.py \
    --hs-code "851712" \
    --your-country-name "South Korea" \
    --your-country-id "410" \
    --target-market-name "Germany" \
    --target-market-id "276"
```

**3. Useful Flags**

-   `--sequential`: Forces scrapers to run one by one. Useful for debugging.
-   `--dry-run`: Skips scraper execution entirely. The orchestrator will try to map data from existing output files in the output directory.
-   `--outdir <path>`: Specify a different base directory for the run outputs.

## Output Directory Structure

For each run, a new directory is created (e.g., `runs/20251117_103000/`), containing:

-   `final_report.json`: The master JSON file with all aggregated data.
-   `Factsheet_[Market]_[HSCode].docx`: The generated Word document factsheet.
-   `Factsheet_[Market]_[HSCode].pdf`: The generated PDF factsheet.
-   `mapping_report.md`: A human-readable report showing which source was used for each data point.
-   `review_checklist.md`: A list of fields that were not successfully filled and may need manual review.
-   `orchestrator.log`: The main log file for the orchestration process.
-   `scraper_name_output.json`: The raw JSON output from each individual scraper.
-   `/logs/`: A subdirectory containing detailed logs for each individual scraper run (`trademap.log`, `macmap.log`, etc.).
-   `/graphs/`: Contains the generated chart images.

## Project File Structure

```
.
├── config/
│   ├── config.json               # Master config: scrapers, priorities, mappings
│   ├── run_config.json           # Input parameters for a specific run
│   └── template.json             # The final, desired output data structure
├── orchestrator/
│   ├── engine.py                 # Core orchestration logic
│   ├── doc_generator.py          # Generates DOCX/PDF factsheets
│   ├── reporting.py              # Creates MD reports and final JSON
│   └── utils.py                  # Helper functions (logging, path access)
├── scrapers/
│   ├── trademap_scraper.py
│   ├── macmap_scraper.py
│   ├── potential_scraper.py
│   └── eping_scraper.py
├── support/
│   ├── spider_core.py            # Base class for Selenium scrapers
│   ├── data_downloader.py        # Advanced downloader for TradeMap
│   └── data_parser.py            # Parses raw .txt files from TradeMap
├── main.py                       # Main entry point for the application
├── geckodriver.exe               # Firefox WebDriver
├── requirements.txt              # Python package dependencies
└── Quantitative_Factsheet_Template.docx  # Word template for the final report
