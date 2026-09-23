import os
import base64
from langchain_core.tools import tool
from utils.sandbox_manager import SandboxManager

# List of tools that the LLM can use to inspect and modify the target repository.
# The @tool annotation allows LangChain to translate the function's name, required arguments, and description into a JSON schema that the LLM can read.
# When the LLM decides to use a tool, it outputs a JSON request. LangChain intercepts this request, and Python executes the actual code (inside the Docker sandbox).
# This back-and-forth execution loop (ReAct) continues until the LLM achieves a passing build.
def build_agent_tools(manager: SandboxManager):
    """
    Factory function that creates tool instances bound to a specific SandboxManager.
    """

    @tool
    def search_symbol(query: str) -> str:
        """
        Executes a bounded grep search inside the repository.
        Use concrete paths (e.g. '/api/v1/address') or class names as queries.
        """
        if not manager.container:
            return "ERROR: Sandbox container is not running."

        # FIX: Wrap in 'sh -c' to parse '||' correctly, and exclude '.git' to stop binary pollution
        command = ["sh", "-c", f"grep -rn --exclude-dir=.git '{query}' . || true"]
        exit_code, output = manager.container.exec_run(command, workdir="/workspace/app")
        lines = output.decode("utf-8").strip().split('\n')

        if not lines or lines == ['']:
            return f"No matches found for '{query}'."

        # Bound context to 10 matches
        truncated = lines[:10]
        result = "\n".join(truncated)
        if len(lines) > 10:
            result += f"\n... (and {len(lines) - 10} more matches. Narrow search query or inspect lines)."
        return result

    @tool
    def read_file_lines(filepath: str, start_line: int, end_line: int) -> str:
        """
        Reads a specific range of lines from a Java file (max 100 lines).
        """
        if not manager.container:
            return "ERROR: Sandbox container is not running."

        # Prevent context explosion
        if end_line - start_line > 100:
            end_line = start_line + 100

        # FIX: Wrap in 'sh -c' to parse the '||' operator correctly
        command = ["sh", "-c", f"sed -n '{start_line},{end_line}p' {filepath} || echo 'FILE_NOT_FOUND'"]
        exit_code, output = manager.container.exec_run(command, workdir="/workspace/app")
        return output.decode("utf-8").strip()

    @tool
    def apply_targeted_patch(filepath: str, target_block: str, replacement_block: str) -> str:
        """
        Performs an exact search-and-replace edit on a file.
        target_block must match exactly once in the file (including whitespace).
        """
        if not manager.container:
            return "ERROR: Sandbox container is not running."

        exit_code, raw_output = manager.container.exec_run(["cat", filepath], workdir="/workspace/app")
        if exit_code != 0:
            return f"ERROR: Could not read file {filepath}"

        file_content = raw_output.decode("utf-8")

        # Deterministic patch safety checks
        occurrences = file_content.count(target_block)
        if occurrences == 0:
            return "PATCH FAILED: target_block not found. Inspect file with read_file_lines first."
        if occurrences > 1:
            return "PATCH FAILED: target_block matches multiple locations. Include surrounding context lines."

        new_content = file_content.replace(target_block, replacement_block)

        # Base64 shell escaping to preserve Java formatting and special characters
        encoded_content = base64.b64encode(new_content.encode("utf-8")).decode("utf-8")
        
        # FIX: Wrap in 'sh -c' so the pipe (|) and redirect (>) operators work inside Docker
        write_cmd = ["sh", "-c", f"echo '{encoded_content}' | base64 -d > {filepath}"]
        manager.container.exec_run(write_cmd, workdir="/workspace/app")

        return f"SUCCESS: File {filepath} patched successfully."

    @tool
    def create_new_java_file(filepath: str, file_content: str) -> str:
        """
        Creates a new Java file at the specified path.
        Fails if the file already exists to avoid accidental overwrites.
        """
        if not manager.container:
            return "ERROR: Sandbox container is not running."

        # Check if file already exists
        check_code, _ = manager.container.exec_run(["test", "-f", filepath], workdir="/workspace/app")
        if check_code == 0:
            return f"ERROR: File {filepath} already exists. Use apply_targeted_patch instead."

        encoded_content = base64.b64encode(file_content.encode("utf-8")).decode("utf-8")
        dir_path = os.path.dirname(filepath)
        manager.container.exec_run(["mkdir", "-p", dir_path], workdir="/workspace/app")

        # FIX: Wrap in 'sh -c' for pipe and redirect
        write_cmd = ["sh", "-c", f"echo '{encoded_content}' | base64 -d > {filepath}"]
        manager.container.exec_run(write_cmd, workdir="/workspace/app")

        return f"SUCCESS: New file created at {filepath}."

    @tool
    def run_maven_validation() -> str:
        """
        Executes 'mvn clean test' inside the sandbox.
        Returns 'MAVEN_PASS' or 'MAVEN_FAIL' with bounded compilation and Surefire diagnostic logs.
        """
        success, logs = manager.run_maven_test()
        if success:
            return "MAVEN_PASS"

        relevant_lines = []
        capture_test_summary = False

        for line in logs.split('\n'):
            line_clean = line.strip()
            if "[ERROR]" in line and ("COMPILATION ERROR" in line or ".java:[" in line):
                relevant_lines.append(line_clean)
            elif "Failed tests:" in line or "Tests run:" in line and "Failures:" in line:
                capture_test_summary = True
                relevant_lines.append(line_clean)
            elif capture_test_summary and line_clean.startswith("[ERROR]"):
                relevant_lines.append(line_clean)
            elif capture_test_summary and line_clean == "":
                capture_test_summary = False

        if not relevant_lines:
            relevant_lines = [line for line in logs.split('\n') if "[ERROR]" in line]

        bounded_diag = "\n".join(relevant_lines[:25])
        return f"MAVEN_FAIL\nDiagnostics:\n{bounded_diag}"

    return [search_symbol, read_file_lines, apply_targeted_patch, create_new_java_file, run_maven_validation]