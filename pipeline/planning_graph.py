# pipeline/planning_graph.py
from typing import Dict, Any
from langgraph.graph import StateGraph, END

from agent.graph_state import PlanningState
from pipeline.schemas import ContractReference
from pipeline.contract_resolver import ContractResolver
from pipeline.diff_engine import DiffEngine
from pipeline.context_builder import ContextBuilder
from pipeline.planner import MigrationPlanner

class PlanningPipelineGraph:
    """
    An autonomous LangGraph state machine that executes the pre-planning phase
    entirely in memory, converting raw contract references into a finalized MigrationPlan.
    """
    def __init__(self):
        # Initialize our underlying modular components
        self.resolver = ContractResolver()
        self.diff_engine = DiffEngine()
        self.planner = MigrationPlanner()
        
        # Build the LangGraph state machine
        self.graph = self._build_graph()

    def _resolve_contracts_node(self, state: PlanningState) -> Dict[str, Any]:
        """Node 1: Fetches and normalizes source and target contracts into RAM."""
        print("\n--- [Planning Graph] Node 1: Resolving Contracts ---")
        
        # Reconstruct Pydantic models from the state dictionary
        src_ref = ContractReference(**state["source_contract_ref"])
        tgt_ref = ContractReference(**state["target_contract_ref"])
        
        source_openapi = self.resolver.resolve(src_ref)
        target_openapi = self.resolver.resolve(tgt_ref)
        
        print("✅ Contracts successfully resolved and $ref-flattened in memory.")
        return {
            "source_openapi": source_openapi,
            "target_openapi": target_openapi
        }

    def _compute_diffs_node(self, state: PlanningState) -> Dict[str, Any]:
        """Node 2: Computes breaking changes using ephemeral temp files and auto-detection."""
        print("\n--- [Planning Graph] Node 2: Computing Diffs ---")
        
        source_openapi = state["source_openapi"]
        target_openapi = state["target_openapi"]
        
        raw_diffs = self.diff_engine.get_breaking_changes(source_openapi, target_openapi)
        print(f"✅ Found {len(raw_diffs)} breaking changes.")
        
        return {"raw_diffs": raw_diffs}

    def _build_context_node(self, state: PlanningState) -> Dict[str, Any]:
        """Node 3: Groups diffs into work items and prepares lightweight target candidates."""
        print("\n--- [Planning Graph] Node 3: Building Context ---")
        
        builder = ContextBuilder(
            source_data=state["source_openapi"],
            target_data=state["target_openapi"],
            oasdiff_findings=state["raw_diffs"]
        )
        context_data = builder.build_context()
        print("✅ Context payload structured successfully.")
        
        return {"context_data": context_data}

    def _generate_plan_node(self, state: PlanningState) -> Dict[str, Any]:
        """Node 4: Invokes the LLM Planner to generate the structured MigrationPlan."""
        print("\n--- [Planning Graph] Node 4: Generating LLM Plan ---")
        
        context_data = state["context_data"]
        plan_object = self.planner.generate_plan(context_data)
        
        # Convert the Pydantic model into a dictionary for downstream state passing
        plan_dict = plan_object.model_dump()
        print(f"✅ Migration plan generated containing {len(plan_dict.get('work_items', []))} work items.")
        
        return {"migration_plan": plan_dict}

    def _build_graph(self) -> StateGraph:
        """Wires the nodes together sequentially using LangGraph."""
        workflow = StateGraph(PlanningState)

        # Add nodes
        workflow.add_node("resolve_contracts", self._resolve_contracts_node)
        workflow.add_node("compute_diffs", self._compute_diffs_node)
        workflow.add_node("build_context", self._build_context_node)
        workflow.add_node("generate_plan", self._generate_plan_node)

        # Define the sequential execution edges
        workflow.set_entry_point("resolve_contracts")
        workflow.add_edge("resolve_contracts", "compute_diffs")
        workflow.add_edge("compute_diffs", "build_context")
        workflow.add_edge("build_context", "generate_plan")
        workflow.add_edge("generate_plan", END)

        return workflow.compile()

    def run(self, consumer_repo_url: str, source_ref: ContractReference, target_ref: ContractReference) -> Dict[str, Any]:
        """
        Public execution handle to trigger the entire planning graph.
        """
        initial_state: PlanningState = {
            "consumer_repo_url": consumer_repo_url,
            "source_contract_ref": source_ref.model_dump(),
            "target_contract_ref": target_ref.model_dump(),
            "source_openapi": None,
            "target_openapi": None,
            "raw_diffs": None,
            "context_data": None,
            "migration_plan": None
        }
        
        print(f"🚀 Launching Planning Pipeline Graph for repository: {consumer_repo_url}")
        final_state = self.graph.invoke(initial_state)
        return final_state