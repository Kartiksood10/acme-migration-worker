# tests/test_planning_graph.py
import json
import os
from pipeline.schemas import ContractReference, ContractType
from pipeline.planning_graph import PlanningPipelineGraph

def test_planning_graph():
    print("=======================================================")
    print("🧪 TESTING PLANNING PIPELINE GRAPH (ISOLATED)")
    print("=======================================================")

    # 1. Setup mock references using your local running Spring Boot app
    source_ref = ContractReference(
        type=ContractType.URL,
        location="http://localhost:8080/v3/api-docs/v1"
    )
    target_ref = ContractReference(
        type=ContractType.URL,
        location="http://localhost:8080/v3/api-docs/v2"
    )

    # 2. Instantiate and run the graph
    pipeline = PlanningPipelineGraph()
    result_state = pipeline.run(
        consumer_repo_url="https://github.com/mock-org/mock-consumer-repo",
        source_ref=source_ref,
        target_ref=target_ref
    )

    # 3. Inspect the final output
    plan = result_state.get("migration_plan")
    
    print("\n=======================================================")
    print("📋 FINAL GENERATED MIGRATION PLAN OUTPUT")
    print("=======================================================")
    print(json.dumps(plan, indent=2))

    # 4. Verify disk cleanliness
    print("\n=======================================================")
    print("📁 VERIFYING DISK IS CLEAN")
    print("=======================================================")
    bad_files = ["source_openapi.json", "target_openapi.json", "raw_diffs.json", "migration_context.json", "migration_plan.json"]
    disk_clean = all(not os.path.exists(bf) for bf in bad_files)
    
    if disk_clean:
        print("✅ SUCCESS: Planning graph ran completely in RAM without writing root JSON files!")
    else:
        print("❌ FAILED: Found legacy files on disk.")

if __name__ == "__main__":
    test_planning_graph()