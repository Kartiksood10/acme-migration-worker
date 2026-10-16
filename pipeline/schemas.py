# In Python, the pydantic library is the gold standard for data validation. 
# Think of a Pydantic BaseModel just like a Java POJO annotated with Lombok and Jackson. 
# It ensures the data moving through your application is strictly typed.
# LangChain uses these Pydantic models to force the LLM to output perfect JSON that exactly matches this shape.
# Concept: In Python, type hinting (e.g., change_type: str) is technically optional, 
# but Pydantic uses it to enforce strict runtime validation.

from pydantic import BaseModel, Field
from typing import List
from enum import Enum
from typing import Optional

# ---------------------------------------------------------
# INPUT CONFIGURATION SCHEMAS
# These handle how the worker receives the API contracts.
# ---------------------------------------------------------

class ContractType(str, Enum):
    """
    Acts as a strict toggle for the API payload. 
    By extending Enum, FastAPI and Pydantic will automatically reject any API request 
    that doesn't strictly use "URL" or "UPLOAD".
    """
    URL = "URL"
    UPLOAD = "UPLOAD"

class ContractReference(BaseModel):
    """
    The main input schema for the /migrations endpoint. 
    It dynamically routes the contract parsing engine: if 'URL' is passed, the worker 
    knows to execute an HTTP GET to fetch the spec. If 'UPLOAD' is passed, it reads 
    the raw string directly from memory.
    """
    type: ContractType
    location: Optional[str] = Field(default=None, description="The HTTP URL to fetch the OpenAPI spec.")
    content: Optional[str] = Field(default=None, description="The raw JSON or YAML string uploaded by the user.")


# ---------------------------------------------------------
# LLM OUTPUT GENERATION SCHEMAS
# These are bound to the Planning Agent to force it to 
# output perfectly structured JSON arrays instead of chat text.
# ---------------------------------------------------------

class RequiredChange(BaseModel):
    """
    The atomic unit of work for the Coder Agent.
    Instead of giving the Coder a massive paragraph of instructions, the Planner must 
    break the migration down into discrete, actionable steps (e.g., updating a Feign client, 
    renaming a DTO field).
    """
    change_type: str = Field(description="Generic category, e.g., 'HTTP_METHOD_UPDATE', 'DTO_RESTRUCTURE', 'CALLER_UPDATE'")
    action: str = Field(description="Clear, actionable instruction of what must change. Do not use specific Java class names.")

class WorkItemPlan(BaseModel):
    """
    The complete context blueprint for a single API endpoint. 
    This schema forces the LLM to map out the exact delta between the source and target 
    contracts before writing any code. It dictates what the Coder Agent needs to find 
    (discovery_requirements) and what it needs to execute (required_changes).
    """
    operation_id: str = Field(description="The source operationId this work item handles. Treat as a correlation hint, not guaranteed Java identity.")
    classification: str = Field(description="The generic category of this migration, e.g., 'METHOD_SHIFT', 'FLAT_TO_NESTED'")
    
    source_method: str = Field(description="The HTTP method in the Source contract.")
    source_path: str = Field(description="The HTTP path in the Source contract.")
    
    target_method: str = Field(description="The HTTP method in the Target contract.")
    target_path: str = Field(description="The HTTP path in the Target contract.")
    
    reasoning_summary: str = Field(description="Brief explanation of why this classification was chosen based on the provided schemas.")
    discovery_requirements: List[str] = Field(description="Specific steps the execution agent must take to dynamically discover the affected Java files.")
    required_changes: List[RequiredChange] = Field(description="The sequence of code mutations required after discovery is complete.")

class MigrationPlan(BaseModel):
    """
    The root wrapper schema bound to the LangChain tool.
    By wrapping a List[WorkItemPlan] in a parent BaseModel, the LLM parser guarantees 
    it will return a unified JSON object containing the full array of endpoints to process.
    """
    work_items: List[WorkItemPlan] = Field(description="List of all planned endpoint migrations.")