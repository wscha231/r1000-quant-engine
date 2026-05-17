# Manual ChatGPT Pro Bridge

This project uses ChatGPT Pro as a manual external reviewer, not as an API dependency.

## Workflow

```text
Codex generates a Pro question packet.
The operator pastes it into ChatGPT Pro.
ChatGPT Pro answers in the required format.
The operator pastes the full response back into Codex.
Codex verifies the answer against repo artifacts and broker-ledger metrics.
```

ChatGPT Pro is advisory. Official performance is always computed by repo scripts using `broker_ledger_next_close`.

## Generate A Packet

```powershell
python tools/run_chatgpt_pro_bridge.py `
  --agent A0 `
  --latest-run outputs `
  --run-url https://github.com/wscha231/r1000-quant-engine/actions/runs/RUN_ID `
  --output-dir outputs/chatgpt_pro_bridge
```

Generated files:

```text
outputs/chatgpt_pro_bridge/pro_question_a0.md
outputs/chatgpt_pro_bridge/pro_response_template_a0.md
outputs/chatgpt_pro_bridge/manifest.json
```

Use `--agent all` to create packets for every manual-review agent.

## Agent Choices

```text
A0  Orchestrator
A2  SEC Evidence
A3  Selection/Scoring
A4  Main PM
A5  Concentrated PM
A7  Diagnostics
A10 AutoLearning/Test Engine
```

## Attach Extra Inputs

Use `--input-file` for reports or metric summaries that should be pasted into the packet.

```powershell
python tools/run_chatgpt_pro_bridge.py `
  --agent A7 `
  --latest-run outputs `
  --input-file outputs/selection_quality/selection_quality_summary.json `
  --input-file outputs/leader_drop_diagnostics/leader_drop_diagnostics_summary.json
```

The tool truncates long inputs so the packet stays pasteable.

## Paste Back To Codex

When ChatGPT Pro answers, paste it back to Codex using the generated response template:

```text
[PRO_RESPONSE]

Agent:
A0 Orchestrator

Source:
ChatGPT Pro manual review

Response:
<paste full ChatGPT Pro answer here>

Codex task:
Verify this response against repo artifacts and official broker-ledger metrics before applying it.
Do not change production defaults. If implementation is needed, make a research-only PR first.
```

Do not summarize the Pro answer before pasting it back. Codex should see the full response.

## Guardrails

- Do not use ChatGPT Pro output as official performance evidence.
- Do not promote a result unless `valid_for_production=true`.
- Do not treat legacy/proxy/backtest metrics as promotion evidence.
- Do not allow SEC features before `accepted_at` / `available_from`.
- Do not change production defaults without human approval.
- Keep Main and Concentrated comparisons separate.
