# In Python, the pydantic library is the gold standard for data validation. 
# Think of a Pydantic BaseModel just like a Java POJO annotated with Lombok and Jackson. 
# It ensures the data moving through your application is strictly typed.
# LangChain uses these Pydantic models to force the LLM to output perfect JSON that exactly matches this shape.

from pydantic import BaseModel, Field
from typing import List

# Concept: In Python, type hinting (e.g., change_type: str) is technically optional, 
# but Pydantic uses it to enforce strict runtime validation.

class RequiredChange(BaseModel):
    """Represents a single, actionable mutation the Coder must make."""
    change_type: str = Field(description="Generic category, e.g., 'HTTP_METHOD_UPDATE', 'DTO_RESTRUCTURE', 'CALLER_UPDATE'")
    action: str = Field(description="Clear, actionable instruction of what must change. Do not use specific Java class names.")

class WorkItemPlan(BaseModel):
    """The complete migration strategy for a single API endpoint."""
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
    """The master plan containing all work items."""
    work_items: List[WorkItemPlan] = Field(description="List of all planned endpoint migrations.")