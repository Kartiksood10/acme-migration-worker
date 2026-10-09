# API Contract Migration Engine (ACME) Migration Worker

**An autonomous AI-powered migration worker that migrates Java Spring Boot consumers across breaking REST API contract changes.**

API Contract Migration Engine (ACME) automates one of the most tedious tasks in microservice development: updating downstream services when an upstream API evolves. By combining OpenAPI contract analysis, LLM-powered code generation, LangGraph orchestration, and isolated Docker execution, ACME transforms API migration from a manual refactoring task into an autonomous engineering workflow.

Instead of merely identifying breaking changes, ACME discovers affected Java code, applies targeted modifications, validates the changes, and raises GitHub Pull Requests for human review.

## 🚀 Key Features

- **Automated API Contract Analysis:** Compares Source and Target OpenAPI specifications using `oasdiff` to identify breaking changes in endpoints, HTTP methods, parameters, and request/response schemas.
- **Agentic Code Migration:** Uses LLM reasoning and controlled repository tools to discover affected Java clients, DTOs, service logic, and unit tests.
- **Three-Tier LangGraph Architecture:** Separates migration planning, workflow orchestration, and autonomous code execution into distinct graphs.
- **Dynamic Schema Resolution:** Retrieves authoritative Target API schemas from the loaded OpenAPI specification when diff findings lack sufficient schema details.
- **Closed-Loop Validation:** Runs Maven compilation and tests, feeds failures back into the Coder Agent, and supports iterative code repair.
- **Docker Sandbox:** Executes repository modifications and builds in an isolated, disposable workspace.
- **Autonomous GitHub Integration:** Creates migration branches, commits validated changes, and generates Pull Requests for developer review.
- **Bounded Agent Execution:** Enforces a tool-calling turn limit to prevent uncontrolled agent loops.
- **Flexible Contract Ingestion:** Accepts Source and Target OpenAPI contracts through hosted URLs or uploaded JSON/YAML files.
- **Asynchronous Execution:** Exposes a FastAPI endpoint for submitting migration jobs and reports completion results through a webhook.

## 🏗️ Architecture

ACME uses three LangGraph layers to coordinate deterministic processing and LLM-driven engineering tasks.

```text
                  Source OpenAPI
                  Target OpenAPI
                  Consumer Repo
                         |
                         v
              +----------------------+
              |    Planning Graph    |
              |                      |
              | Contract Resolution  |
              | oasdiff Analysis     |
              | Context Construction |
              | LLM Migration Plan   |
              +----------+-----------+
                         |
                         v
              +----------------------+
              |   Orchestrator Graph |
              |                      |
              | Work Item Queue      |
              | Migration State      |
              | JIT Schema Lookup    |
              | Validation Routing   |
              +----------+-----------+
                         |
                         v
              +----------------------+
              |     Coder Graph      |
              |                      |
              | LLM <-> Repository   |
              |        Tools         |
              +----------+-----------+
                         |
                         v
              +----------------------+
              |    Docker Sandbox    |
              |                      |
              | Java Code Changes    |
              | Maven Build & Tests  |
              | Contract Validation |
              +----------+-----------+
                         |
                  Validation Pass
                         |
                         v
              +----------------------+
              |     GitHub PR        |
              |                      |
              | Branch + Commit      |
              | Human Review         |
              +----------------------+
```

### 1. Planning Graph

Resolves Source and Target contracts into a common in-memory representation, executes `oasdiff`, constructs migration context, and asks the Planner LLM to generate a structured migration plan.

### 2. Orchestrator Graph

Manages the migration lifecycle, processes work items, coordinates the Docker sandbox, performs just-in-time Target schema lookup, and routes execution through validation and repair stages.

### 3. Coder Graph

Uses a tool-calling ReAct agent to inspect and modify the actual consumer repository. It can search for symbols, read source files, apply targeted patches, and create Java files through controlled tools.

The graph then coordinates Maven validation and contract checks, feeding actionable failures back into the repair workflow.

## 🔄 End-to-End Migration Workflow

1. **Ingest contracts:** Load the Source and Target OpenAPI JSON/YAML documents.
2. **Analyze breaking changes:** Execute `oasdiff` and prepare structured migration context.
3. **Generate a migration plan:** The Planner LLM identifies logical work items and proposes Target operation mappings.
4. **Inspect and modify code:** The Coder Agent discovers affected Java components and applies targeted changes inside Docker.
5. **Validate and repair:** Run `mvn clean test` and static contract checks. Route failures back for bounded repair attempts.
6. **Create Pull Requests:** Commit validated changes to GitHub branches and generate PRs for developer review.

The objective is to automate the migration workflow while keeping deterministic validation and human approval at the appropriate boundaries.

## 💻 Tech Stack

| Component | Technology |
|---|---|
| Language | Python |
| API Framework | FastAPI, Uvicorn |
| Agent Orchestration | LangGraph |
| LLM Integration | LangChain, OpenAI API |
| LLM | GPT-5.6 Luna |
| API Contract Analysis | oasdiff |
| Schema Validation | Pydantic |
| Execution Isolation | Docker, Docker SDK for Python |
| Consumer Build & Tests | Maven, Java 21 |
| Version Control & Delivery | Git, GitHub Pull Requests |

## 🚧 Constraints & MVP Boundaries

To deliver a reliable, deterministic agentic workflow without premature enterprise over-engineering, this V1 MVP operates within defined boundaries:

- **Target Stack Specificity:** The Coder Agent is heavily optimized for Java 21, standard Maven build suites (`mvn clean test`), and Spring Cloud OpenFeign. Handling alternative HTTP abstractions (e.g., `WebClient`, `RestTemplate`) or different build systems (like Gradle) is outside the current scope.
- **Validation Depth:** Pipeline success is defined by compiling successfully via Maven and passing static path/method string validations. It relies on standard Spring Boot unit tests to catch deeper semantic mapping errors and does not currently utilize full Abstract Syntax Tree (AST) parsing.
- **Bounded Execution Limits:** A hard 30-turn limit per endpoint is enforced on the LLM's tool-calling loop. If the agent cannot resolve compiler errors within this budget, the endpoint is marked as failed, safely skipped, and the job reports a `PARTIAL_FAILURE`.
- **Security Context:** While the Docker sandbox strictly isolates the execution environment, the worker currently assumes trusted downstream repositories and contracts.

## 🔌 API Usage

The worker exposes a `POST /migrations` endpoint that accepts `multipart/form-data` and returns `202 Accepted` when a migration is submitted for asynchronous execution.

### Request parameters

| Field | Description |
|---|---|
| `consumer_repo_url` | Git URL of the downstream Java consumer repository |
| `callback_url` | Webhook endpoint for migration completion |
| `source_url` or `source_file` | Source OpenAPI contract: URL or uploaded JSON/YAML file |
| `target_url` or `target_file` | Target OpenAPI contract: URL or uploaded JSON/YAML file |

### Example: Submit a migration using OpenAPI URLs

```bash
curl -X POST "http://127.0.0.1:8000/migrations" \
  -F "consumer_repo_url=https://github.com/yourusername/consumer-service.git" \
  -F "callback_url=http://localhost:8081/api/migrations/status" \
  -F "source_url=http://localhost:8080/v3/api-docs/v1" \
  -F "target_url=http://localhost:8080/v3/api-docs/v2"
```

### Example: Upload OpenAPI contracts

```bash
curl -X POST "http://127.0.0.1:8000/migrations" \
  -F "consumer_repo_url=https://github.com/yourusername/consumer-service.git" \
  -F "callback_url=http://localhost:8081/api/migrations/status" \
  -F "source_file=@openapi-v1.yaml" \
  -F "target_file=@openapi-v2.yaml"
```

The Source and Target inputs can be configured independently, allowing one contract to come from a URL and the other from an uploaded file.

### Webhook response example

The worker sends a JSON payload to the configured callback URL when the migration run finishes.

```json
{
  "task_id": "mig_69c2b81e",
  "status": "COMPLETED",
  "execution_time_minutes": 7.15,
  "generated_prs": [
    "https://github.com/yourusername/consumer-service/pull/35"
  ],
  "completed_endpoints": [
    "getAddress",
    "getData"
  ],
  "failed_endpoints": [],
  "error_message": null
}
```

## 🛠️ Local Setup

### Prerequisites

- Python 3.11+
- Docker Engine or Docker Desktop
- Maven and Java 21 support in the sandbox image
- `oasdiff` installed and available on `PATH`
- OpenAI API key
- GitHub Personal Access Token with the permissions required to clone the consumer repository and push branches or create Pull Requests

### 1. Clone the repository

```bash
git clone https://github.com/yourusername/acme-migration-worker.git
cd acme-migration-worker
```

### 2. Create and activate a virtual environment

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### 3. Configure environment variables

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key
OPENAI_MODEL=gpt-5.6-luna
GITHUB_PAT=your_github_personal_access_token
```

Keep credentials private. Never commit `.env` files or expose tokens to the LLM.

### 4. Start the worker

```bash
uvicorn api.main:app --reload
```

## 🎯 Project Highlights

ACME demonstrates the practical application of agentic AI to software engineering beyond code completion.

- **Autonomous execution:** The LLM interacts with a real repository through controlled tools instead of merely suggesting code changes.
- **Deterministic quality gates:** Maven and static contract checks validate generated changes.
- **Explicit workflow orchestration:** LangGraph coordinates planning, work-item processing, validation, and repair.
- **Isolated execution:** Docker provides a disposable workspace for code modification and compilation.
- **Human-in-the-loop delivery:** The system produces Pull Requests rather than automatically merging changes into the main branch.

**API Contract Migration Engine (ACME)** brings together contract-driven development, agentic coding, automated validation, and GitHub-based delivery into a single migration workflow.
