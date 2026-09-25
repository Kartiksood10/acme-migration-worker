# pipeline/contract_resolver.py
import json
import yaml
import requests
from typing import Dict, Any
from pipeline.schemas import ContractReference, ContractType

# Extracts an OpenAPI contract from a URL or raw JSON/YAML string
class ContractResolver:
    """
    Fetches OpenAPI contracts, parses them, and recursively resolves all 
    $ref pointers so downstream AI agents receive fully expanded schemas in memory.
    """

    def resolve(self, reference: ContractReference) -> Dict[str, Any]:
        """Entry point that handles either URL fetching or raw UPLOAD parsing."""
        if reference.type == ContractType.URL:
            if not reference.location:
                raise ValueError("Location (URL) must be provided for URL contract type.")
            raw_content = self._fetch_from_url(reference.location)
            
        elif reference.type == ContractType.UPLOAD:
            if not reference.content:
                raise ValueError("Content must be provided for UPLOAD contract type.")
            raw_content = reference.content
        else:
            raise ValueError(f"Unsupported contract type: {reference.type}")

        parsed_dict = self._parse_content(raw_content)
        
        # Flatten all $ref pointers immediately after parsing to prevent AI hallucination
        return self._resolve_refs(parsed_dict, root_doc=parsed_dict)

    # OpenAPI contract fetched from URL (for eg : http://localhost:8080/v3/api-docs/v1)
    def _fetch_from_url(self, url: str) -> str:
        """Executes an HTTP GET to retrieve the contract with a 10-second safety timeout."""
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            return response.text
        except requests.RequestException as e:
            raise RuntimeError(f"Failed to fetch contract from URL: {url}. Error: {e}")

    # OpenAPI contract fetched from uploaded JSON/YAML file (for eg : source_openapi.json, target_openapi.json)
    def _parse_content(self, content: str) -> Dict[str, Any]:
        """Dynamically detects and parses JSON. Falls back to YAML if JSON fails."""
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass
            
        try:
            # yaml.safe_load prevents arbitrary code execution from malicious uploaded files
            parsed_yaml = yaml.safe_load(content)
            if not isinstance(parsed_yaml, dict):
                raise ValueError("Parsed YAML is not a valid dictionary.")
            return parsed_yaml
        except yaml.YAMLError as e:
            raise ValueError(f"Failed to parse contract as JSON or YAML: {e}")

    # Expand all the $ref pointers to get full DTO structure
    def _resolve_refs(self, node: Any, root_doc: Dict[str, Any], seen_refs: set = None) -> Any:
        """
        Recursively traverses the dictionary. Whenever it finds a {"$ref": "..."},
        it looks up the actual object in the root document and injects it in place.
        """
        if seen_refs is None:
            seen_refs = set()

        if isinstance(node, dict):
            if "$ref" in node and isinstance(node["$ref"], str):
                ref_path = node["$ref"]
                
                # Prevent infinite recursion if the OpenAPI spec has circular dependencies
                if ref_path in seen_refs:
                    return {"description": f"Circular reference to {ref_path} omitted."}
                
                seen_refs.add(ref_path)
                
                # Navigate the root document to find the referenced object
                parts = ref_path.lstrip("#/").split("/")
                resolved = root_doc
                
                try:
                    for part in parts:
                        resolved = resolved[part]
                    # Recursively resolve the injected object in case it has its own nested refs
                    return self._resolve_refs(resolved, root_doc, seen_refs)
                except (KeyError, TypeError):
                    return node # If the ref is broken, return it as-is
            
            # If it's a normal dictionary, resolve its children
            return {k: self._resolve_refs(v, root_doc, seen_refs.copy()) for k, v in node.items()}
            
        elif isinstance(node, list):
            # Resolve items inside arrays
            return [self._resolve_refs(item, root_doc, seen_refs.copy()) for item in node]
            
        return node