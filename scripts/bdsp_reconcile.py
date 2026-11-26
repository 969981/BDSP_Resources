#!/usr/bin/env python3
"""Reconcile every source once; report unresolved objects separately."""
import argparse
import json
from collections import Counter
from pathlib import Path

def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("artifacts", type=Path)
    ap.add_argument("output", type=Path)
    a=ap.parse_args()
    summaries = sorted(a.artifacts.rglob("summary.json"))
    if not summaries: raise SystemExit("no shard summaries")
    seen=set()
    shards=set()
    expected=set()
    shard_counts=set()
    source_status=Counter()
    kinds=Counter()
    object_status=Counter()
    object_types=Counter()
    errors=[]
    for p in summaries:
        s=json.loads(p.read_text())
        if s["shard"] in shards: errors.append("duplicate shard")
        shards.add(s["shard"])
        expected.add(s["expected_total_sources"])
        shard_counts.add(s["shards"])
        count=0
        for line in (p.parent/"sources.jsonl").open(encoding="utf-8"):
            x=json.loads(line)
            if x["source"] in seen: errors.append("duplicate source: "+x["source"])
            seen.add(x["source"])
            source_status[x["status"]]+=1
            kinds[x["kind"]]+=1
            count+=1
        if count != s["processed"]: errors.append("source count mismatch "+str(p))
        for line in (p.parent/"objects.jsonl").open(encoding="utf-8"):
            x=json.loads(line)
            if x["source"] not in seen: errors.append("object has no source: "+x["source"])
            object_status[x["status"]]+=1
            object_types[x["type"]]+=1
    if len(expected)!=1 or len(shard_counts)!=1 or shards!=set(range(next(iter(shard_counts)))):
        errors.append("inconsistent or missing shards")
    if expected!={len(seen)}: errors.append("unique source total mismatch")
    result={"inventory_complete":not errors,"unique_sources":len(seen),"expected_totals":sorted(expected),
            "shards":sorted(shards),"source_status":dict(source_status),"kinds":dict(kinds),
            "object_types":dict(object_types),"object_status":dict(object_status),"errors":errors,
            "fully_decoded":False,
            "note":"Inventory completeness is not full semantic decoding; inspect indexed, unknown, fallback and error statuses."}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(result,indent=2),encoding="utf-8")
    print(json.dumps(result,indent=2))
    if errors or source_status["load_error"]: raise SystemExit(1)

if __name__=="__main__": main()
