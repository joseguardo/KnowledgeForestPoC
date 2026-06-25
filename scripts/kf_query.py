#!/usr/bin/env python3
"""
kf_query.py — run queries against the KnowledgeForest Supabase project.

No dependencies (stdlib only). Three query paths:
  - nl       natural-language question  -> query-knowledge edge function
  - fund     companies in a fund        -> traverse_graph
  - company  one company's full payload -> search_pointers (inline naluat blob)
  - status   companies by naluat_status -> search_pointers (deterministic filter)
  - rpc      call any RPC with raw JSON  -> /rest/v1/rpc/<name>

──────────────────────────────────────────────────────────────────────────────
CREDENTIALS
──────────────────────────────────────────────────────────────────────────────
The NALUAT data is firm-classed (Kibo-only). What you see depends on the key:
  • service-role key  -> sees everything   (best for your own testing)
  • a Kibo user JWT   -> that user's clearance
  • anon key          -> public rows only  (NALUAT financials come back EMPTY)

Provide a key in any ONE of these ways (checked in this order):
  1. Environment variable (recommended):
        export KF_KEY="<service-role-or-jwt>"
  2. pipeline/.env       -> SUPABASE_SERVICE_ROLE_KEY=<service-role>
  3. .env.local          -> VITE_SUPABASE_ANON_KEY=<anon>   (fallback, limited)

URL/tenant are auto-read from .env.local; override with KF_URL / KF_TENANT.

Where to get the service-role key:
  Supabase dashboard -> Project Settings -> API -> "service_role" secret
  (project KnowledgeForest, ref sjiepibqadbdowcizccw).

──────────────────────────────────────────────────────────────────────────────
EXAMPLES
──────────────────────────────────────────────────────────────────────────────
  export KF_KEY="eyJ...service-role..."
  python3 scripts/kf_query.py nl "Which Fund III companies were written off?"
  python3 scripts/kf_query.py nl "Summarize Devo" --mode answer
  python3 scripts/kf_query.py fund "Fund III"
  python3 scripts/kf_query.py company "Belvo"
  python3 scripts/kf_query.py status divested
  python3 scripts/kf_query.py rpc search_pointers '{"p_types":["company"],"p_limit":5}'
Add --time for latency, --json for raw output.
"""
import argparse, json, os, sys, time, urllib.request, urllib.error

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_URL = "https://sjiepibqadbdowcizccw.supabase.co"
DEFAULT_TENANT = "ca61f0e5-563e-5894-954f-38f5a9e0eabc"  # Kibo


def _read_env_file(path):
    out = {}
    if not os.path.exists(path):
        return out
    for line in open(path):
        line = line.rstrip("\n")
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def resolve_creds():
    local = _read_env_file(os.path.join(ROOT, ".env.local"))
    pipe = _read_env_file(os.path.join(ROOT, "pipeline", ".env"))
    url = os.environ.get("KF_URL") or local.get("VITE_SUPABASE_URL") or DEFAULT_URL
    tenant = os.environ.get("KF_TENANT") or local.get("VITE_KIBO_TENANT_ID") or DEFAULT_TENANT

    key, source = None, None
    if os.environ.get("KF_KEY"):
        key, source = os.environ["KF_KEY"], "env KF_KEY"
    else:
        svc = pipe.get("SUPABASE_SERVICE_ROLE_KEY", "")
        if svc and not svc.startswith("<"):          # skip the <PASTE_...> placeholder
            key, source = svc, "pipeline/.env service-role"
        elif local.get("VITE_SUPABASE_ANON_KEY"):
            key, source = local["VITE_SUPABASE_ANON_KEY"], "anon (limited — firm data hidden)"
    if not key:
        sys.exit("No key found. Set one:  export KF_KEY='<service-role-or-jwt>'  (see header).")
    return url, key, tenant, source


def post(url, path, key, body, want_time=False):
    req = urllib.request.Request(
        url + path, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "apikey": key, "Content-Type": "application/json"},
        method="POST")
    t = time.perf_counter()
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            payload = json.loads(r.read().decode() or "null")
    except urllib.error.HTTPError as e:
        payload = {"error": e.code, "body": e.read().decode()[:500]}
    ms = (time.perf_counter() - t) * 1000
    if want_time:
        print(f"[latency {ms:.0f} ms]", file=sys.stderr)
    return payload


def rpc(url, key, name, body, want_time=False):
    return post(url, f"/rest/v1/rpc/{name}", key, body, want_time)


def find_pointer(url, key, label, ptype):
    """Resolve a pointer id by label+type via search_pointers."""
    res = rpc(url, key, "search_pointers", {"p_types": [ptype], "p_query_text": label, "p_limit": 5})
    for r in (res.get("results") or []):
        if r.get("label", "").lower() == label.lower():
            return r
    return (res.get("results") or [None])[0]


def main():
    ap = argparse.ArgumentParser(description="Query the KnowledgeForest graph.")
    ap.add_argument("--time", action="store_true", help="print latency to stderr")
    ap.add_argument("--json", action="store_true", help="print raw JSON response")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("nl", help="natural-language question (query-knowledge)")
    p.add_argument("question")
    p.add_argument("--mode", default="answer", choices=["answer", "search", "explore"])

    p = sub.add_parser("fund", help="list companies in a fund")
    p.add_argument("name")

    p = sub.add_parser("company", help="show one company's naluat payload")
    p.add_argument("name")

    p = sub.add_parser("status", help="companies by naluat_status")
    p.add_argument("value", choices=["active", "divested", "written_off"])

    p = sub.add_parser("rpc", help="call any RPC with raw JSON body")
    p.add_argument("name")
    p.add_argument("body", help='JSON, e.g. \'{"p_types":["company"],"p_limit":5}\'')

    args = ap.parse_args()
    url, key, tenant, source = resolve_creds()
    print(f"# key: {source}", file=sys.stderr)

    if args.cmd == "nl":
        out = post(url, "/functions/v1/query-knowledge", key,
                   {"query": args.question, "tenant_id": tenant, "mode": args.mode}, args.time)
        if args.json:
            print(json.dumps(out, indent=2)); return
        if out.get("answer"):
            print(out["answer"]); print()
        for r in (out.get("results") or [])[:15]:
            print(f"  • {r.get('label')}  [{r.get('type')}]")
        return

    if args.cmd == "fund":
        f = find_pointer(url, key, args.name, "meta")
        if not f:
            sys.exit(f"Fund '{args.name}' not found (or hidden by your key's clearance).")
        out = rpc(url, key, "traverse_graph",
                  {"p_start_ids": [f["id"]], "p_edge_types": ["part_of"],
                   "p_direction": "inbound", "p_depth": 1, "p_limit": 100}, args.time)
        if args.json:
            print(json.dumps(out, indent=2)); return
        rows = out if isinstance(out, list) else out.get("results", out)
        print(f"# {f['label']}:")
        for r in (rows or []):
            print(f"  • {r.get('label')}")
        return

    if args.cmd == "company":
        out = rpc(url, key, "search_pointers",
                  {"p_types": ["company"], "p_query_text": args.name, "p_limit": 5}, args.time)
        if args.json:
            print(json.dumps(out, indent=2)); return
        for r in (out.get("results") or []):
            if r.get("label", "").lower() != args.name.lower():
                continue
            print(f"# {r['label']}")
            for a in (r.get("attributes") or []):
                if a["key"] == "naluat":
                    print(json.dumps(a["value"], indent=2))
                else:
                    print(f"  {a['key']}: {a['value']}")
            return
        print(f"'{args.name}' not found (or hidden by your key's clearance).")
        return

    if args.cmd == "status":
        out = rpc(url, key, "search_pointers",
                  {"p_types": ["company"], "p_attr_filters": {"naluat_status": args.value},
                   "p_limit": 100}, args.time)
        if args.json:
            print(json.dumps(out, indent=2)); return
        print(f"# {args.value}: {out.get('total')} companies")
        for r in (out.get("results") or []):
            print(f"  • {r.get('label')}")
        return

    if args.cmd == "rpc":
        out = rpc(url, key, args.name, json.loads(args.body), args.time)
        print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
