import json
from langchain_core.messages import SystemMessage, HumanMessage
from utils.sandbox_manager import SandboxManager
from agent.coder_graph import build_coder_graph

# Test inner LangGraph (coder_graph.py) for migration of a single endpoint
def run_test():
    print("🚀 Starting LangGraph Phase 1 Test for 'getAddress'...")

    # 1. Initialize and start the container FIRST
    manager = SandboxManager()
    target_repo = "https://github.com/Kartiksood10/acme-consumer-service.git"
    manager.start_container(target_repo)

    # 2. Build the graph with the LIVE manager
    coder_app = build_coder_graph(manager)

    # 3. Load BOTH Prompts 
    with open("prompts/coder_prompt.txt", "r") as f:
        system_prompt_text = f.read()
        
    with open("prompts/coder_user_prompt.txt", "r") as f:
        user_prompt_template = f.read()

    # 4. Mock the Work Item for getAddress
    work_item = {
        "operation_id": "getAddress",
        "classification": "FLAT_TO_NESTED_RESPONSE",
        "reasoning_summary": "Update the Feign client to /api/v2/address. Create a static inner Address class in AddressResponseDto. Update downstream mappers.",
        "source_path": "/api/v1/address",
        "target_path": "/api/v2/address",
        "target_method": "GET"
    }

    # Load the target schema
    with open("migration_context.json", "r") as f:
        context_data = json.load(f)
        
        get_address_context = None
        if isinstance(context_data, list):
            for item in context_data:
                if "/api/v1/address" in str(item) or "getAddress" in str(item):
                    get_address_context = item
                    break
        else:
            get_address_context = context_data.get("getAddress", context_data)
            
        target_schema = get_address_context.get("v2_candidate") if get_address_context and "v2_candidate" in get_address_context else {
            "address": {"street": "string", "zip": "string"}
        }

    # 5. Format the User Prompt
    user_prompt_text = user_prompt_template.format(
        work_item_strategy=json.dumps(work_item, indent=2),
        target_contract_truth=json.dumps(target_schema, indent=2)
    )

    # 6. Initialize the Graph State
    initial_state = {
        "messages": [
            SystemMessage(content=system_prompt_text),
            HumanMessage(content=user_prompt_text)
        ],
        "work_item": work_item,
        "sandbox_id": "tracked_internally", 
        "turn_count": 0
    }

    print("\n=======================================================")
    print("🧠 Handing control to LangGraph...")
    print("=======================================================\n")

    # 7. EXECUTE THE GRAPH
    final_state = coder_app.invoke(initial_state)

    print("\n=======================================================")
    print("🏁 Graph Execution Finished!")
    
    last_message = final_state["messages"][-1]
    # Check if we passed the final Gate 2 Contract Validation
    last_message = final_state["messages"][-1]
    if "CONTRACT_PASS" in last_message.content:
        print("✅ SUCCESS: Endpoint migrated, passed Maven, AND passed Contract Validation!")
        
        print("\n========== GIT DIFF ==========")
        print(manager.get_git_diff())
    else:
        print("❌ FAILED: Graph exited without passing Gate 2.")

    # 8. Teardown
    manager.destroy_container()

if __name__ == "__main__":
    run_test()