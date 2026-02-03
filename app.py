import streamlit as st
import os
import shutil
import json
import sys
from types import SimpleNamespace

# Import your existing logic
# Ensure the directory is in path so we can import main
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
from main import run_orchestration

# Page Config
st.set_page_config(page_title="Trade Scraper Orchestrator", layout="wide")

def create_zip_archive(source_dir, output_filename):
    """Compresses a directory into a zip file for download."""
    shutil.make_archive(output_filename, 'zip', source_dir)
    return f"{output_filename}.zip"

def main():
    st.title("🌍 Trade Scraper Orchestrator")
    st.markdown("Generate trade factsheets, scrape data from TradeMap/MacMap/ePing, and download reports.")

    # --- Sidebar: Configuration ---
    st.sidebar.header("Configuration")
    
    # Inputs mirroring the CLI arguments
    hs_code = st.sidebar.text_input("HS Code", value="090111")
    your_country = st.sidebar.text_input("Your Country Name", value="Rwanda")
    target_market = st.sidebar.text_input("Target Market Name", value="France")
    
    st.sidebar.markdown("---")
    st.sidebar.subheader("Advanced Settings")
    dry_run = st.sidebar.checkbox("Dry Run (Skip Scraping)", value=False, help="Runs the logic without triggering the actual web scrapers.")
    timeout = st.sidebar.number_input("Timeout (seconds)", value=600)
    
    # File paths (defaulting to what's in your script)
    config_path = st.sidebar.text_input("Config Path", "config/config.json")
    country_list_path = st.sidebar.text_input("Country List Path", "m49-list-with-itc.json")
    
    # --- Main Execution Area ---
    st.subheader("Run Paramaters")
    col1, col2, col3 = st.columns(3)
    with col1:
        st.info(f"**HS Code:** {hs_code}")
    with col2:
        st.info(f"**Origin:** {your_country}")
    with col3:
        st.info(f"**Target:** {target_market}")

    # State to hold the result path after running
    if "output_path" not in st.session_state:
        st.session_state.output_path = None

    # --- Button to Start ---
    if st.button("🚀 Run Orchestration", type="primary"):
        if not hs_code or not your_country or not target_market:
            st.error("Please fill in HS Code, Your Country, and Target Market.")
        else:
            with st.status("Running Orchestrator...", expanded=True) as status:
                try:
                    # 1. Mock the argparse arguments object
                    # We create a SimpleNamespace to mimic the 'args' object main.py expects
                    mock_args = SimpleNamespace(
                        run_config="config/run_config.json", # Default
                        country_list=country_list_path,
                        hs_code=hs_code,
                        your_country_id=None, # Let script resolve it
                        target_market_id=None, # Let script resolve it
                        your_country_name=your_country,
                        target_market_name=target_market,
                        config=config_path,
                        template="config/template.json",
                        outdir="./runs",
                        timeout=timeout,
                        dry_run=dry_run,
                        sequential=False # Default to parallel
                    )

                    st.write("Initializing orchestration...")
                    
                    # 2. Call the main function directly
                    # Note: capture stdout if you want to show logs in UI, 
                    # but simple status updates work for now.
                    output_dir = run_orchestration(mock_args)
                    
                    st.session_state.output_path = output_dir
                    
                    status.update(label="✅ Orchestration Complete!", state="complete", expanded=False)
                    st.success(f"Files generated in: {output_dir}")

                except Exception as e:
                    status.update(label="❌ Error occurred", state="error")
                    st.error(f"An error occurred during execution: {e}")
                    st.exception(e)

    # --- Download Section ---
    if st.session_state.output_path and os.path.exists(st.session_state.output_path):
        st.divider()
        st.header("📂 Downloads")
        
        out_dir = st.session_state.output_path
        factsheet_path = os.path.join(out_dir, "factsheet_data.json")
        
        col_d1, col_d2 = st.columns(2)

        # 1. Download specific Factsheet JSON
        with col_d1:
            if os.path.exists(factsheet_path):
                with open(factsheet_path, "r", encoding="utf-8") as f:
                    factsheet_data = f.read()
                
                st.download_button(
                    label="📄 Download Factsheet Data (JSON)",
                    data=factsheet_data,
                    file_name="factsheet_data.json",
                    mime="application/json"
                )
            else:
                st.warning("factsheet_data.json was not found.")

        # 2. Download Entire Output Folder (Zipped)
        with col_d2:
            # Create a zip of the folder
            zip_name = f"run_output_{os.path.basename(out_dir)}"
            zip_path = create_zip_archive(out_dir, os.path.join("runs", zip_name))
            
            with open(zip_path, "rb") as f:
                st.download_button(
                    label="📦 Download Full Output Folder (ZIP)",
                    data=f,
                    file_name=f"{zip_name}.zip",
                    mime="application/zip"
                )
            
            # Preview Images if they exist
            st.subheader("Image Preview")
            scraper_results_dir = os.path.join(out_dir, "scraper_results")
            
            # Check for images in base dir or scraper results
            image_extensions = ['.png', '.jpg', '.jpeg']
            images_found = []
            
            # Walk through output to find images
            for root, dirs, files in os.walk(out_dir):
                for file in files:
                    if any(file.lower().endswith(ext) for ext in image_extensions):
                        images_found.append(os.path.join(root, file))
            
            if images_found:
                img_cols = st.columns(3)
                for i, img_path in enumerate(images_found):
                    with img_cols[i % 3]:
                        st.image(img_path, caption=os.path.basename(img_path), use_container_width=True)
            else:
                st.info("No images generated in this run.")

if __name__ == "__main__":
    main()