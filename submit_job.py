import requests
import time
import json

# Replace with your actual server address and port
API_BASE_URL = "http://localhost:8000" 

def submit_analysis_job():
    """
    Submits a POST request to the /analyze endpoint.
    """
    
    # --- 1. Define the Analysis Parameters ---
    # Example: HS Code 847130 (Portable digital automatic data processing machines)
    # from 'Your Country' (Germany) to 'Target Market' (China)
    payload = {
        "hs_code": "847130",
        "your_country_id": "", # Leaving ID empty to test name resolution in main.py
        "your_country_name": "Germany",
        "target_market_id": "", 
        "target_market_name": "China",
        "sequential": False,
        "dry_run": False
    }

    headers = {
        'Content-Type': 'application/json'
    }

    print("Submitting new analysis job...")
    try:
        response = requests.post(f"{API_BASE_URL}/analyze", headers=headers, data=json.dumps(payload))
        response.raise_for_status() # Raise exception for bad status codes (4xx or 5xx)
        
        job_info = response.json()
        job_id = job_info.get("job_id")
        print(f"✅ Job submitted successfully!")
        print(f"   Job ID: **{job_id}**")
        print(f"   Status: {job_info.get('message')}")
        
        # --- 2. Poll for Status (Optional) ---
        poll_status(job_id)

    except requests.exceptions.RequestException as e:
        print(f"❌ Error submitting job: {e}")

def poll_status(job_id):
    """
    Repeatedly checks the job status until it is completed or failed.
    """
    print("\nStarting status check...")
    status = ""
    while status not in ["completed", "failed"]:
        time.sleep(5) # Wait 5 seconds between checks
        
        try:
            response = requests.get(f"{API_BASE_URL}/status/{job_id}")
            response.raise_for_status()
            job_status = response.json()
            status = job_status.get("status")
            error = job_status.get("error")
            
            print(f"Current Status: **{status.upper()}**", end='\r')
            
            if status == "failed":
                print(f"\n❌ Job FAILED. Error: {error}")
                break
            
            if status == "completed":
                print("\n🎉 Job COMPLETED! Results available.")
                download_results(job_id)
                break
                
        except requests.exceptions.RequestException as e:
            print(f"\n❌ Error checking status: {e}")
            break

def download_results(job_id):
    """
    Attempts to download the final report JSON.
    """
    print("\nAttempting to download final_report.json...")
    
    try:
        response = requests.get(f"{API_BASE_URL}/results/{job_id}/json")
        response.raise_for_status()

        # Assuming the FileResponse returns the correct filename
        filename = response.headers.get("Content-Disposition", f"report_{job_id}.json").split("filename=")[-1].strip('"')
        
        with open(filename, 'wb') as f:
            f.write(response.content)
            
        print(f"✅ Download successful! Report saved as **{filename}**")

    except requests.exceptions.RequestException as e:
        print(f"❌ Error downloading JSON report: {e}")


if __name__ == "__main__":
    submit_analysis_job()