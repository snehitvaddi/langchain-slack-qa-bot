"""Evaluation script for the Q&A agent against example queries.

Run standalone: python -m eval.evaluate
Requires: OPENAI_API_KEY set in environment (and optionally LangSmith keys).
"""

import os
import sys

from dotenv import load_dotenv

load_dotenv()

# Add project root to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.agent import create_qa_agent

# Example queries from the take-home assessment with key facts to check
EVAL_CASES = [
    {
        "query": "which customer's issue started after the 2026-02-20 taxonomy rollout, and what proof plan did we propose to get them comfortable with renewal?",
        "expected_keywords": ["BlueHarbor", "7-10 business day", "proof-of-fix", "A/B test", "80 percent"],
    },
    {
        "query": "for Verdant Bay, what's the approved live patch window, and exactly how do we roll back if the validation checks fail?",
        "expected_keywords": ["2026-03-24", "02:00", "04:00", "orchestrator rollback", "ruleset"],
    },
    {
        "query": "in the MapleHarvest Quebec pilot, what temporary field mappings are we planning in the router transform, and what is the March 23 workshop supposed to produce?",
        "expected_keywords": ["txn_id", "transaction_id", "total_amount", "amount_cents", "schema document", "SI-SCHEMA-REG"],
    },
    {
        "query": "what SCIM fields were conflicting at Aureum, and what fast fix did Jin propose so we don't have to wait on Okta change control?",
        "expected_keywords": ["department", "businessUnit", "hot-reloadable", "preprocessing rule", "SCIM tracing"],
    },
    {
        "query": "which customer looks most likely to defect to a cheaper tactical competitor if we miss the next promised milestone, and what exactly is that milestone?",
        "expected_keywords": ["BlueHarbor", "NoiseGuard", "proof-of-fix", "2026-03-19", "2026-03-22"],
    },
    {
        "query": "do we have a recurring Canada approval-bypass pattern across accounts, or is MapleBridge basically a one-off? Give me the customer names and the shared failure pattern in plain English.",
        "expected_keywords": ["MapleBridge", "Verdant Bay", "recurring", "approval"],
    },
]


def run_evaluation():
    agent = create_qa_agent()
    results = []

    for i, case in enumerate(EVAL_CASES):
        print(f"\n{'='*60}")
        print(f"Query {i+1}: {case['query'][:80]}...")
        print(f"{'='*60}")

        config = {"configurable": {"thread_id": f"eval-{i}"}}
        result = agent.invoke(
            {"messages": [{"role": "user", "content": case["query"]}]},
            config=config,
        )

        # Extract answer
        messages = result.get("messages", [])
        answer = ""
        tool_calls_count = 0
        for msg in messages:
            if hasattr(msg, "type"):
                if msg.type == "ai" and msg.tool_calls:
                    tool_calls_count += len(msg.tool_calls)
                if msg.type == "ai" and msg.content and not msg.tool_calls:
                    answer = msg.content

        # Check for expected keywords
        answer_lower = answer.lower()
        found = [kw for kw in case["expected_keywords"] if kw.lower() in answer_lower]
        missing = [kw for kw in case["expected_keywords"] if kw.lower() not in answer_lower]
        score = len(found) / len(case["expected_keywords"]) if case["expected_keywords"] else 0

        print(f"\nAnswer: {answer[:500]}...")
        print(f"\nTool calls: {tool_calls_count}")
        print(f"Keywords found: {found}")
        print(f"Keywords missing: {missing}")
        print(f"Score: {score:.0%}")

        results.append({
            "query_num": i + 1,
            "tool_calls": tool_calls_count,
            "score": score,
            "found": found,
            "missing": missing,
        })

    # Summary
    print(f"\n{'='*60}")
    print("EVALUATION SUMMARY")
    print(f"{'='*60}")
    avg_score = sum(r["score"] for r in results) / len(results)
    avg_tools = sum(r["tool_calls"] for r in results) / len(results)
    print(f"Average keyword match: {avg_score:.0%}")
    print(f"Average tool calls: {avg_tools:.1f}")
    for r in results:
        status = "PASS" if r["score"] >= 0.6 else "FAIL"
        print(f"  Query {r['query_num']}: {r['score']:.0%} ({r['tool_calls']} tools) [{status}]")


if __name__ == "__main__":
    run_evaluation()
