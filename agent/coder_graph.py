import os
from dotenv import load_dotenv
from typing import Literal
from langchain_openai import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
from langgraph.graph import StateGraph, END
from langgraph.prebuilt import ToolNode

from agent.graph_state import CoderState
from agent.tools import build_agent_tools
from utils.validator import ContractValidator

def build_coder_graph(sandbox_manager):
    """
    Factory function that compiles the LangGraph application using a LIVE sandbox.
    """
    load_dotenv()
    coder_tools = build_agent_tools(sandbox_manager)
    
    # Initialize the Contract Validator with the live sandbox
    contract_validator = ContractValidator(sandbox_manager)

    model_name = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")

    llm = ChatOpenAI(
        model=model_name, 
        temperature=0, 
        reasoning_effort="none" 
    )

    # We bind our LLM with all the @tool annotations defined in tools.py
    # Langchain will translate the method names, required args, and description into a JSON schema that the LLM can read
    llm_with_tools = llm.bind_tools(coder_tools)

    # ==========================================
    # NODES
    # ==========================================

    # LLM Node
    def llm_node(state: CoderState):
        print(f"\n[Graph] LLM Node thinking... (Turn {state.get('turn_count', 0)})")
        response = llm_with_tools.invoke(state["messages"])
        return {
            "messages": [response],
            "turn_count": state.get("turn_count", 0) + 1
        }

    # Maven Node
    def maven_node(state: CoderState):
        print("\n[Graph] Gate 1: Forcing Maven Validation Node...")
        success, logs = sandbox_manager.run_maven_test()
        
        if success:
            print("✅ [Graph] Maven Passed!")
            return {"messages": [SystemMessage(content="MAVEN_PASS: The build was successful.")]}
        else:
            print("❌ [Graph] Maven Failed. Sending error back to LLM.")
            error_msg = f"MAVEN FAILED. Fix the compilation errors:\n{logs[-1000:]}"
            return {"messages": [HumanMessage(content=error_msg)]}

    # Contract Node
    def contract_node(state: CoderState):
        print("\n[Graph] Gate 2: Running Static Contract Validation...")
        work_item = state["work_item"]
        
        # Extract routing expectations
        target_method = work_item.get("target_method")
        target_path = work_item.get("target_path")
        source_path = work_item.get("source_path")
        
        # Run the V1 validator
        passed, diag = contract_validator.validate_work_item(target_method, target_path, source_path)
        
        if passed:
            print(f"✅ [Graph] Contract Validation Passed: {diag}")
            return {"messages": [SystemMessage(content=f"CONTRACT_PASS: {diag}")]}
        else:
            print(f"❌ [Graph] Contract Validation Failed. Sending error back to LLM.")
            # If it fails, we yell at the LLM to fix it!
            error_msg = f"CONTRACT VALIDATION FAILED. You passed Maven, but failed the API spec. Fix this:\n{diag}"
            return {"messages": [HumanMessage(content=error_msg)]}


    # ==========================================
    # EDGES (The Routing Logic)
    # ==========================================
    def should_continue(state: CoderState) -> Literal["tools", "maven_node"]:
        last_message = state["messages"][-1]

        # if LLM asks for tool call, move to tool node
        if last_message.tool_calls:
            print(f"[Router] LLM requested tools: {[t['name'] for t in last_message.tool_calls]}")
            return "tools"

        # if LLM does not request tools, move to Maven
        print(f"\n[Router] LLM did not request tools. Its final thought was:\n\"{last_message.content}\"\n")
        print("[Router] Routing to Gate 1 (Maven).")
        return "maven_node"

    # Routes to 'contract_node' if Maven passes
    def check_maven_result(state: CoderState) -> Literal["contract_node", "llm_node", "END"]:
        last_message = state["messages"][-1]
        
        if "MAVEN_PASS" in last_message.content:
            return "contract_node" # Proceed to Gate 2
        
        if state.get("turn_count", 0) >= 30:
            print("[Router] MAX TURNS REACHED. Forcing exit.")
            return "END"
            
        return "llm_node" # Failed Maven, go back to LLM

    # Routes to 'END' if Contract passes
    def check_contract_result(state: CoderState) -> Literal["END", "llm_node"]:
        last_message = state["messages"][-1]
        
        if "CONTRACT_PASS" in last_message.content:
            return "END" # The ultimate victory condition!
        
        if state.get("turn_count", 0) >= 30:
            print("[Router] MAX TURNS REACHED. Forcing exit.")
            return "END"
            
        return "llm_node" # Failed Contract Validation, go back to LLM to fix it


    # ==========================================
    # COMPILE THE GRAPH
    # ==========================================
    workflow = StateGraph(CoderState)
    
    workflow.add_node("llm_node", llm_node)
    # ToolNode is a prebuilt class from langgraph that automatically adds the tools to the graph for the LLM to use
    workflow.add_node("tools", ToolNode(coder_tools))
    workflow.add_node("maven_node", maven_node)
    workflow.add_node("contract_node", contract_node) # Add new node

    workflow.set_entry_point("llm_node")
    
    workflow.add_conditional_edges("llm_node", should_continue, {"tools": "tools", "maven_node": "maven_node"})
    workflow.add_edge("tools", "llm_node")
    
    # Update edges to flow through the double gates
    workflow.add_conditional_edges("maven_node", check_maven_result, {
        "contract_node": "contract_node", 
        "llm_node": "llm_node", 
        "END": END
    })
    
    workflow.add_conditional_edges("contract_node", check_contract_result, {
        "END": END, 
        "llm_node": "llm_node"
    })

    return workflow.compile()