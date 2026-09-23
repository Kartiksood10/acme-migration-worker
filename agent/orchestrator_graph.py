import json
import time
from typing import Literal
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage

from agent.graph_state import OrchestratorState
from utils.sandbox_manager import SandboxManager
from agent.coder_graph import build_coder_graph

# ==========================================
# NODES
# ==========================================
def initialize_migration(state: OrchestratorState):
    """Dynamically reads the JSON files specified in the state and builds the queue."""
    print("\n[Orchestrator] Initializing Migration Pipeline...")
    
    plan_path = state.get("plan_file_path")
    context_path = state.get("context_file_path")
    repo_url = state.get("consumer_repo_url")
    
    if not repo_url or not plan_path or not context_path:
        raise ValueError("Missing required configuration in OrchestratorState.")

    with open(plan_path, "r") as f:
        plan_json = json.load(f)
    with open(context_path, "r") as f:
        context_json = json.load(f)

    queue = plan_json.get("work_items", [])
    context_items = context_json.get("work_items", [])

    print(f"[Orchestrator] Found {len(queue)} endpoints in {plan_path}.")

    return {
        "pending_queue": queue,
        "context_data": context_items,
        "completed_prs": [],
        "failed_items": []
    }

def dispatcher(state: OrchestratorState):
    """Pops the next work item from the dynamic queue."""
    queue = list(state.get("pending_queue", []))

    if not queue:
        print("\n[Orchestrator] Work queue is empty. Transitioning to completion.")
        return {"current_item": None}

    next_item = queue.pop(0)
    op_id = next_item.get("operation_id", "UnknownOperation")

    print(f"\n[Orchestrator] Dispatching next work item: '{op_id}'. ({len(queue)} items remaining in queue)")

    return {
        "pending_queue": queue,
        "current_item": next_item
    }

def process_item(state: OrchestratorState):
    """
    Executes an atomic migration cycle for the current work item using a dedicated Docker container.
    """
    work_item = state["current_item"]
    op_id = work_item.get("operation_id")
    context_data = state.get("context_data", [])
    target_repo = state["consumer_repo_url"] 

    print(f"\n=======================================================")
    print(f"🚀 PROCESSING ENDPOINT: {op_id}")
    print(f"=======================================================")

    context_slice = next((item for item in context_data if item.get("operation_id") == op_id), {})

    with open("prompts/coder_prompt.txt", "r") as f:
        system_prompt = f.read()
    with open("prompts/coder_user_prompt.txt", "r") as f:
        user_prompt_template = f.read()

    user_prompt = user_prompt_template.format(
        work_item_strategy=json.dumps(work_item, indent=2),
        target_contract_truth=json.dumps(context_slice, indent=2)
    )

    manager = SandboxManager()

    try:
        # Dynamically clone the specified consumer repository
        manager.start_container(target_repo)

        # Call coder_graph.py inner graph for execution per item
        inner_graph = build_coder_graph(manager)
        inner_state = {
            "messages": [
                SystemMessage(content=system_prompt),
                HumanMessage(content=user_prompt)
            ],
            "work_item": work_item,
            "sandbox_id": "live_sandbox",
            "turn_count": 0
        }

        print(f"[Orchestrator] Invoking Inner AI Subgraph for '{op_id}'...")
        final_inner_state = inner_graph.invoke(inner_state)

        last_message = final_inner_state["messages"][-1]

        if "CONTRACT_PASS" in last_message.content:
            print(f"✅ [Orchestrator] Gate 1 & Gate 2 PASSED for '{op_id}'. Creating PR...")

            run_id = int(time.time())
            branch_name = f"migrate/op-{op_id.lower()}-{run_id}"
            commit_message = f"refactor(api): migrate {op_id} to Target Contract"

            manager.commit_and_push(branch_name, commit_message)

            pr_title = f"Migrate `{op_id}` endpoint to Target Contract"
            pr_body = (
                f"### Autonomous API Migration\n\n"
                f"- **Operation ID**: `{op_id}`\n"
                f"- **Classification**: `{work_item.get('classification', 'N/A')}`\n\n"
                f"Verified with Maven test suites and static AST contract inspection."
            )

            pr_url = manager.create_github_pr(target_repo, branch_name, pr_title, pr_body)
            print(f"🎉 PR Generated: {pr_url}")

            return {"completed_prs": state.get("completed_prs", []) + [f"{op_id}: {pr_url}"]}
        else:
            print(f"❌ [Orchestrator] '{op_id}' failed quality gates. Discarding changes.")
            return {"failed_items": state.get("failed_items", []) + [op_id]}

    except Exception as e:
        print(f"❌ [Orchestrator] Error processing '{op_id}': {e}")
        return {"failed_items": state.get("failed_items", []) + [f"{op_id} (Error: {str(e)})"]}

    finally:
        # Guarantee sandbox teardown regardless of outcome
        manager.destroy_container()


def route_dispatcher(state: OrchestratorState) -> Literal["process_item", "END"]:
    if state.get("current_item"):
        return "process_item"
    return "END"


# ==========================================
# EDGES & GRAPH COMPILATION
# ==========================================
outer_workflow = StateGraph(OrchestratorState)

outer_workflow.add_node("initialize_migration", initialize_migration)
outer_workflow.add_node("dispatcher", dispatcher)
outer_workflow.add_node("process_item", process_item)

outer_workflow.set_entry_point("initialize_migration")
outer_workflow.add_edge("initialize_migration", "dispatcher")
outer_workflow.add_conditional_edges("dispatcher", route_dispatcher, {
    "process_item": "process_item",
    "END": END
})
outer_workflow.add_edge("process_item", "dispatcher")

orchestrator_app = outer_workflow.compile()