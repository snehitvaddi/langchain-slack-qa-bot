"""Stress test: Push conversation length until the agent breaks.

Tests with 30, 50, and 75+ messages to find the breaking point
for each memory strategy.

Usage: python -m eval.stress_test
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.agent import create_qa_agent

# 40 conversation messages — covers many customers and topics
# Each is a realistic follow-up building on prior context
STRESS_MESSAGES = [
    # --- Batch 1: BlueHarbor deep dive (1-7) ---
    "Tell me everything about BlueHarbor Logistics.",
    "What specific issue are they facing with search relevance?",
    "When did the taxonomy rollout happen that caused this?",
    "What's the proof-of-fix plan? Give me full details.",
    "Who is the competitor risk — NoiseGuard?",
    "What's the contract value and deployment model?",
    "What does the support ticket say about this issue?",

    # --- Batch 2: MapleBridge deep dive (8-14) ---
    "Now switch to MapleBridge Insurance. What's happening there?",
    "What approval bypass issues are they having?",
    "Is this pattern unique to MapleBridge or is it a Canada-wide problem?",
    "Which other Canadian customers have similar issues?",
    "What's the root cause — stale caches, field aliases, or what?",
    "What internal Slack thread exists about the MapleBridge fix?",
    "What's MapleBridge's contract value?",

    # --- Batch 3: Verdant Bay deep dive (15-20) ---
    "Tell me about City of Verdant Bay.",
    "What's the emergency playbook for their approval issue?",
    "What's the approved live patch window?",
    "How do we roll back if validation checks fail?",
    "What competitor is being considered as alternative?",
    "What's their account health and CRM stage?",

    # --- Batch 4: More customers (21-27) ---
    "Tell me about Aureum and the SCIM field conflicts.",
    "What fast fix did Jin propose?",
    "Now tell me about MapleHarvest Grocers in Quebec.",
    "What temporary field mappings are planned?",
    "What is the March 23 workshop supposed to produce?",
    "How many at-risk customers do we have in total?",
    "Which region has the most at-risk accounts?",

    # --- Batch 5: Cross-cutting questions requiring full memory (28-35) ---
    "Going back to the VERY FIRST customer we discussed — what was their name and contract value?",
    "What was the specific search relevance issue they had?",
    "Now the SECOND customer we discussed — the insurance company. What was their approval bypass root cause?",
    "Compare BlueHarbor and MapleBridge — which situation is more urgent and why?",
    "Of all the competitors mentioned in this conversation, which one is the biggest threat overall?",
    "What were the three different playbooks or fix plans we discussed across all customers?",
    "How many Canadian customers with approval issues did we identify earlier?",
    "Summarize the top 3 most critical customer situations from everything we've discussed.",

    # --- Batch 6: Even more follow-ups (36-40) ---
    "What about NordChemica — are they at risk too?",
    "Tell me about Pioneer Freight Solutions.",
    "Going way back — what was the Verdant Bay rollback command specifically?",
    "And the BlueHarbor A/B test — what was the success criteria?",
    "Give me a final executive summary of every customer we discussed, their issue, and the status.",
]

# Back-reference checks — which messages require remembering earlier context
STRESS_CHECKS = [
    {"msg_index": 27, "expected": ["BlueHarbor", "780"], "tests": "Back-ref to msg 1 (28 msgs ago)"},
    {"msg_index": 28, "expected": ["taxonomy", "search", "relevance"], "tests": "Back-ref to msg 2 details"},
    {"msg_index": 29, "expected": ["MapleBridge", "approval"], "tests": "Back-ref to msg 8 (22 msgs ago)"},
    {"msg_index": 30, "expected": ["BlueHarbor", "MapleBridge"], "tests": "Cross-ref two topics from msgs 1-14"},
    {"msg_index": 31, "expected": ["NoiseGuard"], "tests": "Recall competitor from msg 5"},
    {"msg_index": 33, "expected": ["Canada", "approval"], "tests": "Recall Canada pattern from msgs 10-11"},
    {"msg_index": 34, "expected": ["BlueHarbor", "MapleBridge", "Verdant Bay"], "tests": "Recall 3+ customers"},
    {"msg_index": 37, "expected": ["orchestrator rollback", "ruleset"], "tests": "Recall Verdant Bay rollback from msg 18"},
    {"msg_index": 38, "expected": ["80 percent", "BlueHarbor"], "tests": "Recall BlueHarbor A/B from msg 4"},
    {"msg_index": 39, "expected": ["BlueHarbor", "MapleBridge", "Verdant Bay", "Aureum"], "tests": "Recall ALL customers"},
]


def run_stress_test(strategy: str, max_messages: int | None = None):
    """Run stress test with a given memory strategy."""
    messages = STRESS_MESSAGES[:max_messages] if max_messages else STRESS_MESSAGES
    checks = [c for c in STRESS_CHECKS if c["msg_index"] < len(messages)]

    print(f"\n{'='*70}")
    print(f"STRESS TEST: strategy={strategy}, messages={len(messages)}")
    print(f"{'='*70}")

    agent = create_qa_agent(memory_strategy=strategy)
    thread_id = f"stress-{strategy}-{len(messages)}"
    total_tokens = 0
    total_time = 0
    check_results = []
    errors = []

    for i, msg_text in enumerate(messages):
        print(f"  [{i+1}/{len(messages)}] {msg_text[:60]}...", end=" ", flush=True)
        start = time.time()

        config = {"configurable": {"thread_id": thread_id}}
        try:
            result = agent.invoke(
                {"messages": [{"role": "user", "content": msg_text}]},
                config=config,
            )
            elapsed = time.time() - start
            total_time += elapsed

            # Extract answer and estimate tokens
            msgs = result.get("messages", [])
            answer = ""
            msg_tokens = 0
            for m in msgs:
                if hasattr(m, "content") and m.content:
                    msg_tokens += len(m.content) // 4
                if hasattr(m, "type") and m.type == "ai" and m.content and not getattr(m, "tool_calls", None):
                    answer = m.content
            total_tokens += msg_tokens

            # Check if this is a scored message
            check = next((c for c in checks if c["msg_index"] == i), None)
            if check:
                answer_lower = answer.lower()
                found = [kw for kw in check["expected"] if kw.lower() in answer_lower]
                missing = [kw for kw in check["expected"] if kw.lower() not in answer_lower]
                score = len(found) / len(check["expected"])
                status = "PASS" if score >= 0.5 else "FAIL"
                print(f"{elapsed:.1f}s | CHECK {status}: {check['tests']} ({score:.0%})")
                check_results.append({
                    "msg_index": i,
                    "tests": check["tests"],
                    "score": score,
                    "found": found,
                    "missing": missing,
                })
            else:
                print(f"{elapsed:.1f}s | tokens_so_far={total_tokens:,}")

        except Exception as e:
            elapsed = time.time() - start
            total_time += elapsed
            error_name = type(e).__name__
            error_msg = str(e)[:200]
            print(f"ERROR: {error_name}: {error_msg}")
            errors.append({"msg_index": i, "error": f"{error_name}: {error_msg}"})

    # Summary
    print(f"\n{'='*70}")
    print(f"STRESS TEST RESULTS: {strategy}")
    print(f"{'='*70}")
    print(f"  Messages sent: {len(messages)}")
    print(f"  Total est tokens: {total_tokens:,}")
    print(f"  Total time: {total_time:.1f}s")
    print(f"  Avg time per message: {total_time/len(messages):.1f}s")
    print(f"  Errors: {len(errors)}")

    if check_results:
        avg_score = sum(r["score"] for r in check_results) / len(check_results)
        passed = sum(1 for r in check_results if r["score"] >= 0.5)
        print(f"  Back-reference checks: {passed}/{len(check_results)} passed ({avg_score:.0%} avg)")
        for r in check_results:
            status = "PASS" if r["score"] >= 0.5 else "FAIL"
            print(f"    [{status}] msg {r['msg_index']}: {r['tests']} ({r['score']:.0%})")
            if r["missing"]:
                print(f"           Missing: {r['missing']}")

    if errors:
        print(f"\n  ERRORS:")
        for e in errors:
            print(f"    msg {e['msg_index']}: {e['error']}")

    return {
        "strategy": strategy,
        "messages_sent": len(messages),
        "total_tokens": total_tokens,
        "total_time": round(total_time, 1),
        "errors": errors,
        "check_results": check_results,
    }


def main():
    print("STRESS TEST: Finding the breaking point for each memory strategy")
    print("This will send 40 messages per strategy — may take 10-15 min per strategy\n")

    results = {}

    # Run all 3 strategies with the full 40 messages
    for strategy in ["summarize", "trim", "full"]:
        results[strategy] = run_stress_test(strategy)

    # Final comparison
    print(f"\n{'='*70}")
    print("FINAL COMPARISON")
    print(f"{'='*70}")
    print(f"{'Strategy':<12} {'Tokens':>10} {'Time':>8} {'Errors':>8} {'Back-Ref Accuracy':>20}")
    print("-" * 62)
    for strategy, data in results.items():
        checks = data["check_results"]
        avg = sum(r["score"] for r in checks) / len(checks) if checks else 0
        print(f"{strategy:<12} {data['total_tokens']:>10,} {data['total_time']:>7.0f}s {len(data['errors']):>8} {avg:>19.0%}")


if __name__ == "__main__":
    main()
