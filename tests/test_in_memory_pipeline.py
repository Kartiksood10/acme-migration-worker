import json
import os
from pipeline.schemas import ContractReference, ContractType
from pipeline.contract_resolver import ContractResolver
from pipeline.diff_engine import DiffEngine
from pipeline.context_builder import ContextBuilder

def test_pipeline():
    print("=======================================================")
    print("🚀 TESTING IN-MEMORY PIPELINE (ALL ENDPOINTS)")
    print("=======================================================")

    resolver = ContractResolver()
    diff_engine = DiffEngine()

    source_ref = ContractReference(type=ContractType.URL, location="http://localhost:8080/v3/api-docs/v1")
    target_ref = ContractReference(type=ContractType.URL, location="http://localhost:8080/v3/api-docs/v2")

    print("\n[Step 1] Resolving Contracts into RAM...")
    source_openapi = resolver.resolve(source_ref)
    target_openapi = resolver.resolve(target_ref)
    
    print("\n[Step 2] Computing OASDiff...")
    raw_diffs = diff_engine.get_breaking_changes(source_openapi, target_openapi)
    
    print("\n[Step 3] Building LLM Context & Injecting Missing Schemas...")
    builder = ContextBuilder(source_openapi, target_openapi, raw_diffs)
    context_payload = builder.build_context()

    print("\n=======================================================")
    print("📊 ENDPOINT COVERAGE REPORT (LIGHTWEIGHT PLANNER PREP)")
    print("=======================================================")
    
    work_items = context_payload.get("work_items", [])
    print(f"Total endpoints processed: {len(work_items)}\n")
    
    for item in work_items:
        op_id = item.get("operation_id", "Unknown")
        has_direct_target = item.get("target_contract") is not None
        candidates = item.get("target_candidates")
        
        status = "✅ Direct 1:1 Mapping" if has_direct_target else f"⚠️ Semantic Shift ({len(candidates)} lightweight candidates staged)"
        print(f"Endpoint: {op_id:<15} | Status: {status}")

        if not has_direct_target and candidates:
            # Verify the candidates are lightweight and NOT carrying heavy DTO details
            lightweight_count = sum(1 for c in candidates if "details" not in c)
            print(f"  -> Validated: {lightweight_count}/{len(candidates)} candidates are lightweight to prevent token explosion.")

    print("\n=======================================================")
    print("📁 VERIFYING DISK IS CLEAN")
    print("=======================================================")
    bad_files = ["source_openapi.json", "target_openapi.json", "raw_diffs.json", "temp_normalized_source.json"]
    disk_clean = all(not os.path.exists(bf) for bf in bad_files)
            
    if disk_clean:
        print("✅ SUCCESS: Pipeline is completely disk-less. No JSON files written to root.")
    else:
        print("❌ FAILED: Found legacy JSON files on disk.")

if __name__ == "__main__":
    test_pipeline()