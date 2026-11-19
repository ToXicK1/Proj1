# Milestone 9 live run

Date: 2026-11-18. Model: `qwen3-vl:4b-instruct` on a local Ollama server, through the OpenAI-compatible adapter.

Reproduce:

```powershell
$env:AIDLC_LIVE_OLLAMA_URL = "http://127.0.0.1:11434/v1"
$env:AIDLC_LIVE_OLLAMA_MODEL = "qwen3-vl:4b-instruct"
.venv\Scripts\python -m pytest -m live tests/test_live_ollama.py -k six_profiles
```

The test confirms a project brief, then goes through the portal API. Each profile produced a stored deliverable, an
independent reviewer read it, and a human approval moved the project on. Human approvals recorded: 6.

| Profile | Versions | Deliverable sections |
|---|---|---|
| business_analyst | 1 | assumptions, functional_requirements, non_functional_requirements, open_questions, summary |
| solution_architect | 1 | components, data_model, integrations, overview, risks |
| ui_ux_designer | 1 | accessibility_notes, design_rationale, navigation, screens, visual_style |
| software_developer | 1 | implementation_plan, key_decisions, known_limits, modules, summary |
| qa_security | 1 | open_risks, owner_test_steps, security_checks, summary, test_cases |
| devops_release | 1 | deployment_steps, environments, monitoring, rollback_plan, summary |

| Call | Result | Count | Total time |
|---|---|---|---|
| lead | succeeded | 6 | 197 s |
| reviewer | succeeded | 6 | 56 s |

What this proves: real model calls, stored output with the required sections, and a human decision at every step.
What it does not prove: the quality of the content. Nothing was built, tested or deployed by this run.
