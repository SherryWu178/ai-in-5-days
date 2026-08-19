# Singapore Corporate Canteen AI Specialist: Enhancement Roadmap & Specification (v1)

This document specifies the planned enhancements, architectural upgrades, and evaluation-driven features for **v1**, derived directly from the evaluation rubric in `evaluation_results.csv`.

---

## 🎯 v1 Goals & Score Targets

| Rubric Category | v0 Score | v1 Target | Key Enhancement |
| :--- | :---: | :---: | :--- |
| **Tool & Interface Design** | 15 / 20 | **20 / 20** | Structured guided error handling & self-correction instructions for LLM. |
| **Context & Memory** | 11 / 20 | **20 / 20** | Persistent Vector Store / SQLite adapter, background memory writes, context window compaction. |
| **Orchestration & Logic** | 15 / 20 | **20 / 20** | Dynamic task-based strategic model routing (`gemini-3.7-flash` vs `gemini-3.1-pro`). |
| **Observability & Tracing** | 0 / 20 | **20 / 20** | Cloud-native structured JSON logging, distributed tracing (`trace_span`), and PII scrubber. |
| **Infrastructure & CI/CD** | 10 / 20 | **20 / 20** | Terraform Infrastructure as Code (`deployment/terraform/`) and GitHub Actions CI workflow. |
| **Total Project Score** | **51 / 100** | **100 / 100** | **Production-grade, fully observable, enterprise-ready ADK agent.** |

---

## 🏛️ Planned v1 Feature Specifications

### 1. Observability, Distributed Tracing & PII Privacy (`app/observability/`)
- **Structured JSON Logging (`app/observability/structured_logger.py`):**
  - Custom `CloudStructuredJsonFormatter` emitting GCP Cloud Logging compatible JSON payloads.
  - Explicit tracking of **`intended_action`** versus **`outcome`** across all ADK node steps.
  - Automatic `trace_id` and `span_id` correlation with Google Cloud Trace (`logging.googleapis.com/trace`).
- **PII & Secrets Redaction Pipeline (`app/observability/pii_scrubber.py`):**
  - Regex and recursive dictionary scrubbing for corporate LDAP emails (`[REDACTED_EMAIL]`), Singapore/international phone numbers (`[REDACTED_PHONE]`), employee badge numbers (`[REDACTED_EMPLOYEE_ID]`), and API keys/tokens (`[REDACTED_SECRET]`).
- **Distributed Tracing Wrapper (`app/observability/tracing.py`):**
  - Lightweight OpenTelemetry / Cloud Trace span context manager (`trace_span`) recording sub-operation latencies in milliseconds.

### 2. Advanced Memory & Context Management (`app/memory/`)
- **Persistent Vector Store / SQLite DB Adapter (`app/memory/vector_store.py`):**
  - SQLite database adapter (`user_profiles.db`) storing user preferences, restrictions, and future embedding vectors alongside the JSON fallback.
- **Non-Blocking Background Memory Persistence:**
  - Decouples long-term memory updates from the critical response path via `asyncio.get_running_loop().run_in_executor(...)` in `preference_extraction_node`.
- **Dialogue History Compactor (`app/memory/compactor.py`):**
  - Compresses conversation histories (`compact_conversation_history`) to prevent context overflow while preserving Turn 0 profile greetings and clinical constraints.

### 3. Strategic Model Tier Routing (`app/utils/llm.py`)
- **Dynamic Task-Based Model Selection (`get_model_for_task`):**
  - **Fast Tier (`gemini-3.7-flash`):** Classification, greeting display, simple parameter extraction, and memory resolution.
  - **Reasoning Tier (`gemini-3.1-pro` / `gemini-1.5-pro`):** Deep multi-dish culinary pairings, clinical dietetics, and complex USDA macro optimization.

### 4. Guided Tool Error Handling & LLM Self-Correction (`app/tools/`)
- **Actionable Error Feedback (`filter_menu_items_with_guidance`, `query_usda_nutrition_with_guidance`):**
  - Instead of silent fallbacks when 0 menu items match or an unknown ingredient is queried, tools return a structured `GUIDED ERROR` payload containing available canteen names, station items, or valid USDA keys to instruct the LLM on how to self-correct its query.

### 5. Infrastructure as Code & Automated CI/CD
- **Terraform IaC (`deployment/terraform/`):**
  - `main.tf`, `variables.tf`, `cloud_run.tf`, `cloud_storage.tf`, `iam.tf`, `outputs.tf` for provisioning Cloud Run v2 services, GCS menu buckets, IAM roles, and Cloud Trace in `asia-southeast1`.
- **Automated CI/CD Pipeline (`.github/workflows/ci.yml`):**
  - GitHub Actions workflow running `uv run pytest -v tests/` across all unit, workflow, REST API, and ADK `EvalSet` tests on every pull request and push to `main`.
