# ADR: Advisor orchestration — LangGraph + MCP server, not Bedrock Agents

Status: Accepted (2026-11-11) · Capability 2 of the six-capability plan (§7)

## Context

CreditMate needs a natural-language card advisor that calls typed,
read-only tools over the existing catalogue (search, compare,
eligibility, calculators, semantic retrieval) with structured outputs,
permission scoping, human confirmation before any action, and a graceful
fallback to normal search. Candidates: LangGraph (in-process Python),
AWS Bedrock Agents (managed), an MCP server alone, or a combination.

## Decision

**LangGraph as the orchestrator, plus an MCP server exposing the same
tool layer. Not Bedrock Agents.**

The tools are built once, framework-free, in `advisor/tools.py` with
Pydantic v2 contracts and a read-only registry. LangGraph
(`advisor/graph.py`) and the MCP server (`advisor/mcp_server.py`, official
`mcp` SDK) are both thin adapters over that layer.

## Why

- **Testability.** LangGraph runs inside the Django process: the BE test
  suite exercises the full graph with a deterministic FakeChatProvider,
  sockets disabled, no credentials. Bedrock Agents is a managed runtime
  outside the repo — its behaviour cannot be unit-tested, only observed
  in AWS.
- **Local development.** The whole advisor runs offline in the k3d/
  compose stack. Bedrock Agents has no local or offline dev loop.
- **Learning value.** The market research behind this programme found
  agentic *orchestration* (graphs, tool loops, state, guardrails) in
  10/12 AI postings. Bedrock Agents teaches console configuration;
  LangGraph teaches the orchestration engineering itself. Ash already
  has production Bedrock experience (Powerley/BillWise), so Bedrock
  Agents also adds the least new, truthful resume signal.
- **Data honesty control.** Grounding, vocabulary restriction
  (Eligible / Likely / No published requirement / Not yet), forbidden
  phrases ("pre-approved", "guaranteed"), budget guards and the
  no-persistence rule for eligibility inputs are enforced in our code,
  in the graph's compose step and in the tools themselves — not
  delegated to a vendor's guardrail configuration.
- **MCP is nearly free once tools exist.** Because the tool layer is
  framework-free, exposing it over MCP costs one adapter module and
  makes CreditMate callable from external MCP clients — the second
  researched surface — without a second implementation.

## Consequences

- We own the operational concerns (timeouts, step caps, budgets,
  fallbacks) — they are implemented in `advisor/graph.py` and the
  `common/llm` budget machinery.
- LangGraph/LangChain churn is contained: pins are `<next major`,
  locked with uv, and the framework is isolated behind `advisor/graph.py`
  + `common/llm/chat.py`. Swapping the orchestrator touches those two
  modules; the tool layer and MCP server are unaffected.
- Checkpointer: sessions persist via Django models
  (`AdvisorSession`/`AdvisorMessage`). A Postgres LangGraph
  checkpointer is a recorded TODO in `graph.py`, pending a deliberate
  psycopg3 pool alongside Django's psycopg2 stack.
- No AWS account, IAM surface or per-request Bedrock cost is required
  by this capability.
