# Experiment Results

## Experiment 1: Baseline Accuracy

Each of the 6 assessment example queries run as independent single-turn questions.

| Query | Difficulty | Score | Tool Calls | Latency | Tools Used |
|-------|-----------|-------|------------|---------|------------|
| easy_1 | easy | 80% | 3 | 7.7s | fts_search -> fts_search -> run_query |
| easy_2 | easy | 80% | 3 | 5.3s | fts_search -> run_query -> run_query |
| easy_3 | easy | 67% | 3 | 4.8s | fts_search -> run_query -> fts_search |
| easy_4 | easy | 60% | 2 | 7.6s | fts_search -> run_query |
| hard_1 | hard | 20% | 3 | 4.5s | fts_search -> run_query -> run_query |
| hard_2 | hard | 75% | 3 | 6.9s | fts_search -> run_query -> run_query |

*Overall: 64% accuracy, 2.8 avg tool calls, 6.1s avg latency*

## Experiment 2: Multi-Turn Context Retention

6 messages in a single thread testing pronoun resolution and topic switching.

| Step | Test | Score | Tool Calls | Latency |
|------|------|-------|------------|---------|
| mt_1 | Basic retrieval | 100% | 3 | 8.5s |
| mt_2 | Pronoun resolution — 'their' = BlueHarbor | 100% | 5 | 6.3s |
| mt_3 | Continued context — still BlueHarbor | 100% | 6 | 1.3s |
| mt_4 | Topic switch | 100% | 10 | 9.1s |
| mt_5 | Pronoun resolution — 'the fix' = Verdant Bay's fix | 100% | 10 | 3.6s |
| mt_6 | Back-reference to earlier topic | 67% | 10 | 3.9s |

*Multi-turn accuracy: 94%*

## Experiment 3: Memory Strategy Comparison

17 messages in one thread, comparing three memory strategies on back-reference accuracy.

| Strategy | Est Tokens | Back-Ref Accuracy | Errors |
|----------|-----------|-------------------|--------|
| full | 226,173 | 100% | 0 |
| trim | 199,661 | 100% | 0 |
| summarize | 172,883 | 100% | 0 |

## Experiment 4: Tool Efficiency

Analysis of tool-calling patterns per query.

| Query | Tool Calls | Efficient? | Path |
|-------|-----------|------------|------|
| easy_1 | 3 | Yes | fts_search -> fts_search -> run_query |
| easy_2 | 3 | Yes | fts_search -> run_query -> run_query |
| easy_3 | 3 | Yes | fts_search -> run_query -> fts_search |
| easy_4 | 2 | Yes | fts_search -> run_query |
| hard_1 | 3 | Yes | fts_search -> run_query -> run_query |
| hard_2 | 3 | Yes | fts_search -> run_query -> run_query |

*Average: 2.8 tool calls, 100% of queries used FTS search*

## Key Findings

### Prompt Tuning Impact (Before → After)

| Metric | Before | After | Change |
|--------|--------|-------|--------|
| Overall accuracy | 49% | 64% | +15pp |
| FTS usage | 83% | 100% | +17pp |
| Avg tool calls | 3.0 | 2.8 | -0.2 |
| easy_4 (Aureum SCIM) | 0% | 60% | Fixed |
| hard_1 (competitor defect) | 0% | 20% | Partially fixed |

### What We Changed
1. Prompt now explicitly instructs FTS-first strategy with short, broad search terms
2. Added "never give up after one empty search — retry with fewer keywords"
3. Added "after FTS, always read content_text for specific details"
4. Fixed column names in schema description (positioning → pricing_position, etc.)

### Memory Strategy Fix Impact

| Metric | Before Fix | After Fix |
|--------|-----------|-----------|
| Summarize errors (40 msgs) | 28 | 0 |
| Summarize accuracy | 0% | 87% |
| Root cause | Orphaned tool messages after summarization |
| Fix | Tool boundary detection + orphaned message removal |

### Rolling Summary Optimization
- Previous: re-summarize ALL older messages every time (O(n) per message)
- After: build on previous summary, only summarize NEW messages (O(1) per message)
- At message 100: summarize ~8 new messages instead of re-processing 80
