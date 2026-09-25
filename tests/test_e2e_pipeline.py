# tests/test_e2e_pipeline.py
import json
import time  # 1. Import the time module
from pipeline.schemas import ContractReference, ContractType
from pipeline.planning_graph import PlanningPipelineGraph
from agent.orchestrator_graph import OrchestratorGraph
from utils.sandbox_manager import SandboxManager

def test_full_e2e():
    print("=======================================================")
    print("🚀 RUNNING FULL END-TO-END MIGRATION PIPELINE")
    print("=======================================================")

    # 2. Start the master timer right as the pipeline kicks off
    start_time = time.time()

    CONSUMER_REPO = "https://github.com/Kartiksood10/acme-consumer-service.git"
    SOURCE_URL = "http://localhost:8080/v3/api-docs/v1"
    TARGET_URL = "http://localhost:8080/v3/api-docs/v2"

    source_ref = ContractReference(type=ContractType.URL, location=SOURCE_URL)
    target_ref = ContractReference(type=ContractType.URL, location=TARGET_URL)

    # Phase 1: Planning Graph
    print("\n--- PHASE 1: GENERATING IN-MEMORY STRATEGY ---")
    planner_pipeline = PlanningPipelineGraph()
    planning_state = planner_pipeline.run(
        consumer_repo_url=CONSUMER_REPO,
        source_ref=source_ref,
        target_ref=target_ref
    )

    plan = planning_state.get("migration_plan")
    context_data = planning_state.get("context_data")
    target_openapi = planning_state.get("target_openapi")

    if not plan:
        print("❌ Planning failed: No migration plan was returned.")
        return
        
    print(f"✅ Generated strategic plan with {len(plan['work_items'])} endpoints.")

    # Phase 2: Sandbox & Orchestrator
    print("\n--- PHASE 2: INITIALIZING LIVE DOCKER SANDBOX ---")
    manager = SandboxManager()
    
    try:
        manager.start_container(CONSUMER_REPO)

        print("\n--- PHASE 3: RUNNING ORCHESTRATOR & CODER LOOP ---")
        orchestrator = OrchestratorGraph(sandbox_manager=manager)
        
        final_state = orchestrator.run(
            consumer_repo_url=CONSUMER_REPO,
            target_openapi=target_openapi,
            context_data=context_data,
            migration_plan=plan
        )

        # 3. Stop the timer right before printing final metrics
        end_time = time.time()
        elapsed_seconds = end_time - start_time
        
        # Format into minutes and seconds for readability
        minutes = int(elapsed_seconds // 60)
        seconds = elapsed_seconds % 60

        # 4. Report Results including Total Duration
        print("\n=======================================================")
        print("📊 FINAL MIGRATION REPORT")
        print("=======================================================")
        print(f"⏱️ Total Execution Time: {minutes}m {seconds:.2f}s ({elapsed_seconds:.2f} seconds)")
        print(f"✅ Completed Endpoints: {final_state.get('completed_items', [])}")
        print(f"❌ Failed Endpoints:    {final_state.get('failed_items', [])}")
        print(f"🔗 Generated Pull Requests:")
        for pr in final_state.get("completed_prs", []):
            print(f"   - {pr}")

    except Exception as e:
        print(f"\n❌ Pipeline Exception: {str(e)}")
        
    finally:
        print("\n🧹 Cleaning up Sandbox...")
        manager.destroy_container()

if __name__ == "__main__":
    test_full_e2e()