import os
import sys
import time

# Ensure Python can import from the new 'agent' folder
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from agent.orchestrator_graph import orchestrator_app

def run_test():
    print("🚀 [TEST] Triggering Local Orchestrator Migration Pipeline...")

    # Pointing to the new 'data/' directory
    initial_state = {
        "consumer_repo_url": "https://github.com/Kartiksood10/acme-consumer-service.git",
        "plan_file_path": "data/migration_plan.json",
        "context_file_path": "data/migration_context.json"
    }

    # Start Timer
    start_time = time.time()
    
    # Execute the Pipeline
    final_state = orchestrator_app.invoke(initial_state)
    
    # End Timer & Calculate Duration
    end_time = time.time()
    duration = int(end_time - start_time)
    minutes, seconds = divmod(duration, 60)

    # Display final execution report
    print("\n=======================================================")
    print("🏁 FULL ORCHESTRATOR RUN COMPLETE")
    print(f"⏱️  Total Execution Time: {minutes}m {seconds}s")
    print("=======================================================")
    
    print(f"✅ Generated PRs ({len(final_state.get('completed_prs', []))}):")
    for pr in final_state.get("completed_prs", []):
        print(f"   • {pr}")

    print(f"\n❌ Failed Endpoints ({len(final_state.get('failed_items', []))}):")
    for fail in final_state.get("failed_items", []):
        print(f"   • {fail}")

if __name__ == "__main__":
    run_test()