import json
import os
import time
from typing import Dict, Any
from langgraph.graph import StateGraph, END
from langchain_core.messages import SystemMessage, HumanMessage

from agent.graph_state import OrchestratorState, CoderState
from agent.coder_graph import build_coder_graph
from utils.sandbox_manager import SandboxManager 

class OrchestratorGraph:
    """
    The Master Execution Engine. Pops items off the LLM's MigrationPlan queue,
    performs JIT schema injection for broken mappings, invokes the live Coder
    sandbox graph, and generates Pull Requests.
    """
    def __init__(self, sandbox_manager: SandboxManager):
        self.sandbox_manager = sandbox_manager
        self.system_prompt = self._load_prompt("prompts/coder_prompt.txt")
        self.user_prompt_template = self._load_prompt("prompts/coder_user_prompt.txt")
        self.graph = self._build_graph()

    def _load_prompt(self, filepath: str) -> str:
        """Safely loads external prompt templates."""
        if os.path.exists(filepath):
            with open(filepath, "r") as f:
                return f.read()
        return ""

    def _pop_queue_node(self, state: OrchestratorState) -> Dict[str, Any]:
        """Node 1: Pulls the next work item from the pending queue."""
        queue = state.get("pending_queue", [])
        if not queue:
            print("\n🏁 [Orchestrator] Queue is empty. Migration complete.")
            return {"current_item": None}
            
        next_item = queue.pop(0)
        op_id = next_item.get("operation_id", "unknown")
        print(f"\n=======================================================")
        print(f"🚀 [Orchestrator] Processing Endpoint: {op_id}")
        print(f"=======================================================")
        
        return {
            "pending_queue": queue,
            "current_item": next_item
        }

    def _execute_coder_node(self, state: OrchestratorState) -> Dict[str, Any]:
        """Node 2: The JIT Engine & Execution Node."""
        current_plan = state["current_item"]
        op_id = current_plan["operation_id"]
        repo_url = state["consumer_repo_url"]
        
        context_items = state["context_data"].get("work_items", [])
        context_item = next((item for item in context_items if item["operation_id"] == op_id), {})
        
        target_schema = context_item.get("target_contract")

        # 1. JUST-IN-TIME (JIT) SCHEMA INJECTION
        if not target_schema:
            print(f"⚠️ [JIT Engine] Missing schema for {op_id}. Initiating dynamic lookup...")
            target_path = current_plan.get("target_path")
            target_method = current_plan.get("target_method", "").lower()
            raw_schema = state["target_openapi"].get("paths", {}).get(target_path, {}).get(target_method, {})
            
            if raw_schema:
                print(f"✅ [JIT Engine] Successfully injected schema for {target_method.upper()} {target_path}")
                target_schema = {
                    "path": target_path,
                    "method": target_method.upper(),
                    "details": raw_schema
                }
            else:
                print(f"❌ [JIT Engine] Critical: Could not resolve target schema for {target_path}")

        # 2. Format the Unified Prompt for the Coder
        user_prompt = self.user_prompt_template.format(
            work_item_strategy=json.dumps(current_plan, indent=2),
            target_contract_truth=json.dumps(target_schema, indent=2)
        )

        # 3. Clean Sandbox to ensure isolation between endpoints
        print(f"🧹 [Orchestrator] Resetting sandbox to clean state for {op_id}...")
        
        # Execute commands sequentially to bypass Docker SDK shell limitations
        self.sandbox_manager.container.exec_run("git reset --hard", workdir="/workspace/app")
        self.sandbox_manager.container.exec_run("git clean -fd", workdir="/workspace/app")
        
        # Determine the default branch dynamically (main or master) and check it out
        exit_code, base_out = self.sandbox_manager.container.exec_run(
            "git rev-parse --abbrev-ref origin/HEAD", 
            workdir="/workspace/app"
        )
        base_branch = base_out.decode("utf-8").strip().replace("origin/", "") if exit_code == 0 else "main"
        
        self.sandbox_manager.container.exec_run(f"git checkout {base_branch}", workdir="/workspace/app")

        # 4. Build and Run the Coder Graph
        print(f"🤖 [Orchestrator] Invoking Coder ReAct Agent...")
        coder_graph = build_coder_graph(self.sandbox_manager)
        
        initial_coder_state: CoderState = {
            "messages": [
                SystemMessage(content=self.system_prompt),
                HumanMessage(content=user_prompt)
            ],
            "work_item": current_plan, 
            "sandbox_id": getattr(self.sandbox_manager, "container").id[:10] if self.sandbox_manager.container else "sandbox",
            "turn_count": 0
        }

        final_coder_state = coder_graph.invoke(initial_coder_state)
        
        # 5. Check Result and Create Pull Request
        completed_items = state.get("completed_items", [])
        completed_prs = state.get("completed_prs", [])
        failed_items = state.get("failed_items", [])

        last_message = final_coder_state["messages"][-1].content
        
        if "CONTRACT_PASS" in last_message:
            print(f"🎉 [Orchestrator] Both Maven & Contract Validation Passed for {op_id}!")
            
            run_id = int(time.time())
            branch_name = f"migrate/op-{op_id.lower()}-{run_id}"
            commit_msg = f"feat(migration): migrate {op_id} to {current_plan.get('target_path')}"
            
            # Utilize existing SandboxManager methods to commit, push, and create PR
            try:
                self.sandbox_manager.commit_and_push(branch_name=branch_name, commit_message=commit_msg)
                pr_url = self.sandbox_manager.create_github_pr(
                    repo_url=repo_url,
                    branch_name=branch_name,
                    title=commit_msg,
                    body=f"Automated API Migration for `{op_id}`.\n\n### Reasoning:\n{current_plan.get('reasoning_summary')}"
                )
                print(f"🚀 [Orchestrator] Pull Request Created: {pr_url}")
                completed_items.append(op_id)
                completed_prs.append(pr_url)
            except Exception as e:
                print(f"❌ [Orchestrator] Git/PR Operation Failed: {str(e)}")
                failed_items.append(op_id)
        else:
            print(f"❌ [Orchestrator] Coder Agent failed to satisfy validators for {op_id}.")
            failed_items.append(op_id)

        return {
            "completed_items": completed_items,
            "completed_prs": completed_prs,
            "failed_items": failed_items
        }

    def _route_queue(self, state: OrchestratorState) -> str:
        """Edge Router: Continues the loop until pending_queue is exhausted."""
        if state.get("current_item") is None:
            return END
        return "execute_coder"

    def _build_graph(self) -> StateGraph:
        """Wires the LangGraph execution loop."""
        workflow = StateGraph(OrchestratorState)

        workflow.add_node("pop_queue", self._pop_queue_node)
        workflow.add_node("execute_coder", self._execute_coder_node)

        workflow.set_entry_point("pop_queue")
        workflow.add_conditional_edges("pop_queue", self._route_queue)
        workflow.add_edge("execute_coder", "pop_queue")

        return workflow.compile()

    def run(self, consumer_repo_url: str, target_openapi: dict, context_data: dict, migration_plan: dict) -> Dict[str, Any]:
        """Public execution handle."""
        initial_state: OrchestratorState = {
            "consumer_repo_url": consumer_repo_url,
            "target_openapi": target_openapi,
            "context_data": context_data,
            "pending_queue": list(migration_plan.get("work_items", [])),
            "current_item": None,
            "completed_items": [],
            "completed_prs": [],
            "failed_items": []
        }
        
        print(f"🚀 Launching Orchestrator for {consumer_repo_url}")
        return self.graph.invoke(initial_state)