#!/usr/bin/env python3
"""Trace native image selection and reconcile data/filename keys without guessing semantics."""
import argparse, bisect, collections, hashlib, json, re, sqlite3, struct
from pathlib import Path
from bdsp_unpack import SOURCE, sha_file
from bdsp_focus import write_json
from bdsp_core import nso_segments, q

def reconcile(db,out):
    add=q(db,"SELECT ordinal,payload FROM master_record WHERE class='AddPersonalTable' AND array_name='AddPersonal' ORDER BY ordinal")
    dp=q(db,"SELECT species_candidate,field_a,field_b FROM image_key WHERE kind='dp' GROUP BY 1,2,3 ORDER BY 1,2,3")
    p=q(db,"SELECT ordinal,payload FROM master_record WHERE class='PersonalTable' AND array_name='Personal' ORDER BY ordinal")
    personal=collections.defaultdict(list); ar=collections.defaultdict(list); keys=collections.defaultdict(list)
    for i,r in p:
        r=json.loads(r); personal[r["monsno"]].append({"ordinal":i,**r})
    for i,r in add:
        r=json.loads(r); ar[r["monsno"]].append({"ordinal":i,**r})
    for s,a,b in dp: keys[s].append([a,b])
    records=[]
    for s in sorted(set(ar)|set(keys)|set(personal)):
        a=ar[s]; k=keys[s]
        ac=collections.Counter(x["formno"] for x in a)
        kc=collections.Counter(x[0] for x in k)
        records.append({"species":s,"personal":personal[s],"addpersonal":a,"image_keys":k,
            "direct_pair_overlap":sum((ac&kc).values()),"add_only":dict(ac-kc),"image_only":dict(kc-ac),
            "classification":"count_only_match" if len(a)==len(k) and ac!=kc else "direct_pair_multiset" if ac==kc else "different_counts"})
    write_json(out/"species_reconciliation.json",records)
    # Find real resource-key fields, including nested master tables.
    pat=re.compile(r"(?:^|/)pm\d{4}_\d{2}_\d{2}_\d{2}_(?:dp|l)(?:$|\.)",re.I)
    hits=[]; field_counts=collections.Counter()
    for cl,arr,src,ser,pid,idx,payload in q(db,"SELECT class,array_name,source,serialized,path_id,ordinal,payload FROM master_record WHERE source LIKE 'Pml/%' OR source LIKE 'Dpr/%' OR source LIKE 'UIs/%'"):
        def visit(v,path):
            if isinstance(v,dict):
                for k,x in v.items(): visit(x,path+"/"+k)
            elif isinstance(v,list):
                for i,x in enumerate(v): visit(x,path+"/"+str(i))
            elif isinstance(v,str) and pat.search(v):
                hits.append({"class":cl,"array":arr,"source":src,"serialized":ser,"path_id":pid,"ordinal":idx,"field":path,"value":v})
                field_counts[(cl,path)]+=1
        visit(json.loads(payload),"")
    write_json(out/"master_image_key_hits.json",hits)
    return {"species_groups":len(records),"direct_pair_overlap":sum(r["direct_pair_overlap"] for r in records),"classifications":dict(collections.Counter(r["classification"] for r in records)),"key_hits":len(hits),"key_fields":[[*k,n] for k,n in field_counts.items()],"examples":[r for r in records if r["species"] in (3,25,201,386,479,493)]}

def literals(path,out):
    b=path.read_bytes()
    magic,ver=struct.unpack_from("<II",b)
    if magic!=0xfab11baf or ver!=24: raise ValueError("unexpected metadata")
    off,n,data,ds=struct.unpack_from("<IIII",b,8)
    if n%8 or off+n>len(b) or data+ds>len(b): raise ValueError("bad literal bounds")
    hits=[]
    for i in range(n//8):
        size,idx=struct.unpack_from("<Ii",b,off+i*8)
        if idx<0 or idx+size>ds: raise ValueError("bad literal")
        s=b[data+idx:data+idx+size].decode("utf8",errors="replace")
        if re.search(r"pokemon_(dp|l)|textures_mass|pm\{[0-9]|pm%[0-9]|pokemonicon|monsicon",s,re.I):
            hits.append({"literal_index":i,"file_offset":data+idx,"value":s})
    write_json(out/"metadata_image_literals.json",hits)
    return hits

def trace(path,db,previous,out):
    from capstone import Cs,CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN
    if previous["status"]!="module_candidate" or len(previous["modules"])!=1 or sha_file(path)!=previous["source_sha256"]: raise ValueError("previous module evidence mismatch")
    module,count,table=previous["modules"][0]; module=int(module,16);table=int(table,16)
    seg=nso_segments(path); base,code=seg[0]; limit=base+len(code)
    def read(a,n):
        for va,b in seg:
            if va<=a and a+n<=va+len(b): return b[a-va:a-va+n]
        raise ValueError("unmapped "+hex(a))
    def u64(a):return struct.unpack("<Q",read(a,8))[0]
    mod=base+struct.unpack_from("<i",code,4)[0]
    if read(mod,4)!=b"MOD0": raise ValueError("MOD0")
    dyn=mod+struct.unpack("<i",read(mod+4,4))[0]; tags={}
    for i in range(4096):
        t,v=struct.unpack("<qQ",read(dyn+i*16,16))
        if not t: break
        tags[t]=v
    if tags.get(9,24)!=24: raise ValueError("RELA stride")
    reloc={}
    for a in range(tags[7],tags[7]+tags[8],24):
        dst,info,add=struct.unpack("<QQq",read(a,24))
        if info&0xffffffff==1027:reloc[dst]=add
    def ptr(a):return reloc[a] if a in reloc else u64(a)
    def executable(a):return base<=a<limit and a%4==0
    if ptr(module+16)!=table or struct.unpack("<I",read(module+8,4))[0]!=count or read(ptr(module),20)!=b"Assembly-CSharp.dll\0": raise ValueError("module changed")
    slots=[ptr(table+i*8) for i in range(count)]
    methodrows=q(db,"SELECT t.namespace,t.name,m.name,m.token,m.id FROM metadata_methods m JOIN metadata_types t ON m.declaring_type=t.id JOIN metadata_image i ON t.id>=i.type_start AND t.id<i.type_start+i.type_count WHERE i.name='Assembly-CSharp.dll'")
    names=collections.defaultdict(list)
    allmethods=[]
    for ns,cl,m,tok,mid in methodrows:
        rid=(tok&0xffffff)
        if not 1<=rid<=count:raise ValueError("RID outside module")
        va=slots[rid-1]
        entry={"namespace":ns,"class":cl,"method":m,"token":tok,"id":mid,"va":va if executable(va) else None}
        allmethods.append(entry)
        if executable(va): names[va].append(entry)
    write_json(out/(path.name+"_method_map.json"),allmethods)
    starts=sorted({p for p in slots if executable(p)})
    def label(a):
        return [f"{x['namespace']}.{x['class']}::{x['method']} [0x{x['token']:08x}]" for x in names.get(a,[])]
    def end(a):
        i=bisect.bisect_right(starts,a)
        return starts[i] if i<len(starts) else limit
    def priority(e):
        cl,m=e["class"],e["method"]
        if cl in ("PokemonIcon","MonsIconData","PokemonIDDataInfo") or m in ("GetPokemonAssetbundleName","GetBattlePokemonAssetbundleName","LoadMonsIconSpr"):return True
        return bool(re.search(r"(pokemon|mons|poke|zukan)",cl+" "+m,re.I) and re.search(r"(assetbundle|assetname|imagename|iconname|spritepath|texturepath|formno|sex|gender|shiny|color)",m,re.I))
    seeds={e["va"] for e in allmethods if e["va"] is not None and priority(e)}
    cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    def direct_target(w,pc):
        if w&0x7c000000!=0x14000000:return None
        x=w&0x03ffffff
        if x&0x02000000:x-=0x04000000
        return pc+x*4
    # One pass: all direct BL/B references to seed starts, independent of method names.
    incoming=collections.defaultdict(list)
    for i,(w,) in enumerate(struct.iter_unpack("<I",code[:len(code)//4*4])):
        if w&0x7c000000!=0x14000000:continue
        pc=base+i*4;t=direct_target(w,pc)
        if t in seeds:
            j=bisect.bisect_right(starts,pc)-1;owner=starts[j] if j>=0 else None
            incoming[t].append({"pc":pc,"kind":"bl" if w&0x80000000 else "b","owner_start_candidate":owner,"owner_names":label(owner)})
    traces=[]
    for va in sorted(seeds):
        bound=end(va); stop=min(bound,va+8192)
        raw=read(va,stop-va); instructions=[]; calls=[]
        for i in cs.disasm(raw,va):
            instructions.append(f"{i.address:#x}: {i.mnemonic} {i.op_str}")
            w=struct.unpack("<I",bytes(i.bytes))[0];t=direct_target(w,i.address)
            if t is not None and (i.mnemonic=="bl" or not va<=t<stop):
                calls.append({"pc":i.address,"kind":i.mnemonic,"target":t,"names":label(t)})
        traces.append({"va":va,"names":label(va),"next_known_start":bound,"window_end":stop,"window_truncated":stop<bound,"instructions":instructions,"direct_edges":calls,"incoming_edges":incoming[va],"boundary_status":"next_module_method_start_candidate_not_function_proof"})
    write_json(out/(path.name+"_selector_trace.json"),traces)
    return {"binary":path.name,"module":hex(module),"method_table":hex(table),"slots":count,"metadata_methods":len(allmethods),"mapped_methods":sum(e["va"] is not None for e in allmethods),"unique_starts":len(starts),"selector_seeds":len(seeds),"direct_incoming_edges":sum(map(len,incoming.values())),"examples":[{"va":hex(x["va"]),"names":x["names"],"calls":[{"pc":hex(c["pc"]),"target":hex(c["target"]),"names":c["names"]} for c in x["direct_edges"] if c["names"]][:12]} for x in traces if any("PokemonIcon::Load " in n or "GetPokemonAssetbundleName" in n or "GetMonsIconSprByFormNo" in n for n in x["names"])]}

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--artifact",type=Path,required=True);ap.add_argument("--output",type=Path,required=True);ap.add_argument("--root",type=Path,default=Path("."));a=ap.parse_args()
    out=a.output.resolve();src=(a.root/SOURCE).resolve()
    if src==out or src in out.parents or (out.exists() and any(out.iterdir())):raise SystemExit("unsafe output")
    out.mkdir(parents=True,exist_ok=True)
    db=sqlite3.connect((a.artifact/"bdsp-core.sqlite").resolve().as_uri()+"?mode=ro",uri=True)
    summary=json.loads((a.artifact/"core_summary.json").read_text())
    if summary["script_links"]!=[["verified",2443]]:raise ValueError("prior link verification missing")
    diff=reconcile(db,out); lit=literals(src/"1/Data/Managed/Metadata/global-metadata.dat",out)
    native=[trace(src/"0"/n,db,summary["native"][n],out) for n in ("main","shiny_pearl_main")]
    result={"reconciliation":diff,"literal_hits":lit,"native":native,"native_selector_verified":False}
    write_json(out/"selector_summary.json",result)
    print(json.dumps({"reconciliation":{k:v for k,v in diff.items() if k!="examples"},"literal_hits":lit[:40],"native":native,"native_selector_verified":False},ensure_ascii=False,indent=2))
    db.close()
if __name__=="__main__":main()
