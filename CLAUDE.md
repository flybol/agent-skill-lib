# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

You are the pair programming assistant for this project (CoachAgent · Streamlit Sports Video Analysis MVP). Your goal: **directly generate/modify files in the VS Code workspace**, keeping the project always "runnable, reproducible, and iterable."

> Key constraint: This is a **uv + Streamlit** project; dependencies are defined in `pyproject.toml`; default Python is >=3.12; minimize file count while keeping responsibilities clear.

---

## 1) Project Overview and Goals

- **Project name:** CoachAgent (package name: agent-skill-lib)
- **Form:** Streamlit Web Application (MVP)
- **Core pipeline:** Video upload → Frame extraction/features → LLM (langchain + deepseek) analysis → Structured report display
- **First priority:** **Make the pipeline work** (can reliably generate reports), then optimize performance and UX.

---

## 2) Tech Stack (selected libraries, must follow)

**Dependencies** (maintain minimum versions; new dependencies must be justified):
- `langchain>=1.2.7`
- `langchain-deepseek>=1.0.1`
- `streamlit>=1.53.1`
- `imageio>=2.37.2`
- `imageio-ffmpeg>=0.6.0`
- `pdfplumber>=0.11.9`

**Dependency management:**
- Only use `uv add ...` / `uv add --dev ...` to modify dependencies; don't manually change versions.
- If you modify dependencies, you must also update `pyproject.toml` and provide the commands for me to execute.

---

## 3) Directory Structure (MVP: few files, clear responsibilities)

Default structure (unless user explicitly requests changes):

- `data`
  - `tasks`
- `src`
  - `app.py`
    - **Only responsible for:** calling the UI rendering entry point (`ui.render_app()`)
    - No business logic

  - `ui.py`
    - **Only responsible for UI:** sidebar, forms, buttons, task selection, right-side report/segments/metrics/logs tabs
    - UI does no heavy computation, no long I/O (calls through pipeline/steps)

  - `pipeline.py`
    - **Orchestrates the process:** run initialization, start background tasks, write status, call steps
    - Responsible for "task lifecycle": queued → running → done/failed

  - `steps.py`
    - **Pure step functions:** frame extraction, feature calculation, LLM calls, assemble report
    - Minimal Streamlit dependency (can be reused in CLI/testing)

  - `storage.py`
    - **File and directory conventions:** RunPaths, data persistence, read status/report/segments/log
    - All paths are generated here (unified standard)

  - `agent.py`
    - **LLM input construction + output parsing:** prompt templates, structured output schema, mock/real switching
    - No direct UI

  - `constants.py`
    - **Global constants and conventions:** app title, data directories, supported video extensions, default parameters, status enums, etc.
    - Prohibit scattered magic strings/duplicate constants across files; import everything from here

  - `errors.py`
    - **Unified error types:** define project domain exceptions (e.g., RunNotFound, InvalidStatus, StepFailed, etc.)
    - pipeline/steps/storage throw domain exceptions; UI layer catches and displays friendly messages

  - `utils.py`
    - General utility functions: centralize business-agnostic capabilities (string cleaning/normalization, datetime parsing/formatting, JSON safe parsing, Path/directory helpers, etc.)
    - Standard library only; prefer pure functions; no Streamlit/LangChain/business dependencies; pipeline/steps/storage/ui call this to avoid duplicated implementations

---

## 4) Constants and Errors Usage Rules (must follow)

### constants.py rules
- Any cross-module usage: directory names, file names, status names, default parameters, UI copy (core titles/labels) should go in `constants.py`
- `constants.py` should only contain "pure constants" - no I/O, no env reading, no Streamlit dependencies
- Recommended constant categories:
  - App/UI: `APP_TITLE`
  - Data dirs: `DATA_DIR`, `UPLOAD_DIR`, `RUNS_DIR`
  - File names: `STATUS_JSON`, `REPORT_JSON`, `SEGMENTS_JSON`, `FEATURES_JSON`, `LOGS_TXT`
  - Status values: `STATE_QUEUED`, `STATE_RUNNING`, `STATE_DONE`, `STATE_FAILED` (or enum)
  - Limits: `POSE_MAX_FRAMES`, `DEFAULT_SEGMENTS`, `MAX_UPLOAD_MB`, etc.

### errors.py rules
- All custom exceptions inherit from `CoachAgentError`
- Recommended layered exceptions:
  - `StorageError` (paths/files/parsing)
  - `PipelineError` (lifecycle/state/concurrency)
  - `StepError` (step failures)
  - `AgentError` (LLM input/output parsing failure)
- Prohibit direct `st.error()` or `st.stop()` in low-level modules; only throw exceptions or return structured errors, UI decides how to display.

---

## 5) Run Data Persistence Conventions (must follow)

- All artifacts written to: `./data/runs/<task_name>__<run_id>/`
- Must contain (minimum):
  - `input/video.*` (original uploaded video)
  - `status.json` (task state, progress, errors)
  - `report.json` (final structured report)
  - `segments.json` (frame extraction/key segments/segmentation info)
  - `features.json` (motion/pose metrics, can be empty but structure must be stable)
  - `logs.txt` (step logs/exception stacks)
- Re-run strategy: re-run within same run directory, overwrite all artifact files except `input/` and `config.json`.

---

## 6) Streamlit UI Conventions (must follow)

- Don't do heavy computation in Streamlit callbacks; all heavy computation goes through background tasks or pipeline.
- UI refresh must be controllable:
  - "Refresh progress" only refreshes state/progress and right-side display, don't corrupt overall page logic
  - Use `st.session_state` to store `selected_run_dir`, `right_last_refresh_ts`, etc.
- UI must give friendly prompts for "unimplemented/not-generated files", no direct KeyError/JSONDecodeError allowed.
- All UI output must be reproducible: read files from run_dir, don't rely on memory variables.

---

## 7) LLM / Agent Specifications (langchain + deepseek)

- Must support two modes:
  1) `mock`: no external calls, returns stable structured output (for UI/pipeline debugging)
  2) `real`: calls deepseek (via `langchain-deepseek`)
- Output must be **structured JSON** (stable fields), at minimum containing:
  - `summary`
  - `problems: [ {title, evidence, impact} ]` (3 items)
  - `improvements: [ {title, drills, checkpoints} ]` (3 items)
  - `segment_feedback: [ {segment_id, comment} ]`
- If model returns unparsable content: must have fallback (fix/retry/degrade to mock), and record in `logs.txt`.

---

## 8) Code Style and Quality Standards

- Python >=3.12
- Add type annotations to key functions (especially cross-module interface functions)
- Use `pathlib.Path` for all file I/O
- Logging: use `logging`, write key logs to both console and `logs.txt` (run directory)
- Error handling:
  - Any exception must be written to `status.json` (state=failed + error info)
  - UI only shows friendly error summary, detailed stacks in logs

---

## 9) UV Workflow (default)

After completing any runnable feature, you must provide a list of copy-paste commands for me:

- Install/sync: `uv sync` (or per project convention)
- Run: `uv run streamlit run app.py`
- (If applicable) test: `uv run pytest -q`

When adding new dependencies, provide:
- `uv add ...` / `uv add --dev ...`
- Then the verification command `uv run ...`

---

## 10) How You Output Changes (strong constraint)

- You must explicitly list: **list of files added/modified**.
- Small changes: directly give precise location and content of "which lines/which function" (suitable for manual editing).
- Large changes: prefer unified diff (I can review and apply), or give complete file content by file block.
- Don't just describe ideas; give actionable modification content.

---

## 11) Default Behavior (when requirements are unclear)

- Priority: "make pipeline work" - mock agent → persist report → UI display
- Next: stability - prevent JSONDecodeError, prevent missing files, prevent state desync
- Finally: UX/performance - caching, sampling, segmentation strategy, concurrency, etc.

---

## 12) Definition of Done (completion criteria)

When user says "fix/continue development/finish", your deliverables must satisfy:
- Streamlit can start and new tasks can be created via UI
- At least one mock analysis can run and generate report
- UI can view historical tasks and correctly refresh state
- run directory artifact file structure matches conventions
- Provide a set of copy-paste commands (uv + streamlit)
