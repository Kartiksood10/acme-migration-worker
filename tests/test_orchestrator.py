# tests/test_orchestrator.py
from agent.orchestrator_graph import OrchestratorGraph
import json

def test_jit_orchestrator():
    print("=======================================================")
    print("🧪 TESTING ORCHESTRATOR JIT INJECTION")
    print("=======================================================")

    # 1. Mock the Target OpenAPI RAM Dictionary (What the API actually looks like)
    mock_target_openapi = {
        "paths": {
            "/api/v2/address": { "get": { "responses": { "200": { "description": "Address DTO" } } } },
            "/api/v2/clients/{clientId}": {
                "get": {
                    "operationId": "getClient",
                    "responses": {
                        "200": { "properties": { "id": "string", "age": "integer", "status": "string" } }
                    }
                }
            }
        }
    }

    # 2. Mock the Context Builder Output (Notice getUser's target is null)
    mock_context_data = {
        "work_items": [
            {
                "operation_id": "getAddress",
                "target_contract": { "path": "/api/v2/address", "method": "GET", "details": {} }
            },
            {
                "operation_id": "getUser",
                "target_contract": None,  # This triggers the JIT engine
                "target_candidates": []
            }
        ]
    }

    # 3. Mock the LLM Planner's Output (The Strategy)
    mock_migration_plan = {
        "work_items": [
            {
                "operation_id": "getAddress",
                "target_path": "/api/v2/address",
                "target_method": "GET"
            },
            {
                "operation_id": "getUser",
                "target_path": "/api/v2/clients/{clientId}",  # The LLM's semantic choice
                "target_method": "GET"
            }
        ]
    }

    # 4. Run the Orchestrator
    orchestrator = OrchestratorGraph()
    result = orchestrator.run(
        consumer_repo_url="https://github.com/mock/repo",
        target_openapi=mock_target_openapi,
        context_data=mock_context_data,
        migration_plan=mock_migration_plan
    )

    print("\n=======================================================")
    print("✅ TEST COMPLETE")
    print(f"Processed endpoints: {result['completed_items']}")

if __name__ == "__main__":
    test_jit_orchestrator()