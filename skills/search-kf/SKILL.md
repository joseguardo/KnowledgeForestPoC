---
name: search-kf
description: Query the Kibo Knowledge Forest via the query_knowledge MCP tool — pick the right mode, phrase queries to the graph model, and read results correctly.
---

# Knowledge Forest — query cheat-sheet

## What this is

The Knowledge Forest is a tenant-scoped **knowledge graph**: typed entities
(*pointers*) connected by *edges* and enriched with *attributes* (key/value
facts). You reach it through a single MCP tool, `query_knowledge`. Every query
runs **under your identity** — you only ever see public data plus whatever is
shared with you.

## The tool

```
query_knowledge(query: str, mode: "search" | "answer" | "explore" = "answer")
```

- `query` — a natural-language question. The backend embeds it, plans a 1–3 step
  retrieval across text + semantic + behavioral + graph layers, and runs it.
- `mode` — **defaults to `answer`**. Pick deliberately:

| Mode | Use when… | You get |
|------|-----------|---------|
| `search` | "find / list / which X" — you want the raw matches | ranked `results`, no prose |
| `answer` *(default)* | "what / who / why / summarize" — you want a conclusion | a cited 2–4 sentence `answer` **plus** `results` |
| `explore` | browsing, "tell me more", building a follow-up | `results` **plus** `suggestions` (next questions) |

`answer` is populated only in `answer` mode and only when there are results.
`suggestions` is populated only in `explore` mode.

## How to phrase queries

The planner understands the graph's own vocabulary — lean into it:

- **Entity types** (pointer types): company, person, sector, geography,
  regulation, document, timeseries, agent, skill, tool, flow, component,
  architecture, best_practice, meta, event.
- **Relationships** (edge types): primary_sector, ceo, competitor, hq_location,
  jurisdiction, related, part_of, contains, uses_skill / uses_tool / uses_agent,
  and more.

Name the type and the relationship when you can — it sharpens the plan. One
query is usually enough; the planner expands and traverses on its own. Don't
batch many questions into one string; ask sequentially.

Worked examples:

| Goal | Call |
|------|------|
| List the fintech companies | `query_knowledge("fintech companies", mode="search")` |
| Who runs NVIDIA? | `query_knowledge("Who leads NVIDIA?")` *(answer)* |
| Summarize a company | `query_knowledge("Summarize Belvo")` *(answer)* |
| Fastest-growing sector | `query_knowledge("Which sector grows fastest by CAGR?")` *(answer)* |
| Explore around a topic | `query_knowledge("payments infrastructure", mode="explore")` |

## Reading the response

The tool returns:

```
{ "answer": str | null, "results": [...], "suggestions": [...], "result_count": int }
```

Each entry in `results` looks like:

```
{
  "pointer": { "id", "label", "type" },   // the matched entity
  "source": "search" | "coaccess" | "graph",
  "score": number | null,                  // relevance
  "coaccess_weight": number | null,        // behavioral co-access signal
  "via": ...,                              // edge it was reached through
  "attributes": [ { "key", "value" }, ... ],
  "why": ...                               // edge rationale
}
```

How to use it:

- **`source` tells you why a result surfaced**: `search` = direct text/semantic
  match, `coaccess` = frequently viewed alongside your matches, `graph` =
  reached by following an edge.
- **Always inspect `attributes`.** Key facts live there, and some entities
  appear *only* inside another entity's attributes — e.g. a CEO shows up as
  `CEO=Bancel` on the company, not as its own result row. Mine these; don't
  assume every entity is a top-level result.
- If `answer` is present, lead with it; otherwise summarize `results` yourself.
- In `explore` mode, offer `suggestions` to the user as next steps.

## Clearance caveat — "not found" ≠ "not there"

Results are filtered to what **you** are cleared to read. Restricted content is
removed from results *and* from the composed answer before you ever see it. So
an empty or thin result may mean **you aren't cleared**, not that the data is
absent. Say "I don't see that in what I can access" rather than asserting it
doesn't exist.

## Boundaries

Over MCP you can **only query**. There is no raw SQL, no structured RPCs
(`search_pointers`, `traverse_graph`, …), and no batch/document/calendar
ingestion from here — those live in the Claude Code `/kf-*` workflow. If a task
needs them, say so; don't invent tool calls that don't exist on this surface.
