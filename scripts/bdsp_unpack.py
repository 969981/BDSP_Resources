#!/usr/bin/env python3
"""Read-only BDSP source audit and Unity extraction. Python 3.11+."""
import argparse
import hashlib
import importlib.metadata
import json
import re
from collections import Counter
from pathlib import Path

SOURCE = Path("1.3.0/5146edd5f9d0579a488ea31d0610e859_NCA")
VERSION = "1.3.0"

def sha_file(p):
    h = hashlib.sha256()
    with p.open("rb") as f:
        for b in iter(lambda: f.read(1024 * 1024), b""):
            h.update(b)
    return h.hexdigest()

def classify(p, head):
    if head.startswith(b"UnityFS\0"): return "UnityFS"
    if head.startswith((b"UnityRaw\0", b"UnityWeb\0")): return "UnityLegacy"
    if head.startswith(b"NSO0"): return "NSO"
    if head.startswith(b"\xaf\x1b\xb1\xfa"): return "IL2CPPMetadata"
    if head.startswith(b"BKHD"): return "WwiseBank"
    if head.startswith(b"RIFF"): return "RIFF"
    if head.startswith(b"CRID"): return "CRI"
    if p.name.endswith(".assets") or p.name in ("globalgamemanagers", "level0", "unity default resources", "unity_builtin_extra"): return "UnitySerializedCandidate"
    if p.name.endswith((".resS", ".resource")): return "UnityStream"
    return "Unknown"

def shard_for(rel, n):
    return int(hashlib.sha256(rel.encode("utf-8")).hexdigest(), 16) % n

def safe(s):
    return re.sub(r"[^A-Za-z0-9_.-]", "_", str(s))[:80].strip(".") or "unnamed"

def emit(f, obj):
    f.write(json.dumps(obj, ensure_ascii=True, default=encode) + "\n")

def encode(v):
    if isinstance(v, (bytes, bytearray, memoryview)):
        return {"bytes_hex": bytes(v).hex()}
    raise TypeError(type(v).__name__)

def dump_obj(reader, source, digest, out, images, raw_fallback):
    typ = reader.type.name
    asset = str(getattr(reader.assets_file, "name", "unknown"))
    pid = reader.path_id
    stem = safe(asset) + "-" + hashlib.sha256(asset.encode()).hexdigest()[:16] + "-" + str(pid)
    base = out / "extracted" / digest / stem
    row = {"source": source, "source_sha256": digest, "serialized_file": asset,
           "path_id": pid, "type": typ, "status": "indexed", "name": None}
    outputs = []
    def record(p):
        outputs.append({"path": p.relative_to(out).as_posix(), "size": p.stat().st_size, "sha256": sha_file(p)})
    try:
        if typ in ("Texture2D", "Sprite") and (images == "all" or (images == "ui" and "/UIs/" in source)):
            data = reader.read()
            row["name"] = str(getattr(data, "m_Name", ""))
            p = base.with_suffix(".png") if "." not in base.name else Path(str(base) + ".png")
            p.parent.mkdir(parents=True, exist_ok=True)
            data.image.save(p)
            from PIL import Image
            with Image.open(p) as im:
                im.verify()
            record(p)
            row["status"] = "validated_png"
        elif typ == "TextAsset":
            data = reader.read()
            row["name"] = str(getattr(data, "m_Name", ""))
            payload = data.m_Script
            if isinstance(payload, str):
                payload = payload.encode("utf-8", "surrogateescape")
            p = Path(str(base) + ".textasset.bin")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(bytes(payload))
            record(p)
            row["status"] = "extracted"
        elif typ in ("MonoBehaviour", "SpriteAtlas", "AssetBundle", "Material", "MonoScript"):
            data = reader.read_typetree()
            row["name"] = str(data.get("m_Name", "")) if isinstance(data, dict) else None
            p = Path(str(base) + ".json")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text(json.dumps(data, ensure_ascii=True, default=encode), encoding="utf-8")
            with p.open(encoding="utf-8") as f:
                json.load(f)
            record(p)
            row["status"] = "parsed_typetree"
        else:
            # Metadata only; do not treat an object inventory as an extraction.
            try:
                row["name"] = str(reader.peek_name() or "")
            except Exception:
                pass
    except Exception as e:
        row["status"] = "decode_error"
        row["error"] = repr(e)
        if raw_fallback and typ in ("MonoBehaviour", "TextAsset", "SpriteAtlas", "AssetBundle", "Material", "MonoScript"):
            try:
                p = Path(str(base) + ".raw")
                p.parent.mkdir(parents=True, exist_ok=True)
                p.write_bytes(reader.get_raw_data())
                record(p)
                row["status"] = "raw_fallback"
            except Exception as raw_error:
                row["raw_error"] = repr(raw_error)
    row["outputs"] = outputs
    return row

def run(args):
    root = args.root.resolve()
    src = root / SOURCE
    out = args.output.resolve()
    if not src.is_dir(): raise SystemExit(f"missing {src}")
    if out == src or src in out.parents or out == root: raise SystemExit("output overlaps source/root")
    if out.exists() and any(out.iterdir()): raise SystemExit("output must be empty; use a new output directory")
    if args.shards < 1 or not 0 <= args.shard < args.shards: raise SystemExit("invalid shard")
    out.mkdir(parents=True, exist_ok=True)
    idx = out / "_index"
    idx.mkdir(exist_ok=True)
    paths = sorted((p for p in src.rglob("*") if p.is_file()), key=lambda p:p.relative_to(root).as_posix())
    selected = [p for p in paths if shard_for(p.relative_to(root).as_posix(), args.shards) == args.shard]
    counts, kinds, object_counts, object_status = Counter(), Counter(), Counter(), Counter()
    unity = None
    if not args.inventory_only:
        import UnityPy as unity
    with (idx / "sources.jsonl").open("w", encoding="utf-8") as sf, (idx / "objects.jsonl").open("w", encoding="utf-8") as of:
        for p in selected:
            rel = p.relative_to(root).as_posix()
            with p.open("rb") as f: head = f.read(64)
            digest = sha_file(p)
            kind = classify(p, head)
            row = {"source":rel, "size":p.stat().st_size, "sha256":digest,
                   "kind":kind, "header_hex":head.hex(), "status":"counted", "object_count":0}
            kinds[kind] += 1
            if unity and kind in ("UnityFS", "UnityLegacy", "UnitySerializedCandidate"):
                try:
                    env = unity.load(str(p))
                    objs = list(env.objects)
                    row["object_count"] = len(objs)
                    row["status"] = "indexed_objects" if objs else "empty_or_unresolved"
                    for reader in objs:
                        obj = dump_obj(reader, rel, digest, out, args.images, args.raw_fallback)
                        object_counts[obj["type"]] += 1
                        object_status[obj["status"]] += 1
                        emit(of, obj)
                    del objs, env
                except Exception as e:
                    row["status"] = "load_error"
                    row["error"] = repr(e)
            counts[row["status"]] += 1
            emit(sf, row)
    summary = {"version":VERSION, "shard":args.shard, "shards":args.shards,
               "expected_total_sources":len(paths), "processed":len(selected),
               "source_status":dict(counts), "kinds":dict(kinds),
               "object_types":dict(object_counts), "object_status":dict(object_status),
               "unitypy_version":importlib.metadata.version("UnityPy") if unity else None,
               "images":args.images, "raw_fallback":args.raw_fallback}
    (idx / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, default=Path("."))
    ap.add_argument("--output", type=Path, required=True)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--images", choices=["none","ui","all"], default="ui")
    ap.add_argument("--inventory-only", action="store_true")
    ap.add_argument("--raw-fallback", action="store_true")
    run(ap.parse_args())

if __name__ == "__main__":
    main()
