This repo consists of a SlackQ&A bot that lets team members ask natural language questions about our customer data, the answers come from a SQLLite database containing CRM records, call transcripts, internal docs, and competitor research for 50 customers.

Architecture Decision:
For this I explored three options Raw LangGraph StateGrapgh for full control, DeepAgents for planning, and create_agent from langchain.agents for its built-in ReAct loop.
I chose create_agent because it gave me ReAct pattern without having to wore up the graph manually. It also supports middleware, which I use for conversation memory management.
I considered DeepAgents but it adds sub-agent spawning and filesystem tools that this use case doesn't need.

The SQLlite database has FTS5 full-text search index on the artifacts table. I made this a dedicated tool (fts_search) instead of replying on the agent to write FTS MATCHqueries in raw sql, because FTS5 syntax is non-standard and LLMs frequently get it wrong.
Having this dedicated tool with parameterized queries also prevents SQL injection which original approach I saw used f-strings which is a security hole.

Memory problem:
During experiments, teh multi-turn conversationd worked great upto about 15 messages in which each new message gets all the past messages and responses. After that, I notices three problems:
1. Context window fills up. At 40 messages with tool calls, and results I'm easily hitting 100k+ tokens.
2. I implemented a summerization strategy that compress older messages. But I found a critical bug: when the summerizer removes an AI mssage that had tool_calls, the orphand tool result messages cause OpenAI to reject the request with a 400 error.
I fixed this by detecting tool call boundaries before splitting and filtering orphaned tool messages.
3. The naive summarization was re-processinf teh entire conversation history everytime. At message 50, it was summaerizing messages 1-40 from scratch. I chanegd to rolling summaries where each new summary builds in the previous one, so at message 50 we're only summerizing ~8 messages, not re-reading 40.

Metrics I Tracked:

1. Accuracy - Basic keyword matching against the expected answers. The assessment provided some expected queries with their answers. I extract the key facts like customer names, specific dates, dollar amounts, and technical commands from those answers and check if the agent's response contains them. This gives a percentage score per query.
2. Tool call efficiency - How many tool calls the agent makes to reach an answer. Fewer calls mean the agent is making smarter decisions about which tool to use and when.
3. Latency - The wall clock time taken from the question being asked to when we get the response.
4. Token usage - Estimated from message content. This directly maps to API cost. I track this per message and cumulatively across a conversation to understand how costs scale with conversation length.
5. FTS usage rate - What percentage of queries start with full-text search versus raw SQL. This tells us whether the agent is following the intended retrieval strategy or not.
6. Back-reference accuracy - In long conversations, can the agent recall facts from much earlier messages? I test this by asking about "the first customer we discussed" after twenty-plus intervening messages.

Experiments I ran:
1. Baseline accuracy - Each of the six assessment example queries run independently with a fresh thread, no prior context. Measures whether the agent can find the right answer and how efficiently it gets there.
2. Multi-turn context - A scripted six-message conversation in a single thread that tests pronoun resolution (e.g., "What's their competitor risk?"), topic switching (e.g., "Now switch to Verdant Bay"), and back-references (e.g., "Go back to BlueHarbor"). Tests whether the checkpoint-based memory actually works.
3. Memory strategy comparison - The same 17-message conversation run three times, each with a different memory strategy:
    Full history: sending everything to the LLM.
    Trim: dropping older messages and sending only the recent ones as context.
    Summarize: compressing the older messages into a summary and keeping the recent raw messages.
I wanted to find out how accuracy and token cost vary for each approach.
4. Tool efficiency - Analyzes the tool-calling patterns from the baseline experiment. Which queries start with FTS versus raw SQL? Are there unnecessary schema lookups? How many retries happen on failed SQL queries?
5. Stress test - A 40-message conversation covering 4+ customers, followed by back-reference questions that require recalling facts from 20 to 30 messages ago. Run across all three memory strategies to find the breaking point. This is where I discovered the orphaned tool message bug in the summarization strategy.

What Experiments Showed:
I ran four experiemnts. I took the six examples mentioned in the assessment as a baseline. For the baseline accuracy, the six example queries initially gave me the baseline accuracy of 49%. Two queries scored 0%. Out of those two:
- One because the agent tried raw SQL instead of searching the text content
- Another because it built an overly specific search query and gave up after one empty result
After tuning the prompt to be explicit about when to use FTS versus SQL and to retry with broader keywords on empty results, accuracy improved to 64%, and all the six questions or six queries now use FTS as the first step. We also tried the multi-turn context and found out that it works 100%. We tracked the matrix-like pronoun resolution, topic switching, and then back references. 
All of these experiments succeeded. I also did a 40-message stress test that showed 87% accuracy on back references across all three memory strategies.

Security:
for the security, I have done a few things:
- I made a SQLite connection read-only.
- I also implemented SQL validation that blocks any non-select parameterized queries for FTS, so no F-strings equal and prompt-level guardrail for the Slack webhook verification. It is handled automatically by Bolt SDKs' SHA256 validation.

My thoughts for Production
I would switch the current socket mode to HTTP Events API for scalability, and then I would also switch memory saver with PostgresSaver for persistence across restarts. I would add schema caching so the agent doesn't  re-discover table structures on every query, and then I will add model feedback chains for resilience and the hard queries, which include, for example, from the question, competitor defection risk which still needs work. It requires multi-hop reasoning across three to four artifacts that the current single pass through struggles with. 
