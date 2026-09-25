# pipeline/context_builder.py
from typing import List, Dict, Any

# The ContextBuilder class transforms raw API diffs into a structured context payload for the LLM to create a plan
class ContextBuilder:
    """
    Transforms raw API diffs into a structured context payload for the LLM.
    Provides lightweight candidates for semantic matching to prevent token explosion.
    """
    def __init__(self, source_data: dict, target_data: dict, oasdiff_findings: list):
        self.source_data = source_data
        self.target_data = target_data
        self.oasdiff_findings = oasdiff_findings

    def _extract_endpoint(self, openapi_data: dict, target_op_id: str) -> dict:
        """Finds an endpoint by operationId and returns its full schema."""
        if not openapi_data or "paths" not in openapi_data:
            return None

        for path, methods in openapi_data["paths"].items():
            for method, details in methods.items():
                if details.get("operationId") == target_op_id:
                    return {
                        "path": path,
                        "method": method.upper(),
                        "details": details
                    }
        return None

    def build_context(self) -> dict:
        """
        Groups structural diffs by operationId and pairs them with full schemas if mapped.
        If unmapped, provides lightweight candidates for the Planner.
        """
        print("Grouping findings and resolving JSON schemas...")
        work_items_map = {}

        for finding in self.oasdiff_findings:
            op_id = finding.get("operationId", "unknown")
            if op_id not in work_items_map:
                work_items_map[op_id] = set()
            work_items_map[op_id].add(finding["text"])

        final_work_items = []
        for op_id, findings in work_items_map.items():
            if op_id == "unknown":
                continue

            source_contract = self._extract_endpoint(self.source_data, op_id)
            target_contract = self._extract_endpoint(self.target_data, op_id)
            target_candidates = []

            # LIGHTWEIGHT CANDIDATES: Prevent token explosion. 
            # Only send routing metadata to the Planner, not the heavy DTOs.
            if not target_contract:
                for path, methods in self.target_data.get("paths", {}).items():
                    for method, details in methods.items():
                        target_candidates.append({
                            "operationId": details.get("operationId"),
                            "path": path,
                            "method": method.upper()
                        })

            final_work_items.append({
                "operation_id": op_id,
                "oasdiff_findings": list(findings),
                "source_contract": source_contract,
                "target_contract": target_contract,
                "target_candidates": target_candidates if target_candidates else None
            })

        return {"work_items": final_work_items}