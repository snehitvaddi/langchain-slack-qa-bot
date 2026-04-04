"""End-to-end Slack integration test.

Sends real messages to the bot via Slack Web API, waits for responses,
and validates accuracy. This tests the FULL pipeline: Slack → Bolt → Agent → Tools → DB → Slack.

Prerequisites:
- Bot must be running: python -m src.main
- Bot must be added to the test channel
- .env must have SLACK_BOT_TOKEN set

Usage: python -m eval.slack_e2e_test
"""

import os
import sys
import time
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
sys.path.insert(0, str(Path(__file__).parent.parent))

from slack_sdk import WebClient

# Config
BOT_TOKEN = os.environ["SLACK_BOT_TOKEN"]
CHANNEL = os.environ.get("SLACK_TEST_CHANNEL", "")  # Set this or we'll find it
BOT_USER_ID = ""  # Will be auto-detected

client = WebClient(token=BOT_TOKEN)


def find_bot_user_id():
    """Find the bot's own user ID."""
    resp = client.auth_test()
    return resp["user_id"]


def find_test_channel():
    """Find a channel the bot is in."""
    resp = client.conversations_list(types="public_channel", limit=100)
    for ch in resp["channels"]:
        if ch.get("is_member"):
            return ch["id"]
    raise RuntimeError("Bot is not a member of any channel. Add it to a channel first.")


def send_message(channel: str, text: str, thread_ts: str = None) -> str:
    """Send a message as the bot and return the message timestamp."""
    # We send as user (not bot) to simulate a real user message
    # But since we only have bot token, we post and the bot will see it
    # For true user simulation, we use chat_postMessage which triggers the event
    resp = client.chat_postMessage(
        channel=channel,
        text=text,
        thread_ts=thread_ts,
    )
    return resp["ts"]


def wait_for_bot_reply(channel: str, thread_ts: str, after_ts: str, timeout: int = 60) -> dict | None:
    """Wait for the bot to reply in a thread after a given timestamp."""
    start = time.time()
    while time.time() - start < timeout:
        time.sleep(3)
        resp = client.conversations_replies(
            channel=channel,
            ts=thread_ts,
            limit=20,
        )
        messages = resp.get("messages", [])
        for msg in messages:
            # Look for bot messages after our timestamp
            if msg.get("bot_id") and float(msg["ts"]) > float(after_ts):
                # Skip "Thinking..." placeholders
                if msg.get("text", "").strip() in ("Thinking...", ""):
                    continue
                return msg
    return None


def score_response(response_text: str, expected_keywords: list[str]) -> dict:
    """Score a response against expected keywords."""
    text_lower = response_text.lower()
    found = [kw for kw in expected_keywords if kw.lower() in text_lower]
    missing = [kw for kw in expected_keywords if kw.lower() not in text_lower]
    score = len(found) / len(expected_keywords) if expected_keywords else 0
    return {"score": score, "found": found, "missing": missing}


# =============================================================================
# Test Scenarios
# =============================================================================

SINGLE_TURN_TESTS = [
    {
        "name": "Easy: Taxonomy rollout",
        "message": "which customer's issue started after the 2026-02-20 taxonomy rollout, and what proof plan did we propose to get them comfortable with renewal?",
        "expected": ["BlueHarbor", "proof-of-fix", "A/B test"],
    },
    {
        "name": "Easy: Verdant Bay rollback",
        "message": "for Verdant Bay, what's the approved live patch window, and exactly how do we roll back if the validation checks fail?",
        "expected": ["02:00", "04:00", "orchestrator rollback"],
    },
    {
        "name": "Hard: Competitor defection",
        "message": "which customer looks most likely to defect to a cheaper tactical competitor if we miss the next promised milestone?",
        "expected": ["BlueHarbor", "NoiseGuard"],
    },
]

MULTI_TURN_TEST = [
    {
        "message": "Tell me about BlueHarbor Logistics and their current issues.",
        "expected": ["BlueHarbor", "taxonomy"],
        "test": "Basic retrieval",
    },
    {
        "message": "What's their competitor risk? Could they leave us?",
        "expected": ["NoiseGuard"],
        "test": "Pronoun resolution — 'their' = BlueHarbor",
    },
    {
        "message": "What's the contract value?",
        "expected": ["780"],
        "test": "Continued context — still BlueHarbor",
    },
    {
        "message": "Now switch to Verdant Bay. What's going on with them?",
        "expected": ["Verdant Bay", "approval"],
        "test": "Topic switch",
    },
    {
        "message": "What's the rollback command if the fix fails?",
        "expected": ["orchestrator rollback"],
        "test": "Pronoun resolution after topic switch",
    },
    {
        "message": "Go back to BlueHarbor — what was the proof-of-fix timeline?",
        "expected": ["BlueHarbor", "7-10"],
        "test": "Back-reference to earlier topic",
    },
]

STRESS_TEST_MESSAGES = [
    "Tell me everything about BlueHarbor Logistics.",
    "What specific issue are they facing with search relevance?",
    "When did the taxonomy rollout happen?",
    "What's the proof-of-fix plan?",
    "Who is the competitor risk?",
    "What's the contract value?",
    "Now tell me about MapleBridge Insurance.",
    "What approval bypass issues are they having?",
    "Is this a Canada-wide pattern?",
    "Tell me about Verdant Bay.",
    "What's the emergency playbook?",
    "What's the live patch window?",
    "Tell me about Aureum and SCIM.",
    "What did Jin propose as a fix?",
    "How many at-risk customers total?",
    # Back-references after 15 messages
    "Going back to the very first customer — what was their contract value?",
    "What was the Canada approval bypass root cause?",
    "Compare BlueHarbor and Verdant Bay — which is more urgent?",
    "Summarize everything we discussed.",
]

STRESS_CHECKS = {
    15: {"expected": ["BlueHarbor", "780"], "test": "Back-ref to msg 1"},
    16: {"expected": ["MapleBridge", "approval"], "test": "Back-ref to msg 7"},
    17: {"expected": ["BlueHarbor", "Verdant Bay"], "test": "Cross-reference"},
    18: {"expected": ["BlueHarbor", "MapleBridge", "Verdant Bay"], "test": "Full recall"},
}


def run_single_turn_tests(channel: str):
    """Run independent single-turn tests in separate threads."""
    print("\n" + "=" * 60)
    print("SINGLE-TURN TESTS (via Slack)")
    print("=" * 60)

    results = []
    for test in SINGLE_TURN_TESTS:
        print(f"\n  [{test['name']}]")
        print(f"  Sending: {test['message'][:70]}...")

        msg_ts = send_message(channel, f"<@{BOT_USER_ID}> {test['message']}")
        print(f"  Waiting for reply (up to 60s)...", end=" ", flush=True)

        reply = wait_for_bot_reply(channel, msg_ts, msg_ts, timeout=60)

        if reply:
            text = reply.get("text", "")
            accuracy = score_response(text, test["expected"])
            status = "PASS" if accuracy["score"] >= 0.5 else "FAIL"
            print(f"{status} | accuracy={accuracy['score']:.0%}")
            if accuracy["missing"]:
                print(f"  Missing: {accuracy['missing']}")
            results.append({"name": test["name"], **accuracy})
        else:
            print("TIMEOUT — no reply received")
            results.append({"name": test["name"], "score": 0, "found": [], "missing": test["expected"]})

        time.sleep(2)  # Rate limit

    return results


def run_multi_turn_test(channel: str):
    """Run multi-turn test in a single thread."""
    print("\n" + "=" * 60)
    print("MULTI-TURN TEST (via Slack, single thread)")
    print("=" * 60)

    # Start the thread
    first = MULTI_TURN_TEST[0]
    print(f"\n  [1/{len(MULTI_TURN_TEST)}] {first['test']}")
    print(f"  Sending: {first['message'][:70]}...")
    thread_ts = send_message(channel, f"<@{BOT_USER_ID}> {first['message']}")

    print(f"  Waiting...", end=" ", flush=True)
    reply = wait_for_bot_reply(channel, thread_ts, thread_ts, timeout=60)
    results = []

    if reply:
        acc = score_response(reply.get("text", ""), first["expected"])
        status = "PASS" if acc["score"] >= 0.5 else "FAIL"
        print(f"{status} | {acc['score']:.0%}")
        results.append({"test": first["test"], **acc})
    else:
        print("TIMEOUT")
        results.append({"test": first["test"], "score": 0})

    # Follow-ups in the same thread
    for i, step in enumerate(MULTI_TURN_TEST[1:], 2):
        print(f"\n  [{i}/{len(MULTI_TURN_TEST)}] {step['test']}")
        print(f"  Sending: {step['message'][:70]}...")
        time.sleep(2)

        msg_ts = send_message(channel, step["message"], thread_ts=thread_ts)
        print(f"  Waiting...", end=" ", flush=True)
        reply = wait_for_bot_reply(channel, thread_ts, msg_ts, timeout=60)

        if reply:
            acc = score_response(reply.get("text", ""), step["expected"])
            status = "PASS" if acc["score"] >= 0.5 else "FAIL"
            print(f"{status} | {acc['score']:.0%}")
            if acc["missing"]:
                print(f"  Missing: {acc['missing']}")
            results.append({"test": step["test"], **acc})
        else:
            print("TIMEOUT")
            results.append({"test": step["test"], "score": 0})

    return results


def run_stress_test(channel: str):
    """Run 19-message stress test in one thread."""
    print("\n" + "=" * 60)
    print(f"STRESS TEST (via Slack, {len(STRESS_TEST_MESSAGES)} messages, single thread)")
    print("=" * 60)

    first_msg = STRESS_TEST_MESSAGES[0]
    print(f"\n  [1/{len(STRESS_TEST_MESSAGES)}] {first_msg[:60]}...")
    thread_ts = send_message(channel, f"<@{BOT_USER_ID}> {first_msg}")

    reply = wait_for_bot_reply(channel, thread_ts, thread_ts, timeout=60)
    if reply:
        print(f"  Got reply ({len(reply.get('text', ''))} chars)")
    else:
        print("  TIMEOUT on first message — aborting stress test")
        return []

    results = []
    for i, msg_text in enumerate(STRESS_TEST_MESSAGES[1:], 1):
        print(f"\n  [{i+1}/{len(STRESS_TEST_MESSAGES)}] {msg_text[:60]}...")
        time.sleep(3)

        msg_ts = send_message(channel, msg_text, thread_ts=thread_ts)
        reply = wait_for_bot_reply(channel, thread_ts, msg_ts, timeout=90)

        if reply:
            text = reply.get("text", "")
            print(f"  Got reply ({len(text)} chars)", end="")

            if i in STRESS_CHECKS:
                check = STRESS_CHECKS[i]
                acc = score_response(text, check["expected"])
                status = "PASS" if acc["score"] >= 0.5 else "FAIL"
                print(f" | CHECK {status}: {check['test']} ({acc['score']:.0%})")
                if acc["missing"]:
                    print(f"  Missing: {acc['missing']}")
                results.append({"msg": i, "test": check["test"], **acc})
            else:
                print()
        else:
            print(f"  TIMEOUT")
            if i in STRESS_CHECKS:
                results.append({"msg": i, "test": STRESS_CHECKS[i]["test"], "score": 0})

    return results


def main():
    global BOT_USER_ID, CHANNEL

    print("Slack E2E Integration Test")
    print("=" * 60)
    print("Make sure the bot is running: python -m src.main\n")

    # Auto-detect bot user ID
    BOT_USER_ID = find_bot_user_id()
    print(f"Bot user ID: {BOT_USER_ID}")

    # Find or use configured channel
    if CHANNEL:
        print(f"Using configured channel: {CHANNEL}")
    else:
        CHANNEL = find_test_channel()
        print(f"Auto-detected channel: {CHANNEL}")

    # Run tests
    single_results = run_single_turn_tests(CHANNEL)
    multi_results = run_multi_turn_test(CHANNEL)
    stress_results = run_stress_test(CHANNEL)

    # Summary
    print("\n" + "=" * 60)
    print("E2E TEST SUMMARY")
    print("=" * 60)

    all_scores = []
    print("\nSingle-turn:")
    for r in single_results:
        status = "PASS" if r["score"] >= 0.5 else "FAIL"
        print(f"  [{status}] {r['name']}: {r['score']:.0%}")
        all_scores.append(r["score"])

    print("\nMulti-turn:")
    for r in multi_results:
        status = "PASS" if r.get("score", 0) >= 0.5 else "FAIL"
        print(f"  [{status}] {r['test']}: {r.get('score', 0):.0%}")
        all_scores.append(r.get("score", 0))

    print("\nStress test back-references:")
    for r in stress_results:
        status = "PASS" if r.get("score", 0) >= 0.5 else "FAIL"
        print(f"  [{status}] msg {r['msg']}: {r['test']} ({r.get('score', 0):.0%})")
        all_scores.append(r.get("score", 0))

    if all_scores:
        avg = sum(all_scores) / len(all_scores)
        passed = sum(1 for s in all_scores if s >= 0.5)
        print(f"\nOverall: {passed}/{len(all_scores)} passed, {avg:.0%} avg accuracy")


if __name__ == "__main__":
    main()
