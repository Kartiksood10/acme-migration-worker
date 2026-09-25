# graph_state.py

from typing import TypedDict, Sequence, Dict, Any, List, Optional, Annotated
from langchain_core.messages import BaseMessage
from typing import TypedDict, List, Dict, Any, Optional

import operator

# TypedDict is a standard Python feature that lets us define the exact shape of a dictionary.

# State Management for the planning_graph
class PlanningState(TypedDict):
    """
    State for the Pre-Orchestrator Planning Phase.
    Handles raw API payloads, fetching contracts, calculating diffs, and LLM planning entirely in RAM.
    """
    consumer_repo_url: str
    
    # Contract References supplied by the UI (URL or UPLOAD)
    source_contract_ref: Dict[str, Any]
    target_contract_ref: Dict[str, Any]
    
    # In-Memory working dictionaries populated dynamically by the graph nodes
    source_openapi: Optional[Dict[str, Any]]
    target_openapi: Optional[Dict[str, Any]]
    raw_diffs: Optional[List[Dict[str, Any]]]
    
    # Final outputs passed downstream
    context_data: Optional[Dict[str, Any]]
    migration_plan: Optional[Dict[str, Any]]

# State Management for the orchestrator_graph
class OrchestratorState(TypedDict):
    """
    State for the Master Orchestrator. 
    Now holds 'target_openapi' strictly for Just-In-Time (JIT) schema injection.
    """
    consumer_repo_url: str
    target_openapi: Dict[str, Any]       # JIT schema lookups
    context_data: Dict[str, Any]         # The payload from ContextBuilder
    pending_queue: List[Dict[str, Any]]  # The queue of planned work items from the LLM
    current_item: Optional[Dict[str, Any]]
    completed_items: List[str]
    completed_prs: List[str]
    failed_items: List[str]


# State management for the coder_graph
class CoderState(TypedDict):
    # 'messages' holds the chat history (Human messages, AI messages, and Tool messages).
    # The `Annotated[..., operator.add]` part is LangGraph magic. 
    # It tells LangGraph: "When a node returns new messages, do NOT overwrite the old list.
    # Instead, ADD (append) the new messages to the existing list."
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # The current endpoint we are working on (e.g., getAddress strategy)
    work_item: Dict[str, Any]
    
    # The Docker container ID where the code lives
    sandbox_id: str
    
    # We track how many times the LLM tries to write code, so we can stop infinite loops
    turn_count: int