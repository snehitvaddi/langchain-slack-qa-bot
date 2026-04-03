"""Test scenarios for experiments — queries, multi-turn scripts, and expected results."""

# =============================================================================
# Experiment 1: Baseline Accuracy — The 6 assessment example queries
# =============================================================================

BASELINE_QUERIES = [
    {
        "id": "easy_1",
        "difficulty": "easy",
        "query": "which customer's issue started after the 2026-02-20 taxonomy rollout, and what proof plan did we propose to get them comfortable with renewal?",
        "expected_keywords": ["BlueHarbor", "7-10 business day", "proof-of-fix", "A/B test", "80 percent"],
    },
    {
        "id": "easy_2",
        "difficulty": "easy",
        "query": "for Verdant Bay, what's the approved live patch window, and exactly how do we roll back if the validation checks fail?",
        "expected_keywords": ["2026-03-24", "02:00", "04:00", "orchestrator rollback", "ruleset"],
    },
    {
        "id": "easy_3",
        "difficulty": "easy",
        "query": "in the MapleHarvest Quebec pilot, what temporary field mappings are we planning in the router transform, and what is the March 23 workshop supposed to produce?",
        "expected_keywords": ["txn_id", "transaction_id", "total_amount", "amount_cents", "schema document", "SI-SCHEMA-REG"],
    },
    {
        "id": "easy_4",
        "difficulty": "easy",
        "query": "what SCIM fields were conflicting at Aureum, and what fast fix did Jin propose so we don't have to wait on Okta change control?",
        "expected_keywords": ["department", "businessUnit", "hot-reloadable", "preprocessing rule", "SCIM tracing"],
    },
    {
        "id": "hard_1",
        "difficulty": "hard",
        "query": "which customer looks most likely to defect to a cheaper tactical competitor if we miss the next promised milestone, and what exactly is that milestone?",
        "expected_keywords": ["BlueHarbor", "NoiseGuard", "proof-of-fix", "2026-03-19", "2026-03-22"],
    },
    {
        "id": "hard_2",
        "difficulty": "hard",
        "query": "do we have a recurring Canada approval-bypass pattern across accounts, or is MapleBridge basically a one-off? Give me the customer names and the shared failure pattern in plain English.",
        "expected_keywords": ["MapleBridge", "Verdant Bay", "recurring", "approval"],
    },
]

# =============================================================================
# Experiment 2: Multi-Turn Context Retention
# =============================================================================

MULTI_TURN_SCRIPT = [
    {
        "id": "mt_1",
        "message": "Tell me about BlueHarbor Logistics — what's their current situation?",
        "expected_keywords": ["BlueHarbor", "taxonomy", "search relevance"],
        "tests": "Basic retrieval",
    },
    {
        "id": "mt_2",
        "message": "What's their competitor risk? Could they leave us?",
        "expected_keywords": ["NoiseGuard", "BlueHarbor"],
        "tests": "Pronoun resolution — 'their' = BlueHarbor",
    },
    {
        "id": "mt_3",
        "message": "What's the contract value and deployment model?",
        "expected_keywords": ["780", "multi-tenant"],
        "tests": "Continued context — still BlueHarbor",
    },
    {
        "id": "mt_4",
        "message": "Now switch to Verdant Bay. What's going on with them?",
        "expected_keywords": ["Verdant Bay", "approval"],
        "tests": "Topic switch",
    },
    {
        "id": "mt_5",
        "message": "What's the rollback plan if the fix fails?",
        "expected_keywords": ["orchestrator rollback", "ruleset"],
        "tests": "Pronoun resolution — 'the fix' = Verdant Bay's fix",
    },
    {
        "id": "mt_6",
        "message": "Go back to BlueHarbor — what was the proof-of-fix timeline we proposed?",
        "expected_keywords": ["7-10", "A/B test", "BlueHarbor"],
        "tests": "Back-reference to earlier topic",
    },
]

# =============================================================================
# Experiment 3: Long Conversation — 20+ messages for memory stress test
# =============================================================================

LONG_CONVERSATION_SCRIPT = [
    # Phase 1: Build up context about multiple customers (messages 1-12)
    "Tell me about BlueHarbor Logistics and their key issues.",
    "What's the proof-of-fix plan for BlueHarbor?",
    "Who is the primary competitor threat for BlueHarbor?",
    "Now tell me about MapleBridge Insurance.",
    "What approval bypass issues are they having?",
    "Is this a one-off or a pattern across Canadian accounts?",
    "Tell me about Verdant Bay's situation.",
    "What's the emergency playbook for Verdant Bay?",
    "What's the live patch window?",
    "Now tell me about Aureum and the SCIM issue.",
    "What did Jin propose as a fix?",
    "How many at-risk customers do we have total?",
    # Phase 2: Back-references that require memory of earlier context (13-17)
    "Going back to the very first customer we discussed — what was their contract value?",
    "And the Canadian customer with approval issues — what was the root cause again?",
    "Compare the BlueHarbor situation with Verdant Bay — which is more urgent?",
    "What were all the competitors mentioned across all the customers we discussed?",
    "Summarize everything we've discussed in this conversation.",
]

# Expected keywords for the back-reference questions (messages 13-17)
LONG_CONVERSATION_CHECKS = [
    {"msg_index": 12, "expected": ["BlueHarbor", "780"], "tests": "Back-ref to msg 1 customer + contract value"},
    {"msg_index": 13, "expected": ["MapleBridge", "approval", "Canada"], "tests": "Back-ref to msg 4-6 topic"},
    {"msg_index": 14, "expected": ["BlueHarbor", "Verdant Bay"], "tests": "Cross-reference two earlier topics"},
    {"msg_index": 15, "expected": ["NoiseGuard"], "tests": "Recall competitors from earlier discussion"},
    {"msg_index": 16, "expected": ["BlueHarbor", "MapleBridge", "Verdant Bay", "Aureum"], "tests": "Full conversation recall"},
]
