from sandbox_manager import SandboxManager

# Ensures that all old API endpoints have been updated to the new API endpoints based on the input openapi.json
class ContractValidator:
    """
    Independent verification gate. Checks that Java source files
    strictly comply with Target contracts beyond Maven compilation.
    """
    def __init__(self, sandbox_manager: SandboxManager):
        self.manager = sandbox_manager

    def validate_work_item(self, target_method: str, target_path: str, source_path: str = None) -> tuple[bool, str]:
        if not self.manager.container:
            return False, "Container not running."

        # 1. Verify target path is present and bound to the correct HTTP Method
        # FIX: Wrap in 'sh -c' to process the '||' operator
        command_target = ["sh", "-c", f"grep -rn '{target_path}' src/main/java || true"]
        exit_code, target_matches = self.manager.container.exec_run(command_target, workdir="/workspace/app")
        
        matched_lines = target_matches.decode("utf-8").strip()
        if not matched_lines:
            return False, f"CONTRACT VIOLATION: Required target path '{target_path}' not found in source code."

        method_annotation_map = {
            "GET": "GetMapping",
            "POST": "PostMapping",
            "PUT": "PutMapping",
            "DELETE": "DeleteMapping"
        }
        expected_annotation = method_annotation_map.get(target_method.upper(), "RequestMapping")
        
        if not any(expected_annotation in line for line in matched_lines.split('\n')):
            if not any(f"RequestMethod.{target_method.upper()}" in line for line in matched_lines.split('\n')):
                return False, f"CONTRACT VIOLATION: Path '{target_path}' found, but expected HTTP method '{expected_annotation}' is missing."

        # 2. Check for stale Source binding ONLY if the path changed
        if source_path and source_path != target_path:
            # FIX: Wrap in 'sh -c' to process the '||' operator
            command_source = ["sh", "-c", f"grep -rn '{source_path}' src/main/java || true"]
            exit_code, source_matches = self.manager.container.exec_run(command_source, workdir="/workspace/app")
            
            stale_lines = source_matches.decode("utf-8").strip()
            # If the source path is still found alongside Feign mapping annotations, it's a violation
            if stale_lines and any(mapping in stale_lines for mapping in ["Mapping(", "FeignClient"]):
                return False, f"CONTRACT VIOLATION: Stale source binding '{source_path}' is still active in Feign client."

        return True, "CONTRACT_PASS: Target route and method verified. Stale routes removed."