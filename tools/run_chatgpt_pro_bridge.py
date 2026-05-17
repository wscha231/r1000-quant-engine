#!/usr/bin/env python3
"""Build manual ChatGPT Pro review packets without using the OpenAI API.

This tool is an operator bridge:

1. Codex generates a copy/paste packet for ChatGPT Pro.
2. The human pastes it into ChatGPT Pro.
3. The human pastes the full Pro response back into Codex.
4. Codex verifies the response against repo artifacts before implementation.

No network calls are made.
"""
from __future__ import annotations

import argparse
import csv
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_OUTPUT_DIR = "outputs/chatgpt_pro_bridge"
DEFAULT_LATEST_RUN = "outputs"


BASELINES = {
    "main": {
        "id": "codex/broker-ledger-replay-foundation",
        "cagr": "21.84%",
        "max_dd": "-28.62%",
    },
    "main_control": {
        "id": "20260511_global_alpha_universe",
        "cagr": "21.09%",
        "max_dd": "-31.69%",
    },
    "concentrated": {
        "id": "20260514_global_alpha_universe",
        "cagr": "35.10%",
        "max_dd": "-22.68%",
    },
    "latest_regression": {
        "id": "latest 20260516",
        "main": "12.86% / -27.07%",
        "concentrated": "16.89% / -33.80%",
    },
}


COMMON_PRO_PROMPT = """You are an external strategy and risk reviewer for the r1000-quant-engine project.

Non-negotiable rules:
- Production performance is judged only by broker_ledger_next_close.
- If valid_for_production is not true, the result cannot be used for promotion.
- Legacy/proxy/backtest_metrics numbers are reference only.
- Forward-return leakage, PIT violations, and SEC features before accepted_at/available_from are forbidden.
- Production defaults cannot change before explicit human approval.
- Main and concentrated portfolios must be compared against their own baselines.
- Treat ChatGPT Pro advice as advisory only; Codex must verify every claim against repo artifacts.

Baselines:
- Main: codex/broker-ledger-replay-foundation, CAGR 21.84%, MaxDD -28.62%.
- Main current-branch control: 20260511_global_alpha_universe, CAGR 21.09%, MaxDD -31.69%.
- Concentrated: 20260514_global_alpha_universe, CAGR 35.10%, MaxDD -22.68%.
- latest 20260516 is a regression case, not a promotion baseline.

Required answer format:
1. Conclusion
2. Official-metric judgment
3. Risk/leakage concerns
4. Next Codex agent instructions
5. Promotion decision: yes/no
6. Human approval items
"""


@dataclass(frozen=True)
class AgentTemplate:
    name: str
    purpose: str
    question: str
    required_output: str


AGENTS: dict[str, AgentTemplate] = {
    "A0": AgentTemplate(
        name="Orchestrator",
        purpose="Judge the run and set the next agent priorities using official metrics only.",
        question=(
            "Decide whether this run improved or regressed versus the locked baselines. "
            "Separate Main and Concentrated. Give exactly three next agent priorities."
        ),
        required_output=(
            "Return a promotion/no-promotion decision, portfolio-specific baseline comparison, "
            "and the next three agent tasks."
        ),
    ),
    "A2": AgentTemplate(
        name="SEC Evidence",
        purpose="Review SEC EDGAR evidence expansion and PIT safety.",
        question=(
            "Rank the next SEC expansion among Form 4, 13D/G, 8-K, 13F, and Form 144. "
            "Find accepted_at/available_from leakage risks and propose shadow-only features."
        ),
        required_output=(
            "Return next SEC form priority, PIT schema risks, shadow feature list, and tests."
        ),
    ),
    "A3": AgentTemplate(
        name="Selection/Scoring",
        purpose="Design shadow scoring that reduces raw score dependence.",
        question=(
            "Propose a leader_onset_score v2 using future_winner, market_confirmation, "
            "and early_evidence. Do not change score_total or production target books."
        ),
        required_output=(
            "Return formula, validation plan, no-leakage checks, and rejected alternatives."
        ),
    ),
    "A4": AgentTemplate(
        name="Main PM",
        purpose="Design Main portfolio challengers against the Main official baseline.",
        question=(
            "Propose three Main challenger experiments to beat 21.84% CAGR / -28.62% MaxDD. "
            "Specify target_n, score_source, no-trade band, cash floor, and broker-ledger checks."
        ),
        required_output=(
            "Return exactly three experiment specs and the official pass/fail criteria."
        ),
    ),
    "A5": AgentTemplate(
        name="Concentrated PM",
        purpose="Design Concentrated portfolio challengers against the 20260514 baseline.",
        question=(
            "Design N2/N3/N5 experiments to beat 35.10% CAGR / -22.68% MaxDD. "
            "N7 cannot be selected as champion. Include caps, staged entry, and replacement swap conditions."
        ),
        required_output=(
            "Return N2/N3/N5 experiment matrix, champion criteria, and rejection gates."
        ),
    ),
    "A7": AgentTemplate(
        name="Diagnostics",
        purpose="Classify performance regression causes from run-to-run and hold-vs-replace evidence.",
        question=(
            "Classify regression causes from run diff, missed winners, and wrong substitutions. "
            "Identify where SEC evidence would have supported holding or replacing."
        ),
        required_output=(
            "Return root-cause buckets, top cases to inspect, and three testable hypotheses."
        ),
    ),
    "A10": AgentTemplate(
        name="AutoLearning/Test Engine",
        purpose="Mine prior experiments and test-data evidence into candidate specs.",
        question=(
            "Separate repeatedly successful and failed patterns from historical experiments and selection_quality. "
            "Suggest tests for whether SEC evidence appears before winner onset. Output only Codex-implementable specs."
        ),
        required_output=(
            "Return candidate_rule_ideas, false-positive checks, missed-winner rescue checks, and implementation-ready specs."
        ),
    ),
}


def repo_path(value: str | Path) -> Path:
    path = Path(value)
    return path if path.is_absolute() else REPO_ROOT / path


def safe_load_json(path: Path) -> Any:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"read_error": f"{type(exc).__name__}: {exc}"}


def safe_float(value: Any) -> float | None:
    try:
        out = float(value)
    except Exception:
        return None
    return out if math.isfinite(out) else None


def fmt_pct(value: Any) -> str:
    num = safe_float(value)
    if num is None:
        return "n/a"
    return f"{num:.2%}"


def compact_json(value: Any, *, max_chars: int = 4000) -> str:
    text = json.dumps(value, indent=2, sort_keys=True, default=str)
    if len(text) <= max_chars:
        return text
    return text[:max_chars] + "\n... <truncated>"


def read_text_snippet(path: Path, *, max_lines: int = 80) -> str:
    if not path.exists():
        return f"<missing: {path}>"
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except Exception as exc:
        return f"<read error: {type(exc).__name__}: {exc}>"
    if len(lines) > max_lines:
        return "\n".join(lines[:max_lines] + [f"... <truncated after {max_lines} lines>"])
    return "\n".join(lines)


def csv_top_rows(path: Path, *, topn: int = 10) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as handle:
            reader = csv.DictReader(handle)
            return [row for _, row in zip(range(topn), reader)]
    except Exception as exc:
        return [{"read_error": f"{type(exc).__name__}: {exc}", "path": str(path)}]


def metric_line(label: str, payload: Any) -> str:
    if not isinstance(payload, dict):
        return f"- {label}: missing"
    return (
        f"- {label}: status={payload.get('status', 'n/a')}, "
        f"metric_mode={payload.get('metric_mode', payload.get('official_metric_mode', 'n/a'))}, "
        f"valid_for_production={payload.get('valid_for_production', 'n/a')}, "
        f"CAGR={fmt_pct(payload.get('cagr', payload.get('strategy_cagr')))}, "
        f"MaxDD={fmt_pct(payload.get('max_dd', payload.get('max_drawdown')))}, "
        f"Sharpe={payload.get('sharpe', 'n/a')}, "
        f"trades={payload.get('trade_count', 'n/a')}, "
        f"avg_cash={fmt_pct(payload.get('avg_cash_weight', payload.get('avg_cash')))}"
    )


def latest_run_summary(latest_run: Path) -> str:
    files = {
        "account official": latest_run / "account_evaluation" / "official_metrics.json",
        "broker main": latest_run / "broker_replay" / "main" / "metrics.json",
        "broker concentrated": latest_run / "broker_replay" / "concentrated" / "metrics.json",
        "goal search": latest_run / "portfolio_goal_search" / "goal_search_summary.json",
        "selection quality": latest_run / "selection_quality" / "selection_quality_summary.json",
    }
    lines = [f"latest_run: {latest_run}"]
    for label, path in files.items():
        payload = safe_load_json(path)
        if label in {"broker main", "broker concentrated", "account official"}:
            lines.append(metric_line(label, payload))
        elif payload is None:
            lines.append(f"- {label}: missing ({path})")
        else:
            lines.append(f"- {label}: present ({path})")

    for rel in [
        "alpha_selector_broker_grid/main/summary.csv",
        "alpha_selector_broker_grid/concentrated/summary.csv",
        "selection_quality/factor_ic.csv",
    ]:
        rows = csv_top_rows(latest_run / rel, topn=10)
        if rows:
            lines.append("")
            lines.append(f"Top rows from {rel}:")
            lines.append(compact_json(rows, max_chars=3500))
    return "\n".join(lines)


def extra_inputs(paths: list[str], *, max_lines: int) -> str:
    blocks: list[str] = []
    for raw in paths:
        path = repo_path(raw)
        blocks.append(f"### Input file: {path}")
        suffix = path.suffix.lower().lstrip(".") or "text"
        blocks.append(f"```{suffix}")
        blocks.append(read_text_snippet(path, max_lines=max_lines))
        blocks.append("```")
    return "\n".join(blocks)


def render_question_packet(
    *,
    agent_key: str,
    latest_run: Path,
    run_url: str = "",
    purpose: str = "",
    extra_context: str = "",
    extra_input_paths: list[str] | None = None,
    question: str = "",
    required_output: str = "",
    language: str = "Korean",
    max_input_lines: int = 80,
) -> str:
    template = AGENTS[agent_key]
    purpose_text = purpose.strip() or template.purpose
    question_text = question.strip() or template.question
    required_text = required_output.strip() or template.required_output
    input_paths = extra_input_paths or []

    parts = [
        "[PRO_QUESTION]",
        "",
        "Common Reviewer Prompt:",
        COMMON_PRO_PROMPT.strip(),
        "",
        f"Agent:\n{agent_key} {template.name}",
        "",
        f"Purpose:\n{purpose_text}",
        "",
        "Context:",
        "- This is a manual ChatGPT Pro review packet. Do not call any API.",
        "- ChatGPT Pro output is advisory. Codex must verify it against repo artifacts.",
        f"- Preferred answer language: {language}.",
        f"- Run URL: {run_url or 'not provided'}",
        "",
        "Locked Baselines:",
        compact_json(BASELINES, max_chars=2000),
        "",
        "Latest Run Summary:",
        latest_run_summary(latest_run),
    ]
    if extra_context.strip():
        parts.extend(["", "Additional Context:", extra_context.strip()])
    if input_paths:
        parts.extend(["", "Inputs:", extra_inputs(input_paths, max_lines=max_input_lines)])
    else:
        parts.extend(["", "Inputs:", "No extra input files were attached. Use the latest run summary above."])
    parts.extend(
        [
            "",
            "Question:",
            question_text,
            "",
            "Required Output:",
            required_text,
            "",
            "Remember: promotion evidence must be official broker_ledger_next_close only.",
        ]
    )
    return "\n".join(parts) + "\n"


def render_response_template(agent_key: str) -> str:
    template = AGENTS[agent_key]
    return (
        "[PRO_RESPONSE]\n\n"
        f"Agent:\n{agent_key} {template.name}\n\n"
        "Source:\nChatGPT Pro manual review\n\n"
        "Response:\n"
        "<paste the full ChatGPT Pro answer here without summarizing>\n\n"
        "Codex task:\n"
        "Verify this response against repo artifacts and official broker-ledger metrics before applying it. "
        "Do not change production defaults. If implementation is needed, make a research-only PR first.\n"
    )


def write_packet(output_dir: Path, agent_key: str, question: str, response: str) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    q_path = output_dir / f"pro_question_{agent_key.lower()}.md"
    r_path = output_dir / f"pro_response_template_{agent_key.lower()}.md"
    q_path.write_text(question, encoding="utf-8")
    r_path.write_text(response, encoding="utf-8")
    return {"question": str(q_path), "response_template": str(r_path)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--agent", choices=[*AGENTS.keys(), "all"], default="A0")
    parser.add_argument("--latest-run", default=DEFAULT_LATEST_RUN)
    parser.add_argument("--run-url", default="")
    parser.add_argument("--purpose", default="")
    parser.add_argument("--context", default="")
    parser.add_argument("--question", default="")
    parser.add_argument("--required-output", default="")
    parser.add_argument("--input-file", action="append", default=[])
    parser.add_argument("--max-input-lines", type=int, default=80)
    parser.add_argument("--language", default="Korean")
    parser.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--stdout", action="store_true", help="Print generated question packet(s) to stdout.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    latest_run = repo_path(args.latest_run)
    output_dir = repo_path(args.output_dir)
    agent_keys = list(AGENTS) if args.agent == "all" else [args.agent]
    manifest: dict[str, Any] = {
        "status": "ok",
        "api_used": False,
        "latest_run": str(latest_run),
        "agents": {},
    }
    for key in agent_keys:
        question = render_question_packet(
            agent_key=key,
            latest_run=latest_run,
            run_url=args.run_url,
            purpose=args.purpose,
            extra_context=args.context,
            extra_input_paths=args.input_file,
            question=args.question,
            required_output=args.required_output,
            language=args.language,
            max_input_lines=int(args.max_input_lines),
        )
        response = render_response_template(key)
        paths = write_packet(output_dir, key, question, response)
        manifest["agents"][key] = paths
        if args.stdout:
            print(question)
    manifest_path = output_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
