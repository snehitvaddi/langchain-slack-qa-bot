"""Automated experiment runner for the Q&A agent.

Runs 4 experiments, tracks metrics, and generates EXPERIMENTS.md report.

Usage: python -m eval.experiments
"""

import json
import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent import create_qa_agent
from eval.scenarios import (
    BASELINE_QUERIES,
    MULTI_TURN_SCRIPT,
    LONG_CONVERSATION_SCRIPT,
    LONG_CONVERSATION_CHECKS,
)


def extract_metrics(result: dict) -> dict:
    """Extract metrics from an agent invocation result."""
    messages = result.get("messages", [])
    tool_calls = 0
    tool_names = []
    answer = ""

    for msg in messages:
        if not hasattr(msg, "type"):
            continue
        if msg.type == "ai" and getattr(msg, "tool_calls", None):
            for tc in msg.tool_calls:
                tool_calls += 1
                tool_names.append(tc["name"])
        if msg.type == "ai" and msg.content and not getattr(msg, "tool_calls", None):
            answer = msg.content

    # Estimate tokens from all messages
    total_chars = sum(
        len(msg.content) if hasattr(msg, "content") and msg.content else 0
        for msg in messages
    )
    est_tokens = total_chars // 4

    return {
        "answer": answer,
        "tool_calls": tool_calls,
        "tool_names": tool_names,
        "total_messages": len(messages),
        "est_tokens": est_tokens,
    }


def score_accuracy(answer: str, expected_keywords: list[str]) -> dict:
    """Score answer accuracy against expected keywords."""
    answer_lower = answer.lower()
    found = [kw for kw in expected_keywords if kw.lower() in answer_lower]
    missing = [kw for kw in expected_keywords if kw.lower() not in answer_lower]
    score = len(found) / len(expected_keywords) if expected_keywords else 0
    return {"score": score, "found": found, "missing": missing}


# =============================================================================
# Experiment 1: Baseline Accuracy
# =============================================================================

def run_experiment_1():
    """Baseline accuracy — 6 example queries as independent single-turn questions."""
    print("\n" + "=" * 70)
    print("EXPERIMENT 1: Baseline Accuracy (6 Example Queries)")
    print("=" * 70)

    agent = create_qa_agent(memory_strategy="summarize")
    results = []

    for i, case in enumerate(BASELINE_QUERIES):
        print(f"\n  [{case['id']}] {case['query'][:70]}...")
        start = time.time()

        config = {"configurable": {"thread_id": f"exp1-{case['id']}"}}
        result = agent.invoke(
            {"messages": [{"role": "user", "content": case["query"]}]},
            config=config,
        )

        elapsed = time.time() - start
        metrics = extract_metrics(result)
        accuracy = score_accuracy(metrics["answer"], case["expected_keywords"])

        entry = {
            "id": case["id"],
            "difficulty": case["difficulty"],
            "latency_s": round(elapsed, 1),
            **metrics,
            **accuracy,
        }
        results.append(entry)

        status = "PASS" if accuracy["score"] >= 0.6 else "FAIL"
        print(f"    {status} | score={accuracy['score']:.0%} | tools={metrics['tool_calls']} ({' -> '.join(metrics['tool_names'])}) | {elapsed:.1f}s")
        if accuracy["missing"]:
            print(f"    Missing: {accuracy['missing']}")

    return results


# =============================================================================
# Experiment 2: Multi-Turn Context Retention
# =============================================================================

def run_experiment_2():
    """Multi-turn — 6 messages in one thread testing pronoun resolution."""
    print("\n" + "=" * 70)
    print("EXPERIMENT 2: Multi-Turn Context Retention")
    print("=" * 70)

    agent = create_qa_agent(memory_strategy="summarize")
    thread_id = "exp2-multi-turn"
    results = []

    for step in MULTI_TURN_SCRIPT:
        print(f"\n  [{step['id']}] {step['message'][:70]}...")
        print(f"    Testing: {step['tests']}")
        start = time.time()

        config = {"configurable": {"thread_id": thread_id}}
        result = agent.invoke(
            {"messages": [{"role": "user", "content": step["message"]}]},
            config=config,
        )

        elapsed = time.time() - start
        metrics = extract_metrics(result)
        accuracy = score_accuracy(metrics["answer"], step["expected_keywords"])

        entry = {
            "id": step["id"],
            "tests": step["tests"],
            "latency_s": round(elapsed, 1),
            **metrics,
            **accuracy,
        }
        results.append(entry)

        status = "PASS" if accuracy["score"] >= 0.5 else "FAIL"
        print(f"    {status} | score={accuracy['score']:.0%} | tools={metrics['tool_calls']} | {elapsed:.1f}s")

    return results


# =============================================================================
# Experiment 3: Memory Strategy Comparison
# =============================================================================

def run_experiment_3():
    """Compare memory strategies on a long conversation."""
    print("\n" + "=" * 70)
    print("EXPERIMENT 3: Memory Strategy Comparison (Long Conversation)")
    print("=" * 70)

    strategies = ["full", "trim", "summarize"]
    all_results = {}

    for strategy in strategies:
        print(f"\n  --- Strategy: {strategy.upper()} ---")
        agent = create_qa_agent(memory_strategy=strategy)
        thread_id = f"exp3-{strategy}"
        strategy_results = []
        total_tokens = 0

        for i, msg_text in enumerate(LONG_CONVERSATION_SCRIPT):
            print(f"    Msg {i + 1}/{len(LONG_CONVERSATION_SCRIPT)}: {msg_text[:60]}...")
            start = time.time()

            config = {"configurable": {"thread_id": thread_id}}
            try:
                result = agent.invoke(
                    {"messages": [{"role": "user", "content": msg_text}]},
                    config=config,
                )
                elapsed = time.time() - start
                metrics = extract_metrics(result)
                total_tokens += metrics["est_tokens"]

                # Check if this is a back-reference message we need to score
                check = next(
                    (c for c in LONG_CONVERSATION_CHECKS if c["msg_index"] == i),
                    None,
                )
                if check:
                    accuracy = score_accuracy(metrics["answer"], check["expected"])
                    status = "PASS" if accuracy["score"] >= 0.5 else "FAIL"
                    print(f"      CHECK: {status} | {check['tests']} | score={accuracy['score']:.0%}")
                    strategy_results.append({
                        "msg_index": i,
                        "tests": check["tests"],
                        "latency_s": round(elapsed, 1),
                        "tool_calls": metrics["tool_calls"],
                        **accuracy,
                    })
                else:
                    strategy_results.append({
                        "msg_index": i,
                        "latency_s": round(elapsed, 1),
                        "tool_calls": metrics["tool_calls"],
                    })

            except Exception as e:
                print(f"      ERROR: {type(e).__name__}: {e}")
                strategy_results.append({"msg_index": i, "error": str(e)})

        all_results[strategy] = {
            "results": strategy_results,
            "total_est_tokens": total_tokens,
        }
        print(f"    Total est tokens for {strategy}: {total_tokens:,}")

    return all_results


# =============================================================================
# Experiment 4: Tool Efficiency (derived from Experiment 1 data)
# =============================================================================

def analyze_tool_efficiency(exp1_results: list) -> list:
    """Analyze tool calling patterns from experiment 1."""
    print("\n" + "=" * 70)
    print("EXPERIMENT 4: Tool Efficiency Analysis")
    print("=" * 70)

    analysis = []
    for r in exp1_results:
        tool_path = " -> ".join(r["tool_names"])
        uses_fts = "fts_search" in r["tool_names"]
        uses_list = "list_tables" in r["tool_names"]

        entry = {
            "id": r["id"],
            "tool_calls": r["tool_calls"],
            "tool_path": tool_path,
            "uses_fts": uses_fts,
            "uses_list_tables": uses_list,
            "efficient": r["tool_calls"] <= 5,
        }
        analysis.append(entry)

        status = "GOOD" if entry["efficient"] else "HIGH"
        print(f"  [{r['id']}] {r['tool_calls']} calls [{status}]: {tool_path}")

    avg_calls = sum(a["tool_calls"] for a in analysis) / len(analysis)
    print(f"\n  Average tool calls: {avg_calls:.1f}")
    return analysis


# =============================================================================
# Report Generator
# =============================================================================

def generate_report(exp1, exp2, exp3, exp4) -> str:
    """Generate EXPERIMENTS.md markdown report."""
    lines = ["# Experiment Results\n"]

    # --- Experiment 1 ---
    lines.append("## Experiment 1: Baseline Accuracy\n")
    lines.append("Each of the 6 assessment example queries run as independent single-turn questions.\n")
    lines.append("| Query | Difficulty | Score | Tool Calls | Latency | Tools Used |")
    lines.append("|-------|-----------|-------|------------|---------|------------|")
    for r in exp1:
        tools = " -> ".join(r["tool_names"])
        lines.append(f"| {r['id']} | {r['difficulty']} | {r['score']:.0%} | {r['tool_calls']} | {r['latency_s']}s | {tools} |")

    avg_score = sum(r["score"] for r in exp1) / len(exp1)
    avg_tools = sum(r["tool_calls"] for r in exp1) / len(exp1)
    avg_latency = sum(r["latency_s"] for r in exp1) / len(exp1)
    lines.append(f"\n*Overall: {avg_score:.0%} accuracy, {avg_tools:.1f} avg tool calls, {avg_latency:.1f}s avg latency*\n")

    # --- Experiment 2 ---
    lines.append("## Experiment 2: Multi-Turn Context Retention\n")
    lines.append("6 messages in a single thread testing pronoun resolution and topic switching.\n")
    lines.append("| Step | Test | Score | Tool Calls | Latency |")
    lines.append("|------|------|-------|------------|---------|")
    for r in exp2:
        lines.append(f"| {r['id']} | {r['tests']} | {r['score']:.0%} | {r['tool_calls']} | {r['latency_s']}s |")

    mt_avg = sum(r["score"] for r in exp2) / len(exp2)
    lines.append(f"\n*Multi-turn accuracy: {mt_avg:.0%}*\n")

    # --- Experiment 3 ---
    lines.append("## Experiment 3: Memory Strategy Comparison\n")
    lines.append("17 messages in one thread, comparing three memory strategies on back-reference accuracy.\n")
    lines.append("| Strategy | Est Tokens | Back-Ref Accuracy | Errors |")
    lines.append("|----------|-----------|-------------------|--------|")
    for strategy, data in exp3.items():
        checks = [r for r in data["results"] if "score" in r]
        errors = [r for r in data["results"] if "error" in r]
        avg_acc = sum(r["score"] for r in checks) / len(checks) if checks else 0
        lines.append(
            f"| {strategy} | {data['total_est_tokens']:,} | {avg_acc:.0%} | {len(errors)} |"
        )
    lines.append("")

    # --- Experiment 4 ---
    lines.append("## Experiment 4: Tool Efficiency\n")
    lines.append("Analysis of tool-calling patterns per query.\n")
    lines.append("| Query | Tool Calls | Efficient? | Path |")
    lines.append("|-------|-----------|------------|------|")
    for r in exp4:
        eff = "Yes" if r["efficient"] else "No"
        lines.append(f"| {r['id']} | {r['tool_calls']} | {eff} | {r['tool_path']} |")

    avg_calls = sum(r["tool_calls"] for r in exp4) / len(exp4)
    fts_pct = sum(1 for r in exp4 if r["uses_fts"]) / len(exp4)
    lines.append(f"\n*Average: {avg_calls:.1f} tool calls, {fts_pct:.0%} of queries used FTS search*\n")

    # --- Key Findings ---
    lines.append("## Key Findings\n")
    lines.append("*(To be filled in after reviewing results)*\n")

    return "\n".join(lines)


# =============================================================================
# Main
# =============================================================================

def main():
    print("Starting experiments...\n")
    print("All traces will appear in LangSmith under project 'slack-qa-bot'")
    print("View at: https://smith.langchain.com\n")

    # Run experiments
    exp1 = run_experiment_1()
    exp2 = run_experiment_2()
    exp3 = run_experiment_3()
    exp4 = analyze_tool_efficiency(exp1)

    # Generate report
    report = generate_report(exp1, exp2, exp3, exp4)
    report_path = Path(__file__).parent / "EXPERIMENTS.md"
    report_path.write_text(report)
    print(f"\nReport written to: {report_path}")

    # Also save raw JSON for reference
    raw = {
        "experiment_1_baseline": [{k: v for k, v in r.items() if k != "answer"} for r in exp1],
        "experiment_2_multi_turn": [{k: v for k, v in r.items() if k != "answer"} for r in exp2],
        "experiment_3_memory": {
            s: {"total_est_tokens": d["total_est_tokens"], "checks": [r for r in d["results"] if "score" in r]}
            for s, d in exp3.items()
        },
        "experiment_4_efficiency": exp4,
    }
    json_path = Path(__file__).parent / "results.json"
    json_path.write_text(json.dumps(raw, indent=2))
    print(f"Raw JSON saved to: {json_path}")


if __name__ == "__main__":
    main()
