import os
import time
import uuid
import requests
import tempfile
import shutil
from typing import Optional

from fastapi import FastAPI, BackgroundTasks, Form, File, UploadFile, HTTPException
from fastapi.responses import JSONResponse

# Import your existing pipeline modules
from pipeline.schemas import ContractReference, ContractType
from pipeline.planning_graph import PlanningPipelineGraph
from agent.orchestrator_graph import OrchestratorGraph
from utils.sandbox_manager import SandboxManager

# Initialize the FastAPI application
app = FastAPI(title="Autonomous Migration Worker", version="1.0.0")

# Method that runs the PlanningGraph, OrchestratorGraph, and CoderGraph in the background
# and fires the final JSON payload to the webhook callback_url
def run_migration_pipeline(
    task_id: str,
    consumer_repo_url: str,
    source_ref: ContractReference,
    target_ref: ContractReference,
    callback_url: str
):
    """
    This function runs entirely in the background. It executes your existing 
    LangGraph logic and fires the final JSON payload to the webhook callback_url.
    """
    print(f"[{task_id}] 🚀 Background task started for {consumer_repo_url}")
    start_time = time.time()
    
    manager = SandboxManager()
    payload = {
        "task_id": task_id,
        "status": "FAILED",
        "execution_time_minutes": 0,
        "generated_prs": [],
        "completed_endpoints": [],
        "failed_endpoints": [],
        "error_message": None
    }

    try:
        # Phase 1: Run the RAM-based Planning Graph
        print(f"[{task_id}] --- PHASE 1: GENERATING STRATEGY ---")
        planner_pipeline = PlanningPipelineGraph()
        planning_state = planner_pipeline.run(
            consumer_repo_url=consumer_repo_url,
            source_ref=source_ref,
            target_ref=target_ref
        )

        plan = planning_state.get("migration_plan")
        if not plan:
            raise ValueError("Planning failed: No migration plan was returned.")

        # Phase 2 & 3: Run Orchestrator and Coder Graph in Sandbox
        print(f"[{task_id}] --- PHASE 2 & 3: INITIALIZING SANDBOX & ORCHESTRATOR ---")
        manager.start_container(consumer_repo_url)
        orchestrator = OrchestratorGraph(sandbox_manager=manager)
        
        final_state = orchestrator.run(
            consumer_repo_url=consumer_repo_url,
            target_openapi=planning_state.get("target_openapi"),
            context_data=planning_state.get("context_data"),
            migration_plan=plan
        )

        # Build Success Payload
        payload["generated_prs"] = final_state.get("completed_prs", [])
        payload["completed_endpoints"] = final_state.get("completed_items", [])
        payload["failed_endpoints"] = final_state.get("failed_items", [])
        
        if payload["failed_endpoints"]:
            payload["status"] = "PARTIAL_FAILURE"
        else:
            payload["status"] = "COMPLETED"

    except Exception as e:
        print(f"[{task_id}] ❌ Pipeline Exception: {str(e)}")
        payload["error_message"] = str(e)
    
    finally:
        # Clean up Docker Sandbox
        print(f"[{task_id}] 🧹 Cleaning up Sandbox...")
        manager.destroy_container()

        # Clean up temporary uploaded files
        print(f"[{task_id}] 🧹 Cleaning up Temporary Uploads...")
        if source_ref.type == ContractType.UPLOAD and source_ref.location and os.path.exists(source_ref.location):
            os.remove(source_ref.location)
        if target_ref.type == ContractType.UPLOAD and target_ref.location and os.path.exists(target_ref.location):
            os.remove(target_ref.location)

        # Stop timer and record execution time in minutes (rounded to 2 decimal places)
        end_time = time.time()
        elapsed_seconds = end_time - start_time
        payload["execution_time_minutes"] = round(elapsed_seconds / 60, 2)
        
        # Dispatch the Webhook Callback
        print(f"[{task_id}] 📡 Dispatching results to webhook: {callback_url}")
        try:
            requests.post(callback_url, json=payload, timeout=10)
            print(f"[{task_id}] ✅ Webhook delivered successfully.")
        except requests.exceptions.RequestException as e:
            print(f"[{task_id}] ❌ Webhook delivery failed: {e}")


@app.post("/migrations", status_code=202)
async def trigger_migration(
    background_tasks: BackgroundTasks,
    consumer_repo_url: str = Form(...),
    callback_url: str = Form(...),
    source_url: Optional[str] = Form(None),
    target_url: Optional[str] = Form(None),
    source_file: Optional[UploadFile] = File(None),
    target_file: Optional[UploadFile] = File(None)
):
    """
    API Endpoint that accepts Form Data and File Uploads. 
    It validates inputs, kicks off the background task, and returns a 202 Accepted.
    """
    # 1. Input Validation: Ensure we have either a URL or a File for both source and target
    if not source_url and not source_file:
        raise HTTPException(status_code=400, detail="Must provide either source_url or source_file")
    if not target_url and not target_file:
        raise HTTPException(status_code=400, detail="Must provide either target_url or target_file")

    task_id = f"mig_{uuid.uuid4().hex[:8]}"

    # 2. Helper to safely save uploaded files to a temporary local directory
    def save_temp_file(upload_file: UploadFile) -> str:
        temp_dir = tempfile.gettempdir()
        file_path = os.path.join(temp_dir, f"{task_id}_{upload_file.filename}")
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(upload_file.file, buffer)
        return file_path

    # 3. Resolve Source Contract Reference
    if source_file:
        content_bytes = source_file.file.read()
        source_ref = ContractReference(type=ContractType.UPLOAD, content=content_bytes.decode("utf-8"))
    else:
        source_ref = ContractReference(type=ContractType.URL, location=source_url)

    # 4. Resolve Target Contract Reference
    if target_file:
        content_bytes = target_file.file.read()
        target_ref = ContractReference(type=ContractType.UPLOAD, content=content_bytes.decode("utf-8"))
    else:
        target_ref = ContractReference(type=ContractType.URL, location=target_url)

    # 5. Hand the heavy lifting off to the Background Task - runs the migration pipeline asynchronously
    # As soon as we send the response, the migration pipeline triggers
    background_tasks.add_task(
        run_migration_pipeline,
        task_id=task_id,
        consumer_repo_url=consumer_repo_url,
        source_ref=source_ref,
        target_ref=target_ref,
        callback_url=callback_url
    )

    # 6. Return immediate 202 response to Postman, so that main thread is free and heavy lifting happens in the background
    return JSONResponse(
        status_code=202,
        content={
            "task_id": task_id,
            "status": "PROCESSING",
            "message": "Migration pipeline started in background. Results will be sent to the callback URL."
        }
    )