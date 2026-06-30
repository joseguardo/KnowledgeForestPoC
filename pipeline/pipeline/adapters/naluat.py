from __future__ import annotations

import csv
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# Parses Kibo's Naluat fund ledger (the exported `naluat_neo.json`, fallback
# `naluat_neo.csv`) into a graph model the API layer writes through the edge
# functions. Unlike the Affinidad adapter this source is a flat file, not a
# Postgres connection, so the whole adapter is pure/offline — every row is one
# transaction; companies and funds are rollups computed from those rows.
#
#   funds        -> `fund` pointers (4)        + fund-level rollups
#   companies    -> `company` pointers (50)    + rollups + valuation series
#                   (12 reconcile to existing pointers and MERGE; 38 are new)
#   transactions -> `event` pointers (347)     one per row, occurred_at = date
#   edges        -> company —part_of→ fund, event —transaction_of→ company,
#                   event —booked_to→ fund     (rich payloads for traversal)
#
# Everything is stamped source="Naluat" (exact casing) and access_class
# firm:<kibo> by the API layer. This adapter only builds the specs.

# Kibo tenant (the only firm Naluat data is visible to).
KIBO_TENANT = "ca61f0e5-563e-5894-954f-38f5a9e0eabc"

# Exact source string for every Naluat attribute (never all-caps "NALUAT").
SOURCE = "Naluat"

# Repo-root default for the exported ledger (…/pipeline/pipeline/adapters/naluat.py
# → repo root is three parents up).
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_SOURCE_PATH = str(_REPO_ROOT / "naluat_neo.json")

# Of the 50 Naluat companies, these 12 already exist in the graph: reuse the
# existing canonical_key so insert-pointer MERGES (enriches) the pointer rather
# than creating a duplicate. The other 38 get a fresh naluat-namespaced key.
RECONCILIATION: dict[str, str] = {
    "Anyformat": f"company::{KIBO_TENANT}::anyformat.ai",
    "Cala": f"company::{KIBO_TENANT}::cala.ai",
    "Fossa Systems": f"company::{KIBO_TENANT}::fossa.systems",
    "NeuralTrust": f"company::{KIBO_TENANT}::neuraltrust.ai",
    "Qida": f"company::{KIBO_TENANT}::qida.es",
    "Trucksters": f"company::{KIBO_TENANT}::trucksters.io",
    "Zynap": f"company::{KIBO_TENANT}::zynap.com",
    "Circular": f"company::{KIBO_TENANT}::cocircular.es",
    "Green Eagle": f"company::{KIBO_TENANT}::greeneaglesolutions.com",
    "KD": f"company::{KIBO_TENANT}::kdpof.com",
    "Plenit": f"company::{KIBO_TENANT}::jotelulu.com",
    "Theker": f"company::{KIBO_TENANT}::theker.eu",
}

# Row `type` prefix → canonical transaction_type. Raw type/subtype are preserved
# on the event for traceability.
_TXN_TYPE = {
    "investment": "investment",
    "valuation": "valuation",
    "partial_divestment": "divestment",
    "full_divestment": "divestment",
    "write_off": "write_off",
}


# ── Attribute / value helpers ───────────────────────────────────────

# (key, value, data_type) tuples destined for attributes_kv (mirrors Affinidad).
Attr = tuple[str, Any, str]


def slug(value: str) -> str:
    """Lowercase, non-alphanumeric → single hyphen, trimmed. Used for fund and
    new-company canonical keys."""
    s = re.sub(r"[^a-z0-9]+", "-", (value or "").strip().lower())
    return s.strip("-")


def _str(v: Any) -> str | None:
    if v is None:
        return None
    s = str(v).strip()
    return s or None


def _num(v: Any) -> float | int | None:
    """Coerce numeric-ish source values (some `data.*` come as strings) to a
    number. Empty / non-numeric → None (attribute omitted)."""
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    try:
        f = float(str(v).strip().replace(",", ""))
    except (TypeError, ValueError):
        return None
    return int(f) if f.is_integer() else f


def _date10(v: Any) -> str | None:
    """ISO timestamp → YYYY-MM-DD (for labels / date attributes)."""
    s = _str(v)
    return s[:10] if s else None


def transaction_type(row_type: str | None) -> str | None:
    """Map a row `type` to its canonical transaction_type via prefix match."""
    t = (row_type or "").strip().lower()
    if t in _TXN_TYPE:
        return _TXN_TYPE[t]
    prefix = t.split("/", 1)[0]
    return _TXN_TYPE.get(prefix)


# ── Normalized records ──────────────────────────────────────────────


@dataclass
class FundSpec:
    name: str
    canonical_key: str
    attributes: list[Attr]


@dataclass
class CompanySpec:
    name: str
    canonical_key: str
    existing: bool          # True → reuse existing pointer (merge), False → new
    funds: list[str]        # fund names this company appears under
    attributes: list[Attr]


@dataclass
class EventSpec:
    src_id: str             # unique row id
    canonical_key: str
    label: str
    occurred_at: str | None
    company: str
    fund: str
    transaction_type: str
    amount: float | int | None
    currency: str | None
    attributes: list[Attr]


@dataclass
class EdgeSpec:
    source_key: str         # canonical_key of the source pointer
    target_key: str         # canonical_key of the target pointer
    relationship_type: str  # part_of | transaction_of | booked_to
    why: str
    payload: dict[str, Any] | None = None


@dataclass
class NaluatModel:
    funds: list[FundSpec] = field(default_factory=list)
    companies: list[CompanySpec] = field(default_factory=list)
    events: list[EventSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)
    unmapped: list[str] = field(default_factory=list)  # row ids with no txn_type

    def counts(self) -> dict[str, int]:
        existing = sum(1 for c in self.companies if c.existing)
        part_of = sum(1 for e in self.edges if e.relationship_type == "part_of")
        return {
            "funds": len(self.funds),
            "companies_existing": existing,
            "companies_new": len(self.companies) - existing,
            "events": len(self.events),
            "edges": len(self.edges),
            "edges_part_of": part_of,
            "edges_transaction_of": sum(
                1 for e in self.edges if e.relationship_type == "transaction_of"
            ),
            "edges_booked_to": sum(
                1 for e in self.edges if e.relationship_type == "booked_to"
            ),
            "unmapped": len(self.unmapped),
        }


# ── Canonical-key helpers ───────────────────────────────────────────


def fund_key(name: str) -> str:
    return f"fund:naluat:{slug(name)}"


def company_key(name: str) -> str:
    existing = RECONCILIATION.get(name)
    if existing:
        return existing
    return f"company::{KIBO_TENANT}::naluat:{slug(name)}"


def event_key(row_id: str) -> str:
    return f"event:naluat:{row_id}"


# ── Source loading ──────────────────────────────────────────────────


def load_rows(source_path: str | None = None) -> list[dict[str, Any]]:
    """Load the ledger rows from the JSON export, falling back to the CSV (same
    dir). Returns a list of dicts with the source column names preserved."""
    path = Path(source_path or DEFAULT_SOURCE_PATH)
    if path.suffix.lower() == ".json" and not path.exists():
        path = path.with_suffix(".csv")
    if not path.exists():
        raise FileNotFoundError(f"Naluat source not found: {path}")
    if path.suffix.lower() == ".csv":
        with path.open(newline="", encoding="utf-8") as fh:
            return list(csv.DictReader(fh))
    with path.open(encoding="utf-8") as fh:
        data = json.load(fh)
    if isinstance(data, dict):
        data = data.get("rows") or data.get("data") or []
    return list(data)


# ── Builders ────────────────────────────────────────────────────────


def _add_ccy(bucket: dict[str, float], ccy: str | None, amount: Any) -> None:
    a = _num(amount)
    c = _str(ccy)
    if a is None or not c:
        return
    bucket[c] = round(bucket.get(c, 0.0) + float(a), 6)


def _event_attrs(row: dict[str, Any], txn_type: str) -> list[Attr]:
    """Event attributes, omitting any whose source value is empty."""
    pairs: list[Attr] = [
        ("amount", _num(row.get("amount")), "number"),
        ("currency", _str(row.get("currency")), "string"),
        ("transaction_type", txn_type, "string"),
        ("raw_type", _str(row.get("type")), "string"),
        ("raw_subtype", _str(row.get("subtype")), "string"),
        ("fund", _str(row.get("fund_name")), "string"),
        ("round_name", _str(row.get("data.nombre_ronda")), "string"),
        ("follow_on", _str(row.get("data.follow_on")), "string"),
        ("pps", _num(row.get("data.pps")), "number"),
        ("premoney", _num(row.get("data.premoney")), "number"),
        ("shares", _num(row.get("data.shares")), "number"),
        ("reported_value", _num(row.get("data.reported_value")), "number"),
        ("is_calculated", _bool(row.get("isCalculated")), "boolean"),
        ("src_id", _row_id(row), "string"),
    ]
    return [(k, v, dt) for (k, v, dt) in pairs if v is not None]


def _bool(v: Any) -> bool | None:
    if v is None or v == "":
        return None
    if isinstance(v, bool):
        return v
    s = str(v).strip().lower()
    if s in ("true", "1", "yes"):
        return True
    if s in ("false", "0", "no"):
        return False
    return None


def _row_id(row: dict[str, Any]) -> str | None:
    return _str(row.get("id")) or _str(row.get("elementId")) or _str(row.get("investment"))


def build_model(source_path: str | None = None) -> NaluatModel:
    """Parse the ledger and produce the full graph model (pure / offline)."""
    rows = load_rows(source_path)
    model = NaluatModel()

    # Per-company and per-fund accumulators.
    comp_funds: dict[str, list[str]] = {}
    comp_invested: dict[str, dict[str, float]] = {}
    comp_realized: dict[str, dict[str, float]] = {}
    comp_dates: dict[str, list[str]] = {}
    comp_ccy_count: dict[str, dict[str, int]] = {}
    comp_status: dict[str, str] = {}
    # valuation rows per company: (date, currency, amount) with usable amount.
    comp_valuations: dict[str, list[tuple[str, str, float]]] = {}

    fund_companies: dict[str, set[str]] = {}
    fund_invested: dict[str, dict[str, float]] = {}

    company_fund_pairs: set[tuple[str, str]] = set()

    for row in rows:
        company = _str(row.get("company"))
        fund = _str(row.get("fund_name"))
        rid = _row_id(row)
        if not company or not fund or not rid:
            continue
        raw_type = _str(row.get("type"))
        txn_type = transaction_type(raw_type)
        if txn_type is None:
            model.unmapped.append(rid or raw_type or "?")
            continue

        amount = _num(row.get("amount"))
        ccy = _str(row.get("currency"))
        date = _str(row.get("date"))

        # ── event pointer ──
        date10 = _date10(date) or ""
        label = f"{company} — {txn_type} — {date10}".rstrip(" —")
        model.events.append(
            EventSpec(
                src_id=rid,
                canonical_key=event_key(rid),
                label=label,
                occurred_at=date,
                company=company,
                fund=fund,
                transaction_type=txn_type,
                amount=amount,
                currency=ccy,
                attributes=_event_attrs(row, txn_type),
            )
        )

        # ── rollup accumulation ──
        comp_funds.setdefault(company, [])
        if fund not in comp_funds[company]:
            comp_funds[company].append(fund)
        fund_companies.setdefault(fund, set()).add(company)
        company_fund_pairs.add((company, fund))

        if date:
            comp_dates.setdefault(company, []).append(date)
        if ccy:
            cc = comp_ccy_count.setdefault(company, {})
            cc[ccy] = cc.get(ccy, 0) + 1

        if txn_type == "investment":
            _add_ccy(comp_invested.setdefault(company, {}), ccy, amount)
            _add_ccy(fund_invested.setdefault(fund, {}), ccy, amount)
        elif txn_type == "divestment":
            _add_ccy(comp_realized.setdefault(company, {}), ccy, amount)
        elif txn_type == "valuation":
            a = _num(amount)
            if a is not None and ccy and date:
                comp_valuations.setdefault(company, []).append((date, ccy, float(a)))

        # status precedence: write_off > divestment(full) > partial > active
        st = comp_status.get(company, "active")
        if raw_type == "write_off":
            comp_status[company] = "written_off"
        elif raw_type == "full_divestment" and st != "written_off":
            comp_status[company] = "divested"
        elif raw_type == "partial_divestment" and st in ("active",):
            comp_status[company] = "partially_divested"

    # ── fund specs ──
    for fund in sorted(fund_companies):
        invested = fund_invested.get(fund, {})
        attrs: list[Attr] = [
            ("naluat_company_count", len(fund_companies[fund]), "number"),
        ]
        if invested:
            attrs.append(("naluat_invested_by_currency", invested, "json"))
        model.funds.append(
            FundSpec(name=fund, canonical_key=fund_key(fund), attributes=attrs)
        )

    # ── company specs ──
    for company in sorted(comp_funds):
        funds = comp_funds[company]
        existing = company in RECONCILIATION
        invested = comp_invested.get(company, {})
        realized = comp_realized.get(company, {})
        dates = sorted(comp_dates.get(company, []))
        # primary currency = most frequent ccy across this company's rows
        ccy_count = comp_ccy_count.get(company, {})
        primary_ccy = max(ccy_count, key=ccy_count.get) if ccy_count else None
        # valuation series, time-ordered
        vseries = sorted(comp_valuations.get(company, []), key=lambda t: t[0])
        series = [{"date": d, "currency": c, "amount": a} for (d, c, a) in vseries]
        # current value = latest valuation amount per currency
        current: dict[str, float] = {}
        for (d, c, a) in vseries:
            current[c] = a  # later dates overwrite (sorted ascending)
        # MOIC where computable (single primary ccy with invested > 0)
        moic = _moic(invested, realized, current, primary_ccy)

        attrs: list[Attr] = [
            ("naluat_status", comp_status.get(company, "active"), "string"),
        ]
        if invested:
            attrs.append(("naluat_invested_by_currency", invested, "json"))
        if realized:
            attrs.append(("naluat_realized_by_currency", realized, "json"))
        if current:
            attrs.append(("naluat_current_value_by_currency", current, "json"))
        if moic is not None:
            attrs.append(("naluat_moic", moic, "number"))
        if dates:
            attrs.append(("naluat_first_date", _date10(dates[0]), "date"))
            attrs.append(("naluat_last_date", _date10(dates[-1]), "date"))
        if primary_ccy:
            attrs.append(("naluat_currency", primary_ccy, "string"))
        if funds:
            attrs.append(("naluat_funds", funds, "json"))
        if series:
            attrs.append(("naluat_valuation_series", series, "json"))

        model.companies.append(
            CompanySpec(
                name=company,
                canonical_key=company_key(company),
                existing=existing,
                funds=funds,
                attributes=attrs,
            )
        )

    # ── edges ──
    # company —part_of→ fund (one per company/fund pair)
    for (company, fund) in sorted(company_fund_pairs):
        model.edges.append(
            EdgeSpec(
                source_key=company_key(company),
                target_key=fund_key(fund),
                relationship_type="part_of",
                why=f"{company} is part of {fund} (Naluat)",
            )
        )
    # event —transaction_of→ company  and  event —booked_to→ fund
    for ev in model.events:
        payload = {
            "amount": ev.amount,
            "currency": ev.currency,
            "transaction_type": ev.transaction_type,
            "company": ev.company,
            "fund": ev.fund,
            "date": _date10(ev.occurred_at),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        model.edges.append(
            EdgeSpec(
                source_key=ev.canonical_key,
                target_key=company_key(ev.company),
                relationship_type="transaction_of",
                why=f"{ev.transaction_type} transaction of {ev.company} (Naluat)",
                payload=payload,
            )
        )
        model.edges.append(
            EdgeSpec(
                source_key=ev.canonical_key,
                target_key=fund_key(ev.fund),
                relationship_type="booked_to",
                why=f"{ev.transaction_type} booked to {ev.fund} (Naluat)",
                payload=payload,
            )
        )

    return model


def _moic(
    invested: dict[str, float],
    realized: dict[str, float],
    current: dict[str, float],
    primary_ccy: str | None,
) -> float | None:
    """MOIC = (realized + current value) / invested, computed in the primary
    currency only (cross-currency MOIC is not meaningful). None if not
    computable (no invested, or no primary ccy, or invested is 0)."""
    if not primary_ccy:
        return None
    inv = invested.get(primary_ccy)
    if not inv:
        return None
    gained = realized.get(primary_ccy, 0.0) + current.get(primary_ccy, 0.0)
    return round(gained / inv, 4)
