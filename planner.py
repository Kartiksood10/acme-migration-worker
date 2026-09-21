import os
import json
from dotenv import load_dotenv
from langchain_openai import ChatOpenAI
from langchain_core.prompts import ChatPromptTemplate

# 1. Import our custom Pydantic schemas from the schemas.py file we just created
from schemas import MigrationPlan

class MigrationPlanner:
    def __init__(self):
        # Concept: load_dotenv() automatically parses the .env file and loads the variables into os.environ
        load_dotenv()
        
        # Fetch the model name from our config. If it's missing, default to gpt-5.6-luna.
        model_name = os.getenv("OPENAI_MODEL", "gpt-5.6-luna")
        
        # Concept: Temperature=0 makes the LLM deterministic. It will pick the most logical tokens, 
        # eliminating creative hallucinations. Perfect for coding tasks.
        self.llm = ChatOpenAI(
            model=model_name,
            temperature=0
        )
        
        # We wrap the standard LLM with our Pydantic schema. 
        # Under the hood, LangChain translates our Python classes into a JSON Schema 
        # and passes it to the OpenAI API's 'response_format' parameter.
        self.structured_llm = self.llm.with_structured_output(MigrationPlan)
        
        # Load the externalized system prompt
        self.system_prompt = self._load_prompt("prompts/planner_prompt.txt")

    def _load_prompt(self, filepath: str) -> str:
        """
        Helper method to read a text file from disk.
        Concept: 'with open(...)' is a Context Manager. It automatically closes the file 
        after reading it, preventing memory leaks (similar to Java's try-with-resources).
        """
        try:
            with open(filepath, "r") as file:
                return file.read()
        except FileNotFoundError:
            raise FileNotFoundError(f"CRITICAL: Could not find prompt file at {filepath}")

    def generate_plan(self, context_data: dict) -> MigrationPlan:
        """
        Takes the migration_context.json dictionary and passes it to the LLM.
        Returns a strongly-typed MigrationPlan Python object.
        """
        print(f"Generating Master Migration Plan using {self.llm.model_name}...")
        
        # ChatPromptTemplate formats the conversation history.
        # We pass our loaded text as the "system" instructions, and the JSON as the "human" input.
        prompt_template = ChatPromptTemplate.from_messages([
            ("system", self.system_prompt),
            ("human", "Here is the migration context output from the Context Builder:\n\n{context_json}")
        ])

        # Concept: LCEL (LangChain Expression Language).
        # The '|' operator pipes the output of the prompt template directly into the LLM.
        chain = prompt_template | self.structured_llm
        
        # Execute the chain, passing in our dictionary as a formatted JSON string
        result = chain.invoke({"context_json": json.dumps(context_data, indent=2)})
        return result

# =====================================================================
# Execution Block (For local testing)
# =====================================================================
if __name__ == "__main__":
    # 1. Load the context file generated in Step 1
    try:
        with open("migration_context.json", "r") as f:
            context_payload = json.load(f)
    except FileNotFoundError:
        print("Error: migration_context.json not found. Run context_builder.py first.")
        exit(1)

    # 2. Initialize and run the planner
    planner = MigrationPlanner()
    try:
        # This returns a MigrationPlan Pydantic object
        plan = planner.generate_plan(context_payload)
        
        # 3. Save the result to disk
        output_filename = "migration_plan.json"
        with open(output_filename, "w") as f:
            # Concept: .model_dump() converts a Pydantic object back into a standard Python dictionary
            json.dump(plan.model_dump(), f, indent=2)
            
        print(f"Planning complete! Master plan saved to {output_filename}")
        
    except Exception as e:
        print(f"Planning failed: {e}")