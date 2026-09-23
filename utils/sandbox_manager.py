import os
import docker
from dotenv import load_dotenv

# 1. Load environment variables
# This reads the .env file in your folder and injects its contents into the system environment
load_dotenv()

class SandboxManager:
    def __init__(self):
        """
        The constructor: This runs exactly once when we create a new SandboxManager.
        It sets up our connection to Docker and verifies our credentials.
        """
        # 2. Connect to the local Docker Daemon
        # 'from_env()' tells the Python library to look for Docker Desktop on your machine
        # just like your terminal does when you type 'docker run'.
        self.client = docker.from_env()
        
        # We initialize the container variable as None. We will create it in the next step.
        self.container = None
        
        # 3. Load the GitHub Token securely
        self.github_token = os.getenv("GITHUB_PAT")
        
        # Safety Check: If the token is missing, crash the program immediately.
        # This prevents the script from spinning up a container it can't use.
        if not self.github_token:
            raise ValueError("CRITICAL ERROR: GITHUB_PAT not found in .env file!")
            
        print("SandboxManager initialized. Connected to Docker daemon.")

    def start_container(self, repo_url: str):
        """
        Spins up an isolated Maven container and clones the target repository.
        """
        print("Starting the Maven Docker sandbox...")
        
        # 1. Start the container in detached mode (background)
        # We use Java 21 / Maven 3.9 to perfectly match your Spring Boot setup.
        # 'tail -f /dev/null' is a Linux trick that forces the container to stay awake infinitely.
        self.container = self.client.containers.run(
            image="maven:3.9-eclipse-temurin-21",
            command="tail -f /dev/null",
            detach=True,
            working_dir="/workspace" # This is where we will do all our work inside the container
        )
        print(f"Container started! ID: {self.container.id[:10]}")
        
        # 2. Inject the GitHub Personal Access Token into the URL
        # We change 'https://github.com/...' to 'https://TOKEN@github.com/...'
        # This allows git to bypass the password prompt.
        auth_url = repo_url.replace("https://", f"https://{self.github_token}@")
        
        print(f"Cloning repository into the sandbox...")
        
        # 3. Execute the Git Clone command INSIDE the running container
        # We clone it into a folder named 'app'
        exit_code, output = self.container.exec_run(f"git clone {auth_url} app")
        
        # 4. Verify success. In Linux, an exit code of 0 means "Success".
        if exit_code == 0:
            print("Repository cloned successfully!")
        else:
            # If it fails, we decode the byte output to a string so we can read the error
            raise RuntimeError(f"Clone failed: {output.decode('utf-8')}")

    def run_maven_test(self):
        """
        Executes 'mvn clean test' inside the cloned repository.
        Returns a tuple: (success_boolean, console_output_string)
        """
        print("Executing 'mvn clean test' inside the sandbox...")
        
        if not self.container:
            raise RuntimeError("Container is not running. Call start_container() first.")

        # Execute the Maven command. 
        # 'workdir=/workspace/app' tells Docker to run this specifically inside the cloned repo.
        exit_code, output = self.container.exec_run(
            "mvn clean test",
            workdir="/workspace/app"
        )
        
        # Decode the raw bytes output into a readable Python string
        logs = output.decode("utf-8")
        
        # Exit code 0 means the build passed. Anything else means compilation or test failure.
        is_success = (exit_code == 0)
        
        if is_success:
            print("Maven Build: SUCCESS")
        else:
            print("Maven Build: FAILED")
            
        return is_success, logs

    def destroy_container(self):
        """
        Stops and removes the Docker container to free up system resources.
        """
        if self.container:
            print(f"Destroying sandbox {self.container.id[:10]}...")
            self.container.stop()
            self.container.remove()
            self.container = None
            print("Sandbox successfully destroyed.")


    def get_git_status(self) -> str:
        """Returns the current git status of the working tree inside the container."""
        if not self.container:
            return "Container not running."
        exit_code, out = self.container.exec_run("git status --short", workdir="/workspace/app")
        return out.decode("utf-8").strip()
    

    def get_git_diff(self) -> str:
        """Returns the uncommitted git diff inside the container."""
        if not self.container:
            return "Container not running."
        exit_code, out = self.container.exec_run("git diff", workdir="/workspace/app")
        return out.decode("utf-8").strip()
    

    def commit_and_push(self, branch_name: str, commit_message: str) -> str:
        """Creates branch, stages changes, commits, and pushes to remote."""
        if not self.container:
            raise RuntimeError("Container is not running.")

        self.container.exec_run('git config user.name "Autonomous Migration Bot"', workdir="/workspace/app")
        self.container.exec_run('git config user.email "bot@acme-migration.internal"', workdir="/workspace/app")

        # Checkout new branch
        exit_code, out = self.container.exec_run(f"git checkout -b {branch_name}", workdir="/workspace/app")
        if exit_code != 0:
            raise RuntimeError(f"Branch checkout failed: {out.decode('utf-8')}")

        # Stage and commit
        self.container.exec_run("git add .", workdir="/workspace/app")
        sanitized_msg = commit_message.replace('"', '\\"')
        exit_code, out = self.container.exec_run(f'git commit -m "{sanitized_msg}"', workdir="/workspace/app")
        if exit_code != 0:
            raise RuntimeError(f"Git commit failed: {out.decode('utf-8')}")

        # Push to remote origin
        exit_code, out = self.container.exec_run(f"git push -u origin {branch_name}", workdir="/workspace/app")
        if exit_code != 0:
            raise RuntimeError(f"Git push failed: {out.decode('utf-8')}")

        return branch_name
    

    def create_github_pr(self, repo_url: str, branch_name: str, title: str, body: str) -> str:
        """Creates a Pull Request via GitHub REST API."""
        import json
        import urllib.request

        cleaned_url = repo_url.rstrip("/").removesuffix(".git")
        parts = cleaned_url.split("/")
        owner, repo_name = parts[-2], parts[-1]

        exit_code, base_out = self.container.exec_run("git rev-parse --abbrev-ref origin/HEAD", workdir="/workspace/app")
        base_branch = base_out.decode("utf-8").strip().replace("origin/", "") if exit_code == 0 else "main"

        api_url = f"https://api.github.com/repos/{owner}/{repo_name}/pulls"
        headers = {
            "Authorization": f"Bearer {self.github_token}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json"
        }
        payload = {
            "title": title,
            "body": body,
            "head": branch_name,
            "base": base_branch
        }

        req = urllib.request.Request(api_url, data=json.dumps(payload).encode("utf-8"), headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req) as response:
                res_data = json.loads(response.read().decode("utf-8"))
                return res_data.get("html_url")
        except urllib.error.HTTPError as e:
            raise RuntimeError(f"GitHub PR failed ({e.code}): {e.read().decode('utf-8')}")

# --- Temporary Test Block ---
if __name__ == "__main__":
    manager = SandboxManager()
    
    target_repo = "https://github.com/Kartiksood10/acme-consumer-service.git"
    
    # 1. Start container and clone
    manager.start_container(target_repo)
    
    # 2. Run the tests
    success, build_logs = manager.run_maven_test()
    
    # 3. Print the result
    print("\n--- Maven Output Preview ---")
    # Print the last 15 lines of the logs to see the test results
    print("\n".join(build_logs.splitlines()[-15:]))

    # 4. Clean up resources
    manager.destroy_container()