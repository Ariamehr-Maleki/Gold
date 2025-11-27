import os
import uuid
import json
import logging
import glob
from typing import Optional
from fastapi import FastAPI, BackgroundTasks, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
from types import SimpleNamespace

# Import your existing logic
# We import run_orchestration to leverage your existing wiring
from main import run_orchestration

# Setup logging for API
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("API")

app = FastAPI(title="Trade Data Orchestrator API")

# --- In-Memory Job Store (Use Redis/Database for production) ---
# Structure: { "job_id": { "status": "pending|running|completed|failed", "output_dir": "path", "error": None } }
JOBS = {}

# --- Pydantic Models for Input Validation ---
class AnalysisRequest(BaseModel):
    hs_code: str
    your_country_id: str
    your_country_name: str
    target_market_id: str
    target_market_name: str
    
    # Optional overrides matching main.py args
    sequential: bool = False
    dry_run: bool = False

# --- Helper Wrapper ---
def background_orchestrator_runner(job_id: str, request_data: AnalysisRequest):
    """
    Wraps the main.py run_orchestration function.
    """
    try:
        JOBS[job_id]["status"] = "running"
        
        # Define a fixed output directory for this job ID
        output_dir = os.path.join(os.getcwd(), "runs", job_id)
        os.makedirs(output_dir, exist_ok=True)
        JOBS[job_id]["output_dir"] = output_dir

        # Mock the 'args' object that main.py expects
        # We point config/template to the default locations
        mock_args = SimpleNamespace(
            config="config/config.json",
            template="config/template.json",
            run_config="config/run_config.json", # Can be ignored as we override below
            outdir=os.path.dirname(output_dir), # Parent dir, run_orchestration creates subdir
            timeout=600,
            dry_run=request_data.dry_run,
            sequential=request_data.sequential,
            
            # CLI Overrides
            hs_code=request_data.hs_code,
            your_country_id=request_data.your_country_id,
            your_country_name=request_data.your_country_name,
            target_market_id=request_data.target_market_id,
            target_market_name=request_data.target_market_name
        )

        # CRITICAL: We need to modify main.py slightly or trick it regarding output folders.
        # Your main.py creates a timestamp folder inside 'outdir'.
        # To make retrieval easier, we will modify run_orchestration logic locally 
        # OR just scan the folder after execution.
        
        # Let's run it. 
        # NOTE: Orchestrator creates a timestamped folder inside mock_args.outdir.
        # To keep it simple, let's pass "runs" as outdir, and later we find the specific timestamp folder created.
        
        mock_args.outdir = os.path.join(os.getcwd(), "runs", "jobs") # distinct folder for api jobs
        
        # Execute existing logic
        run_orchestration(mock_args)

        # After execution, we need to find where exactly it saved.
        # Since main.py uses datetime to name folders, we assume the latest folder 
        # in 'runs/jobs' created in the last few seconds is ours, 
        # OR (Cleaner) we rely on the orchestrator logs/logic. 
        
        # For this specific setup, let's locate the most recently created folder in the output dir
        list_of_dirs = glob.glob(os.path.join(mock_args.outdir, "*"))
        if not list_of_dirs:
            raise Exception("Orchestrator did not create an output directory.")
            
        latest_dir = max(list_of_dirs, key=os.path.getctime)
        JOBS[job_id]["actual_output_path"] = latest_dir
        JOBS[job_id]["status"] = "completed"
        logger.info(f"Job {job_id} completed. Data at {latest_dir}")

    except Exception as e:
        logger.error(f"Job {job_id} failed: {e}")
        JOBS[job_id]["status"] = "failed"
        JOBS[job_id]["error"] = str(e)

# --- Endpoints ---

@app.post("/analyze", status_code=202)
async def start_analysis(request: AnalysisRequest, background_tasks: BackgroundTasks):
    """
    Submit a new analysis job. Returns a Job ID to track progress.
    """
    job_id = str(uuid.uuid4())
    JOBS[job_id] = {
        "status": "pending", 
        "request": request.dict(),
        "submitted_at": str(os.path.getctime(os.getcwd())) # generic timestamp
    }
    
    background_tasks.add_task(background_orchestrator_runner, job_id, request)
    
    return {
        "job_id": job_id,
        "status": "pending",
        "message": "Analysis started in background. Check /status/{job_id} for updates."
    }

@app.get("/status/{job_id}")
async def get_job_status(job_id: str):
    """
    Check the status of a specific job.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job ID not found")
    
    job = JOBS[job_id]
    return {
        "job_id": job_id,
        "status": job["status"],
        "error": job.get("error")
    }

@app.get("/results/{job_id}/json")
async def get_json_report(job_id: str):
    """
    Download the final_report.json
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job ID not found")
    
    job = JOBS[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Job is {job['status']}, not completed.")

    output_path = job.get("actual_output_path")
    json_file = os.path.join(output_path, "final_report.json")
    
    if not os.path.exists(json_file):
        raise HTTPException(status_code=404, detail="Report file missing.")
        
    return FileResponse(json_file, media_type="application/json", filename=f"report_{job_id}.json")

@app.get("/results/{job_id}/docx")
async def get_docx_factsheet(job_id: str):
    """
    Download the generated Word Factsheet.
    """
    if job_id not in JOBS:
        raise HTTPException(status_code=404, detail="Job ID not found")
    
    job = JOBS[job_id]
    if job["status"] != "completed":
        raise HTTPException(status_code=400, detail=f"Job is {job['status']}, not completed.")

    output_path = job.get("actual_output_path")
    
    # The docx filename is dynamic (e.g. Factsheet_847130_China.docx). We need to find it.
    docx_files = glob.glob(os.path.join(output_path, "*.docx"))
    
    if not docx_files:
        raise HTTPException(status_code=404, detail="Factsheet .docx not found.")
        
    # Return the first docx found
    return FileResponse(docx_files[0], media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document", filename=os.path.basename(docx_files[0]))

if __name__ == "__main__":
    import uvicorn
    # Run the server
    uvicorn.run(app, host="0.0.0.0", port=8000)