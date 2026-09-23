# graph_state.py

from typing import TypedDict, Sequence, Dict, Any, List, Optional, Annotated
from langchain_core.messages import BaseMessage
import operator

# TypedDict is a standard Python feature that lets us define the exact shape of a dictionary.
class CoderState(TypedDict):
    # 'messages' holds the chat history (Human messages, AI messages, and Tool messages).
    # The `Annotated[..., operator.add]` part is LangGraph magic. 
    # It tells LangGraph: "When a node returns new messages, do NOT overwrite the old list. 
    # Instead, ADD (append) the new messages to the existing list."
    messages: Annotated[Sequence[BaseMessage], operator.add]
    
    # The current endpoint we are working on (e.g., getAddress strategy)
    work_item: dict
    
    # The Docker container ID where the code lives
    sandbox_id: str
    
    # We track how many times the LLM tries to write code, so we can stop infinite loops
    turn_count: int

class OrchestratorState(TypedDict):
    """
    State for the Outer Graph (Orchestrator).
    Manages dynamic inputs, queue iteration, and execution reporting.
    """
    # --- Dynamic Configuration (Passed in at runtime) ---
    consumer_repo_url: str                      # The target GitHub repository URL
    plan_file_path: str                         # Dynamic path to migration_plan.json
    context_file_path: str                      # Dynamic path to migration_context.json
    
    # --- Graph Execution Variables ---
    pending_queue: List[Dict[str, Any]]         # Queue of remaining endpoints to migrate
    context_data: List[Dict[str, Any]]          # Target schema truth for all endpoints
    current_item: Optional[Dict[str, Any]]      # The endpoint currently under active refactoring
    
    # --- Audit & Reporting ---
    completed_prs: List[str]                    # Successfully created GitHub PR URLs
    failed_items: List[str]                     # Operations that failed Gate 1 or Gate 2