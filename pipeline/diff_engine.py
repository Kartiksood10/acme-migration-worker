import subprocess
import json
import tempfile
import os
from typing import Dict, Any, List, Optional, Tuple

# Uses oasdiff CLI to detect breaking changes between source and target OpenAPI contracts
class DiffEngine:
    """
    Computes breaking changes between two in-memory OpenAPI dictionaries.
    Uses ephemeral OS temp files to interface securely with the oasdiff CLI.
    Auto-detects base path shifts to support generic migrations.
    """
    def __init__(self):
        pass

    def _execute_oasdiff(self, base_path: str, revision_path: str) -> list:
        """Runs the oasdiff CLI against two physical file paths and returns JSON."""
        command = [
            "oasdiff", "breaking",
            base_path, revision_path,
            "--format", "json"
        ]
        
        result = subprocess.run(command, capture_output=True, text=True)
        raw_output = result.stdout.strip()
        error_output = result.stderr.strip()
        
        if error_output:
            print(f"OASDiff Diagnostic: {error_output}")
             
        if not raw_output or raw_output == "[]":
            return []
            
        return json.loads(raw_output)

    def _auto_detect_mapping(self, source_openapi: Dict[str, Any], target_openapi: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        """
        Dynamically calculates the common base path for both contracts.
        Example: If Source paths start with '/api/v1' and Target paths start with '/api/v2',
        it returns ('/api/v1', '/api/v2').
        """
        def get_common_prefix(openapi_dict: dict) -> str:
            paths = list(openapi_dict.get("paths", {}).keys())
            if not paths:
                return ""
            
            # Split paths by '/' to compare directory levels 
            # e.g. ['', 'api', 'v1', 'address']
            split_paths = [p.strip("/").split("/") for p in paths]
            common_parts = []
            
            # Zip allows us to iterate through the path parts vertically across all endpoints
            for chars in zip(*split_paths):
                # If all endpoints share this exact path segment, keep it
                if len(set(chars)) == 1:
                    common_parts.append(chars[0])
                else:
                    break
            return "/" + "/".join(common_parts) if common_parts else ""

        src_prefix = get_common_prefix(source_openapi)
        tgt_prefix = get_common_prefix(target_openapi)

        # Only return a mapping if a definitive version shift is detected
        if src_prefix and tgt_prefix and src_prefix != tgt_prefix:
            print(f"Auto-detected base path shift: {src_prefix} -> {tgt_prefix}")
            return (src_prefix, tgt_prefix)
        
        return None

    def get_breaking_changes(self, source_openapi: Dict[str, Any], target_openapi: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Detects breaking changes. Normalizes path shifts automatically if detected.
        """
        source_str = json.dumps(source_openapi)
        target_str = json.dumps(target_openapi)

        # 1. Create secure, ephemeral temp files that the OS tracks and isolates
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as src_file, \
             tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as tgt_file:
            
            src_file.write(source_str)
            tgt_file.write(target_str)
            src_path, tgt_path = src_file.name, tgt_file.name

        try:
            print("Running Pass 1: Checking for strict routing changes...")
            pass1_findings = self._execute_oasdiff(src_path, tgt_path)

            print("Running Pass 2: Checking for normalized schema changes...")
            
            # Auto-detect the mapping instead of requiring manual UI configuration
            path_mapping = self._auto_detect_mapping(source_openapi, target_openapi)
            
            if path_mapping:
                source_prefix, target_prefix = path_mapping
                source_str = source_str.replace(source_prefix, target_prefix)

            # Create an isolated temp file for the normalized source
            with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as norm_src_file:
                norm_src_file.write(source_str)
                norm_src_path = norm_src_file.name

            try:
                pass2_findings = self._execute_oasdiff(norm_src_path, tgt_path)
            finally:
                # Instantly destroy the normalized temp file
                if os.path.exists(norm_src_path):
                    os.remove(norm_src_path)

        finally:
            # 2. Guarantee destruction of primary temporary files regardless of exceptions
            if os.path.exists(src_path):
                os.remove(src_path)
            if os.path.exists(tgt_path):
                os.remove(tgt_path)

        # Merge findings using the unique fingerprint to prevent overwriting distinct endpoint changes
        merged_findings = {f.get('fingerprint'): f for f in pass1_findings + pass2_findings if f.get('fingerprint')}
        return list(merged_findings.values())