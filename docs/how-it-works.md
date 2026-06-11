# How the Knowledge Forest Works

## The Core Insight

Every organization looks at the same world differently. An investment fund sees "NVIDIA" as a portfolio candidate sitting in the "AI Infrastructure" sector. A regulatory body sees it as an entity subject to the EU AI Act. A supply chain analyst sees it as a node between TSMC and cloud providers.

The data is the same. The structure is not.

The Knowledge Forest separates **what you know** from **how you see it**.

---

## Two Layers

### Layer 1: The Global Graph (shared truth)

Every piece of knowledge lives as a **pointer** — a lightweight node with a label, a type, and connections to other pointers. A pointer is deliberately minimal: it gates access to deeper information without carrying the weight of it.

Behind each pointer, **attributes** are stored flexibly. A company pointer holds financial metrics in key-value pairs. A document pointer holds ordered text chunks. A timeseries pointer holds time-indexed values. The pointer doesn't care what shape its payload takes — it just points.

Pointers connect to each other through **edges** — directional relationships with explanations. "CrowdStrike → Cybersecurity" because it's the primary sector. "Jensen Huang → NVIDIA" because he's the CEO. The graph is shared across everyone. It's the objective substrate.

### Layer 2: The Forest (subjective view)

Trees and branches are **not stored in the graph**. They emerge from how you use it.

When you navigate the graph — clicking from NVIDIA to AI Infrastructure to the EU AI Act — you leave a trail. That trail is a **query path**. Over time, your paths reveal which concepts you think of together. Pointers that you frequently visit in the same session develop strong **co-access weight**.

When enough weight accumulates, an algorithm clusters the co-accessed pointers into **branches** (groups of related concepts) and merges branches into **trees** (higher-level themes). The algorithm doesn't know what the clusters mean — it only knows what you navigate together. An LLM then names each cluster from the labels inside it.

The result: your forest reflects your mental model. Different tenants navigating the same graph produce completely different forests.

---

## How Trees Grow

```
You navigate:  NVIDIA → AI Infrastructure → EU AI Act → Europe
You navigate:  NVIDIA → AI Infrastructure → CrowdStrike
You navigate:  EU AI Act → Europe → GDPR

Co-access builds:
  NVIDIA ↔ AI Infrastructure    weight: 2.0
  AI Infrastructure ↔ EU AI Act weight: 1.5
  EU AI Act ↔ Europe            weight: 1.5
  NVIDIA ↔ EU AI Act            weight: 0.5
  ...

Clustering detects:
  Branch: [NVIDIA, AI Infrastructure, EU AI Act, Europe]
  → Named: "AI Regulation"

Merging produces:
  Tree: "AI Regulation" containing that branch
```

The tree didn't exist before your navigation created it. And if your navigation patterns shift — if you start exploring biotech instead — the tree structure will eventually shift too.

---

## How Duplicates Are Handled

When new knowledge enters the graph, it must answer one question: **does this already exist?**

The system checks three ways:
1. **Canonical key** — Is there already a pointer with ticker "NVDA"? Exact match → auto-merge.
2. **Text similarity** — Does "Nvidea" look like "NVIDIA"? Fuzzy match via trigram comparison.
3. **Semantic similarity** — Does "Alphabet" mean the same as "Google"? Embedding-based comparison catches what text matching cannot.

The response is tiered:
- **High confidence** (>80% match): merge automatically, no human needed
- **Medium confidence** (40-80%): block insertion, present both to a human for review
- **Low confidence** (<40%): clean insert, no flag

The thresholds are not fixed. Every time a human resolves a duplicate flag, the system records the decision alongside the similarity score. After enough decisions accumulate, the thresholds adapt — sliding toward the boundary where humans actually make their merge/distinct calls.

The system learns where your judgment sits and tries to match it.

---

## Why It Matters

Traditional knowledge management forces you to choose a taxonomy upfront. Folders, tags, categories — all decided before the knowledge arrives. The structure is rigid. When your understanding evolves, the structure doesn't.

The Knowledge Forest inverts this. Knowledge enters as an unstructured graph. Structure emerges from usage. Different people see different structures from the same data. And as your understanding deepens, your forest grows with you.

The forest is not the knowledge. The forest is how you see it.
