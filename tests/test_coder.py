import os
import re
import json
import time
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.messages import SystemMessage, HumanMessage, ToolMessage, AIMessage

# Import our custom environment orchestration and validation modules
from utils.sandbox_manager import SandboxManager
from agent.tools import build_agent_tools
from utils.validator import ContractValidator

# Test Coder Agent for testing endpoint one at a time (Pre-LangGraph code)
class CoderAgent:
    def __init__(self, sandbox_manager: SandboxManager):
        load_dotenv()
        self.manager = sandbox_manager
        
        # Configure OpenAI model and temperature
        model_name = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
        
        # Explicitly disable reasoning_effort to avoid LangChain API warnings and allow tools
        self.llm = ChatOpenAI(
            model=model_name, 
            temperature=0,
            reasoning_effort="none"
        )
        
        # Build job-scoped tools bound strictly to this SandboxManager instance
        raw_tools = build_agent_tools(self.manager)
        self.tool_map = {tool.name: tool for tool in raw_tools}
        self.llm_with_tools = self.llm.bind_tools(raw_tools)
        
        # Load externalized prompts
        with open("prompts/coder_prompt.txt", "r") as f:
            self.system_prompt = f.read()
            
        with open("prompts/coder_user_prompt.txt", "r") as f:
            self.user_prompt_template = f.read()

    def _invoke_llm_with_resilience(self, messages: list, max_retries: int = 5) -> AIMessage:
        """
        Invokes the OpenAI LLM. Uses reactive exponential backoff 
        to gracefully handle generic OpenAI 429 quota/rate limits.
        """
        for attempt in range(1, max_retries + 1):
            try:
                return self.llm_with_tools.invoke(messages)
            except Exception as e:
                error_msg = str(e).lower()
                if "429" in error_msg or "rate limit" in error_msg or "quota" in error_msg:
                    print(f"\n  ⚠️ OpenAI rate limit encountered on attempt {attempt}/{max_retries}.")
                    
                    # Extract OpenAI's specific 'retry-after' or generic delay
                    delay_match = re.search(r"please try again in ([\d\.]+)s", error_msg)
                    
                    if delay_match:
                        backoff_seconds = float(delay_match.group(1)) + 1.0
                        print(f"  🛑 Server explicitly requested wait of {delay_match.group(1)}s. Pausing for {backoff_seconds:.1f}s...")
                    else:
                        backoff_seconds = 5.0 * attempt  # Shorter backoff for paid tier
                        print(f"  🛑 Applying fallback backoff: pausing for {backoff_seconds:.1f}s...")

                    time.sleep(backoff_seconds)
                else:
                    # Non-quota exceptions should fail fast
                    raise e

        raise RuntimeError(f"Failed to obtain LLM response after {max_retries} retries.")

    def execute_work_item(self, work_item_plan: dict, target_schema_slice: dict, max_turns: int = 20) -> dict:
        """
        Executes an autonomous discovery-to-patch cycle for a single endpoint.
        Bounded strictly to max_turns to prevent infinite reasoning loops.
        """
        op_id = work_item_plan.get("operation_id", "Unknown")
        print(f"\n=======================================================")
        print(f"Coder Agent starting migration for: {op_id}")
        print(f"Classification: {work_item_plan.get('classification')}")
        print(f"=======================================================\n")

        # Dynamically format the generic user prompt with the current endpoint's data
        user_prompt = self.user_prompt_template.format(
            work_item_strategy=json.dumps(work_item_plan, indent=2),
            target_contract_truth=json.dumps(target_schema_slice, indent=2)
        )

        messages = [
            SystemMessage(content=self.system_prompt),
            HumanMessage(content=user_prompt)
        ]

        turns = 0
        maven_passed = False

        while turns < max_turns:
            turns += 1
            print(f"[Turn {turns}/{max_turns}] Invoking {self.llm.model_name}...")

            # Resilient invocation without artificial pacing
            response = self._invoke_llm_with_resilience(messages)
            messages.append(response)

            # If the model outputs standard text instead of tool calls, it believes its work is finished
            if not response.tool_calls:
                print(f"\nAgent returned final thought:\n{response.content}")
                break

            # Execute all requested tool calls
            for tool_call in response.tool_calls:
                tool_name = tool_call["name"]
                tool_args = tool_call["args"]
                tool_id = tool_call["id"]

                print(f"  -> Requested Tool: {tool_name}")
                print(f"     Args: {tool_args}")

                tool_func = self.tool_map.get(tool_name)
                if tool_func:
                    try:
                        tool_output = tool_func.invoke(tool_args)
                    except Exception as err:
                        tool_output = f"TOOL EXECUTION ERROR: {str(err)}"
                else:
                    tool_output = f"ERROR: Tool '{tool_name}' not recognized."

                # Deterministic Maven status parsing
                if tool_name == "run_maven_validation" and str(tool_output).startswith("MAVEN_PASS"):
                    maven_passed = True

                preview = str(tool_output).strip().split('\n')[0][:80]
                print(f"     Output preview: {preview}...")
                
                messages.append(ToolMessage(content=str(tool_output), tool_call_id=tool_id))

            # Early loop termination once Gate 1 passes
            if maven_passed:
                print(f"\n[Gate 1 Passed] Maven build and tests succeeded for {op_id}.")
                return {"success": True, "turns": turns, "reason": "MAVEN_PASS"}

        return {"success": False, "turns": turns, "reason": "EXHAUSTED_TURNS_OR_BUILD_FAIL"}


# =====================================================================
# Execution Block: Single-Item Benchmark & Double-Gated PR Creation
# =====================================================================
if __name__ == "__main__":
    target_repo = "https://github.com/Kartiksood10/acme-consumer-service.git"
    manager = SandboxManager()

    try:
        # 1. Start clean Docker sandbox
        manager.start_container(target_repo)

        # 2. Load migration specifications
        with open("migration_plan.json", "r") as f:
            plan_data = json.load(f)

        with open("migration_context.json", "r") as f:
            context_data = json.load(f)

        # 3. Isolate the target work item (Testing getUser again to verify guardrail)
        target_op_id = "getAddress"
        work_item_plan = next((item for item in plan_data["work_items"] if item["operation_id"] == target_op_id), None)
        
        # Fetch the complete context item for this operation
        context_item = next((item for item in context_data["work_items"] if item["operation_id"] == target_op_id), None)

        if not work_item_plan or not context_item:
            raise ValueError(f"Could not locate work item or context slice for '{target_op_id}'.")

        # Fallback for inferred replacements where 'target_contract' might not explicitly exist
        context_slice = context_item.get("target_contract") or context_item

        # Generic contract extraction
        source_path = work_item_plan.get("source_path")
        target_path = work_item_plan.get("target_path")
        target_method = work_item_plan.get("target_method")

        if not target_path or not target_method:
            raise ValueError(f"Work item plan for '{target_op_id}' is missing required routing attributes.")

        # 4. Gate 1: Autonomous Coder Agent
        agent = CoderAgent(manager)
        result = agent.execute_work_item(work_item_plan, context_slice, max_turns=30)

        if not result["success"]:
            print(f"\n❌ GATE 1 FAILED: Maven tests did not pass. Reason: {result['reason']}")
            exit(1)

        print("\n✅ GATE 1 PASSED: Maven build and unit tests passed.")

        # 5. Gate 2: Static Contract Validator
        validator = ContractValidator(manager)
        contract_passed, contract_diag = validator.validate_work_item(
            target_method=target_method,
            target_path=target_path,
            source_path=source_path
        )

        if not contract_passed:
            print(f"\n❌ GATE 2 FAILED: {contract_diag}")
            print("Aborting PR creation to protect upstream contract integrity.")
            exit(1)

        print(f"\n✅ GATE 2 PASSED: {contract_diag}")

        # 6. Working Tree Inspection
        print("\n========== GIT STATUS ==========")
        print(manager.get_git_status())

        print("\n========== GIT DIFF ==========")
        print(manager.get_git_diff())

        # Append a timestamp to ensure unique branch names on every run
        run_id = int(time.time())
        branch = f"migrate/op-{target_op_id.lower()}-{run_id}"
        commit_msg = f"refactor(api): migrate {target_op_id} to Target Contract"

        print(f"\nPushing branch '{branch}' and opening Pull Request...")
        manager.commit_and_push(branch, commit_msg)

        pr_title = f"Migrate `{target_op_id}` endpoint to Target Contract"
        pr_body = f"""## Autonomous Migration: `{target_op_id}`
This Pull Request was generated autonomously by the Acme Migration Worker.

### Strategy Summary
- **Classification**: {work_item_plan.get('classification')}
- **Target Method**: `{target_method}`
- **Target Path**: `{target_path}`
- **Reasoning**: {work_item_plan.get('reasoning_summary')}

### Dual-Gate Verification
- **Gate 1 (Maven Sandbox)**: `mvn clean test` passed in isolated container.
- **Gate 2 (Contract Validator)**: Validated target route, method binding, and removal of obsolete source paths.
"""
        pr_url = manager.create_github_pr(target_repo, branch, pr_title, pr_body)
        print(f"\n🎉 Benchmark complete! Pull Request created successfully:\n{pr_url}")

    except Exception as e:
        print(f"\nExecution failed: {e}")
    finally:
        manager.destroy_container()