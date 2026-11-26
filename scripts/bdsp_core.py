#!/usr/bin/env python3
"""Evidence-preserving joins, read-only query core and native selector candidates."""
import argparse, hashlib, json, re, sqlite3, struct, shutil
from pathlib import Path
from collections import Counter
from bdsp_unpack import SOURCE, sha_file
from bdsp_focus import write_json

def q(db,sql,args=()):
    return db.execute(sql,args).fetchall()

def metadata_images(raw, db):
    b=raw.read_bytes()
    magic,ver,end=struct.unpack_from("<III",b)
    if magic!=0xfab11baf or ver!=24 or not 168<=end<=512 or (end-8)%8: raise ValueError("metadata header")
    sections=[struct.unpack_from("<II",b,i) for i in range(8,end,8)]
    for o,n in sections:
        if n and (o<end or o+n>len(b)): raise ValueError("section bounds")
    so,sn=sections[2]
    def name(i):
        if not 0<=i<sn: raise ValueError("name index")
        e=b.find(b"\0",so+i,so+sn)
        if e<0: raise ValueError("unterminated name")
        return b[so+i:e].decode("utf8")
    types=q(db,"SELECT id,name,namespace,field_start,field_count,method_start,method_count,token FROM metadata_types ORDER BY id")
    # Verify raw definitions independently; locate the exact section by row evidence.
    matches=[]
    for i,(o,n) in enumerate(sections):
        if n!=len(types)*92: continue
        try:
            for j,tn,ns,fs,fc,ms,mc,token in types:
                p=o+j*92
                ni,nsi=struct.unpack_from("<II",b,p)
                f,m=struct.unpack_from("<ii",b,p+36)
                mcount,_,fcount=struct.unpack_from("<3H",b,p+68)
                tok=struct.unpack_from("<I",b,p+88)[0]
                if (name(ni),name(nsi),f,fcount,m,mcount,tok)!=(tn,ns,fs,fc,ms,mc,token): raise ValueError("type row mismatch")
            matches.append(i)
        except (ValueError,UnicodeError,struct.error): pass
    if len(matches)!=1: raise ValueError("raw type table mismatch or ambiguous "+str(matches))
    # Verify method and field rows separately, not just the type table.
    for table,stride,section in [("metadata_fields",12,11),("metadata_methods",32,5)]:
        o,n=sections[section]
        rr=q(db,"SELECT * FROM "+table+" ORDER BY id")
        if n!=len(rr)*stride: raise ValueError(table+" byte count")
        for row in rr:
            p=o+row[0]*stride
            ni=struct.unpack_from("<I",b,p)[0]
            if table=="metadata_fields":
                ti,tok=struct.unpack_from("<iI",b,p+4)
                check=(row[0],name(ni),ti,tok)
            else:
                decl,ret=struct.unpack_from("<ii",b,p+4)
                tok=struct.unpack_from("<I",b,p+20)[0]
                check=(row[0],name(ni),decl,ret,tok)
            if check!=row: raise ValueError(table+" row mismatch "+str(row[0]))
    options=[]
    for i,(o,n) in enumerate(sections):
        if not n or n%40 or n//40>4096: continue
        try:
            images=[]; covered=set(); names=set()
            for j in range(n//40):
                ni,ai,ts,tc,es,ec,ep,tok,ca,cc=struct.unpack_from("<IiiIiIiIiI",b,o+j*40)
                nm=name(ni)
                if not nm.endswith((".dll",".exe")) or nm in names or ai<0 or ai>=n//40 or tok!=1: raise ValueError("invalid image")
                names.add(nm)
                if tc and not 0<=ts<=len(types)-tc: raise ValueError("image range")
                r=set(range(ts,ts+tc)) if tc else set()
                if covered&r: raise ValueError("overlap")
                covered|=r
                images.append((j,nm,ai,ts,tc))
            if len(covered)!=len(types): raise ValueError("coverage")
            options.append((i,images))
        except (ValueError,UnicodeError,struct.error): pass
    if len(options)!=1: raise ValueError("image definition section unresolved "+str([x[0] for x in options]))
    si,images=options[0]
    db.executemany("INSERT INTO metadata_image VALUES (?,?,?,?,?)",images)
    return {"type_section":matches[0],"image_section":si,"images":len(images),"types":len(types),"source_sha256":sha_file(raw)}

def link_objects(db, artifact):
    masters=q(db,"SELECT s.source,s.serialized,s.path_id,s.namespace,s.class,s.assembly,a.name,a.output FROM master_schema s JOIN asset a USING(source,serialized,path_id)")
    for src,serial,pid,ns,cl,asm,nm,output in masters:
        tree=json.loads((artifact/output).read_text(encoding="utf8"))
        ptr=tree.get("m_Script",{})
        fid=ptr.get("m_FileID"); sid=ptr.get("m_PathID")
        script=q(db,"SELECT output FROM asset WHERE source=? AND serialized=? AND path_id=? AND type='MonoScript'",(src,serial,sid)) if fid==0 and isinstance(sid,int) else []
        matches=q(db,"SELECT t.id FROM metadata_types t JOIN metadata_image i ON t.id>=i.type_start AND t.id<i.type_start+i.type_count WHERE t.name=? AND t.namespace=? AND i.name=?",(cl,ns,asm))
        verified=False
        if len(script)==1 and script[0][0]:
            st=json.loads((artifact/script[0][0]).read_text(encoding="utf8"))
            verified=(st.get("m_ClassName"),st.get("m_Namespace"),st.get("m_AssemblyName"))==(cl,ns,asm)
        status="verified" if verified and len(matches)==1 else "unresolved"
        db.execute("INSERT INTO script_link VALUES (?,?,?,?,?,?,?,?,?,?)",(src,serial,pid,fid,sid,ns,cl,asm,matches[0][0] if len(matches)==1 else None,status))
        # Preserve each top-level record with its original ordinal and complete JSON.
        for key,value in tree.items():
            if not isinstance(value,list) or not value or not all(isinstance(v,dict) for v in value): continue
            for idx,row in enumerate(value):
                db.execute("INSERT INTO master_record VALUES (?,?,?,?,?,?,?)",(src,serial,pid,cl,key,idx,json.dumps(row,ensure_ascii=False)))
    db.commit()

def get_records(db,cl,array):
    return [(src,serial,pid,ordinal,json.loads(payload)) for src,serial,pid,ordinal,payload in q(db,"SELECT source,serialized,path_id,ordinal,payload FROM master_record WHERE class=? AND array_name=? ORDER BY ordinal",(cl,array))]

def nso_segments(path):
    import lz4.block
    b=path.read_bytes()
    if b[:4]!=b"NSO0": raise ValueError("NSO magic")
    flags=struct.unpack_from("<I",b,12)[0]
    segments=[]
    for i in range(3):
        off,va,size=struct.unpack_from("<III",b,16+16*i)
        stored=struct.unpack_from("<I",b,0x60+4*i)[0]
        data=b[off:off+(stored if flags&(1<<i) else size)]
        if flags&(1<<i): data=lz4.block.decompress(data,uncompressed_size=size)
        if len(data)!=size: raise ValueError("segment size")
        if flags&(1<<(i+3)) and hashlib.sha256(data).digest()!=b[0xa0+i*32:0xc0+i*32]: raise ValueError("NSO segment hash")
        segments.append((va,data))
    return segments

def native_candidates(path,db,out):
    from capstone import Cs, CS_ARCH_ARM64, CS_MODE_LITTLE_ENDIAN
    seg=nso_segments(path)
    text,ro,data=seg
    def read(va,n):
        for base,b in seg:
            if base<=va and va+n<=base+len(b): return b[va-base:va-base+n]
        raise ValueError("unmapped VA "+hex(va))
    def u64(va): return struct.unpack("<Q",read(va,8))[0]
    reloc={}
    # MOD0 dynamic relocation table, AArch64 relative pointers.
    try:
        mod=text[0]+struct.unpack_from("<i",text[1],4)[0]
        if read(mod,4)!=b"MOD0": raise ValueError("MOD0 signature")
        dyn=mod+struct.unpack("<i",read(mod+4,4))[0]
        tags={}
        for i in range(4096):
            tag,val=struct.unpack("<qQ",read(dyn+i*16,16))
            if tag==0: break
            tags[tag]=val
        if tags.get(9,24)!=24: raise ValueError("RELA stride")
        if 7 in tags and 8 in tags:
            for p in range(tags[7],tags[7]+tags[8],24):
                dst,info,add=struct.unpack("<QQq",read(p,24))
                if info&0xffffffff==1027: reloc[dst]=add
    except (ValueError,struct.error) as e: return {"status":"unresolved_relocations","error":str(e)}
    def ptr(va): return reloc[va] if va in reloc else u64(va)
    def executable(va): return text[0]<=va<text[0]+len(text[1]) and va%4==0
    # Exact assembly name reference and bounded codegen module layout candidate.
    needle=b"Assembly-CSharp.dll\0"
    names=set()
    for base,buf in seg:
        start=0
        while True:
            pos=buf.find(needle,start)
            if pos<0: break
            names.add(base+pos);start=pos+1
    refs={a for a,v in reloc.items() if v in names}
    for base,buf in seg[1:]:
        for n in names:
            pat=struct.pack("<Q",n)
            pos=buf.find(pat)
            while pos>=0:
                if (base+pos)%8==0: refs.add(base+pos)
                pos=buf.find(pat,pos+1)
    methods=q(db,"SELECT t.namespace,t.name,m.name,m.token FROM metadata_methods m JOIN metadata_types t ON m.declaring_type=t.id JOIN metadata_image i ON t.id>=i.type_start AND t.id<i.type_start+i.type_count WHERE i.name='Assembly-CSharp.dll'")
    maxrid=max((t&0xffffff for _,_,_,t in methods),default=0)
    modules=[]
    for a in sorted(refs):
        try:
            count=struct.unpack("<I",read(a+8,4))[0]; table=ptr(a+16)
            if not maxrid or count<maxrid or count>maxrid+1000: continue
            pointers=[ptr(table+8*i) for i in range(count)]
            nonzero=[p for p in pointers if p]
            if not nonzero or sum(executable(p) for p in nonzero)/len(nonzero)<.99: continue
            modules.append((a,count,table,pointers))
        except (ValueError,struct.error): pass
    candidates=[(ns,cl,m,tok) for ns,cl,m,tok in methods if re.search(r"(pokemon|poke|mons|zukan|monster)",cl+" "+m,re.I) and re.search(r"(sprite|icon|texture|assetbundle|assetname|imagename|image|resourcekey)",cl+" "+m,re.I)]
    result={"status":"module_candidate" if len(modules)==1 else "unresolved_module","source_sha256":sha_file(path),"relocations":len(reloc),"name_addresses":[hex(x) for x in sorted(names)],"modules":[[hex(a),n,hex(t)] for a,n,t,_ in modules],"candidate_count":len(candidates)}
    cs=Cs(CS_ARCH_ARM64,CS_MODE_LITTLE_ENDIAN)
    for ns,cl,m,tok in candidates:
        va=None; ins=[]
        if len(modules)==1:
            ps=modules[0][3]; p=ps[(tok&0xffffff)-1]
            if executable(p):
                va=p
                ins=[f"{i.address:#x}: {i.mnemonic} {i.op_str}" for i in cs.disasm(read(p,min(128,text[0]+len(text[1])-p)),p)]
        db.execute("INSERT INTO native_method VALUES (?,?,?,?,?,?,?)",(path.name,ns,cl,m,tok,va,json.dumps(ins)))
    write_json(out/(path.name+"_native.json"),result)
    return result

class BDSPResourceCore:
    def __init__(self,path):
        self.db=sqlite3.connect(Path(path).resolve().as_uri()+"?mode=ro",uri=True)
    def close(self): self.db.close()
    def personal(self,monsno):
        return [json.loads(p) for (p,) in q(self.db,"SELECT payload FROM master_record WHERE class='PersonalTable' AND array_name='Personal' AND json_extract(payload,'$.monsno')=? ORDER BY ordinal",(monsno,))]
    def item(self,no):
        return [json.loads(p) for (p,) in q(self.db,"SELECT payload FROM master_record WHERE class='ItemTable' AND array_name='Item' AND json_extract(payload,'$.no')=? ORDER BY ordinal",(no,))]
    def image_candidates(self,species,field_a=None,field_b=None,field_c=None,kind="dp"):
        filters=["species_candidate=?","kind=?","type='Sprite'","status='validated_png'"]; args=[species,kind]
        for col,val in zip(("field_a","field_b","field_c"),(field_a,field_b,field_c)):
            if val is not None: filters.append(col+"=?");args.append(val)
        return q(self.db,"SELECT source,field_a,field_b,field_c,output,pixel_sha256 FROM image_lookup WHERE "+" AND ".join(filters)+" ORDER BY field_a,field_b,field_c",args)

def main():
    ap=argparse.ArgumentParser();ap.add_argument("--artifact",type=Path,required=True);ap.add_argument("--root",type=Path,default=Path("."));ap.add_argument("--output",type=Path,required=True);a=ap.parse_args()
    out=a.output.resolve()
    if out.exists() and any(out.iterdir()): raise SystemExit("output must be empty")
    src=(a.root/SOURCE).resolve()
    if src==out or src in out.parents: raise SystemExit("source is read-only")
    out.mkdir(parents=True,exist_ok=True)
    art=a.artifact.resolve()
    dbpath=out/"bdsp-core.sqlite";shutil.copy2(art/"bdsp.sqlite",dbpath);db=sqlite3.connect(dbpath)
    db.executescript("""
    CREATE TABLE metadata_image(id INTEGER PRIMARY KEY,name TEXT UNIQUE,assembly_index INT,type_start INT,type_count INT);
    CREATE TABLE script_link(source TEXT,serialized TEXT,path_id INT,script_file_id INT,script_path_id INT,namespace TEXT,class TEXT,assembly TEXT,metadata_id INT,status TEXT,PRIMARY KEY(source,serialized,path_id));
    CREATE TABLE master_record(source TEXT,serialized TEXT,path_id INT,class TEXT,array_name TEXT,ordinal INT,payload TEXT,PRIMARY KEY(source,serialized,path_id,array_name,ordinal));
    CREATE TABLE native_method(binary TEXT,namespace TEXT,class TEXT,method TEXT,token INT,va INT,instructions_json TEXT);
    """)
    try: metadata=metadata_images(src/"1/Data/Managed/Metadata/global-metadata.dat",db)
    except (ValueError,struct.error) as e: metadata={"status":"unresolved","error":str(e)}
    link_objects(db,art)
    add=get_records(db,"AddPersonalTable","AddPersonal")
    personal=get_records(db,"PersonalTable","Personal")
    dp=q(db,"SELECT species_candidate,field_a,field_b FROM image_key WHERE kind='dp' GROUP BY 1,2,3")
    pairs=Counter((x[4]["monsno"],x[4]["formno"]) for x in add)
    dp_pairs=Counter((s,f) for s,f,g in dp)
    comparison={"add_rows":len(add),"personal_rows":len(personal),"dp_keys":len(dp),"equal_pair_multiset":pairs==dp_pairs,"add_only":[[*k,n] for k,n in sorted((pairs-dp_pairs).items())],"dp_only":[[*k,n] for k,n in sorted((dp_pairs-pairs).items())]}
    write_json(out/"addpersonal_image_comparison.json",comparison)
    native={}
    for n in ("main","shiny_pearl_main"):
        try: native[n]=native_candidates(src/"0"/n,db,out)
        except Exception as e: native[n]={"status":"unresolved","error":repr(e)}
    db.commit()
    summary={"metadata":metadata,"script_links":q(db,"SELECT status,count(*) FROM script_link GROUP BY status"),"link_by_source":q(db,"SELECT source,status,count(*) FROM script_link GROUP BY source,status"),"master_records":q(db,"SELECT class,array_name,count(*) FROM master_record GROUP BY class,array_name"),"addpersonal_comparison":comparison,"native":native,"native_method_sample":q(db,"SELECT binary,namespace,class,method,token,va FROM native_method WHERE va IS NOT NULL LIMIT 40"),"native_selector_verified":False}
    write_json(out/"core_summary.json",summary)
    print(json.dumps({k:v for k,v in summary.items() if k!="master_records"},ensure_ascii=False,indent=2))
    print("master record samples",summary["master_records"][:40])
    db.close()
    core=BDSPResourceCore(dbpath)
    assert core.personal(1) and core.item(1) and core.image_candidates(1,0,0,0)
    core.close()
    if metadata.get("status")=="unresolved" or any(s!="verified" for s,_ in summary["script_links"]): raise SystemExit(1)

if __name__=="__main__":main()
