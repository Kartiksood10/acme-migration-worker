import subprocess
import json
import urllib.request
import tempfile
import os

# Input : source_openapi.json, target_openapi.json
# Output: raw_diffs.json (using oasdiff)
class DiffEngine:
    def __init__(self):
        print("DiffEngine initialized. Ready to compute API contracts.")

    def _execute_oasdiff(self, base_source: str, revision_source: str) -> list:
        """
        Runs the oasdiff CLI and returns the JSON output.

        Args:
            base_source (str): The path to the base OpenAPI specification.
            revision_source (str): The path to the revision OpenAPI specification.

        Returns:
            list: A list of breaking changes detected by oasdiff.
        """
        command = [
            "oasdiff",
            "breaking",
            base_source,
            revision_source,
            "--format",
            "json"
        ]
        
        result = subprocess.run(command, capture_output=True, text=True)
        raw_output = result.stdout.strip()
        error_output = result.stderr.strip()
        
        if "connection refused" in error_output.lower() or "no such host" in error_output.lower():
             raise ConnectionError("ERROR: Could not connect to the Producer. Is Spring Boot running?")
             
        if not raw_output or raw_output == "[]":
            return []
            
        return json.loads(raw_output)

    def get_breaking_changes(self, source_url: str, target_url: str, path_mapping: tuple = None) -> list:
        """
        The main entry point for detecting breaking changes between two API contracts.

        Args:
            source_url (str): The URL to the source API contract.
            target_url (str): The URL to the target API contract.
            path_mapping (tuple, optional): A mapping of paths between the source and target contracts. Defaults to None.

        Returns:
            list: A list of breaking changes detected by oasdiff.
        """
        
        print("Running Pass 1: Checking for base path and routing changes...")
        # Note: In the MVP, oasdiff outputs JSON directly, so we just use the execution output.
        pass1_findings = self._execute_oasdiff(source_url, target_url)

        print("Running Pass 2: Checking for normalized schema and parameter changes...")
        with urllib.request.urlopen(source_url) as response:
            source_json = response.read().decode('utf-8')

        if path_mapping:
            source_prefix, target_prefix = path_mapping
            source_json = source_json.replace(source_prefix, target_prefix)

        temp_source_path = "temp_normalized_source.json"
        with open(temp_source_path, "w") as f:
            f.write(source_json)

        pass2_findings = self._execute_oasdiff(temp_source_path, target_url)

        if os.path.exists(temp_source_path):
            os.remove(temp_source_path)

        # Merge findings using the unique fingerprint to prevent overwriting distinct endpoint changes
        merged_findings = {f.get('fingerprint'): f for f in pass1_findings + pass2_findings if f.get('fingerprint')}
        return list(merged_findings.values())

# =====================================================================
# Execution Block: Fetch live specs and save for context_builder.py
# =====================================================================
if __name__ == "__main__":
    engine = DiffEngine()
    
    # 1. Define your live local Spring Boot endpoints
    source_url = "http://localhost:8080/v3/api-docs/v1"
    target_url = "http://localhost:8080/v3/api-docs/v2"
    
    try:
        # 2. Download and save the raw OpenAPI specs
        print("Downloading live OpenAPI specifications...")
        urllib.request.urlretrieve(source_url, "source_openapi.json")
        urllib.request.urlretrieve(target_url, "target_openapi.json")
        
        # 3. Execute the diff engine (passing the path mapping for normalization)
        changes = engine.get_breaking_changes(source_url, target_url, path_mapping=('/api/v1', '/api/v2'))
        
        # 4. Save the raw diffs
        with open("raw_diffs.json", "w") as f:
            json.dump(changes, f, indent=2)
            
        print(f"\nSUCCESS: Saved source_openapi.json, target_openapi.json, and raw_diffs.json ({len(changes)} breaking changes found).")
        
    except Exception as error:
        print(error)