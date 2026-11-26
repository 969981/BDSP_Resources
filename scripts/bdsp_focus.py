#!/usr/bin/env python3
"""Focused BDSP tables, named sprite keys, metadata definitions; no invented IDs."""
import argparse
import hashlib
import json
import re
import sqlite3
import struct
from collections import Counter
from pathlib import Path
from bdsp_unpack import SOURCE, sha_file, encode

KEY=re.compile(r"pm(\d{4})_(\d{2})_(\d{2})_(\d{2})_(dp|l)$")
TARGETS=["Pml/personal_masterdatas","Dpr/masterdatas","UIs/masterdatas/uimasterdatas"]
def parse_key(name):
    m=KEY.fullmatch(name)
    if not m: raise ValueError(name)
    return (*map(int,m.groups()[:4]),m.group(5))
def write_json(p,v):
    p.parent.mkdir(parents=True,exist_ok=True)
    p.write_text(json.dumps(v,ensure_ascii=True,default=encode,indent=2),encoding="utf8")
def rows(db,sql):
    return db.execute(sql).fetchall()
def parse_metadata(p, db, out):
    b=p.read_bytes()
    magic,version=struct.unpack_from("<II",b)
    if magic!=0xfab11baf: raise ValueError("metadata magic")
    if version not in (24,27,29): raise ValueError("unsupported metadata version "+str(version))
    end=struct.unpack_from("<I",b,8)[0]
    if not 168<=end<=512 or (end-8)%8: raise ValueError("bad header span")
    sections=[struct.unpack_from("<II",b,i) for i in range(8,end,8)]
    for off,n in sections:
        if n and (off<end or off+n>len(b)): raise ValueError("bad section bounds")
    so,sn=sections[2]
    strings=b[so:so+sn]
    def name(i):
        if not 0<=i<len(strings): raise ValueError("bad string index")
        e=strings.find(b"\0",i)
        if e<0: raise ValueError("unterminated name")
        return strings[i:e].decode("utf8")
    fo,fn=sections[11]
    mo,mn=sections[5]
    to,tn=sections[19]
    # Layout candidates from IL2CPP metadata structures. All rows validated;
    # v24 header alone cannot distinguish its subversions.
    candidates={24:[("24.0",104,48,16),("24.1",100,48,12),("24.2-24.5",92,32,12)],
                27:[("27",88,32,12)],29:[("29",88,32,12)]}[version]
    valid=[]
    rejected={}
    for label,ts,ms,fs in candidates:
        try:
            # v24.0 methods contain customAttributeIndex; v24.1 does not.
            if label=="24.0": ms=56
            if label=="24.1": ms=52
            if fn%fs or mn%ms or tn%ts: raise ValueError("nonintegral table")
            fields=[]; methods=[]; types=[]
            for i in range(fn//fs):
                o=fo+i*fs
                ni,ti=struct.unpack_from("<Ii",b,o)
                token=struct.unpack_from("<I",b,o+fs-4)[0]
                if token>>24!=4 or ti<0: raise ValueError("invalid field token/type")
                fields.append((i,name(ni),ti,token))
            for i in range(mn//ms):
                o=mo+i*ms
                ni,decl,ret=struct.unpack_from("<Iii",b,o)
                token=struct.unpack_from("<I",b,o+ms-12)[0]
                if token>>24!=6 or not 0<=decl<tn//ts or ret<0: raise ValueError("invalid method token/owner")
                methods.append((i,name(ni),decl,ret,token))
            owned_fields=set(); owned_methods=set()
            for i in range(tn//ts):
                o=to+i*ts
                ni,nsi=struct.unpack_from("<II",b,o)
                # Common tail: fieldStart through interfaceOffsetsStart, 8 counts, bitfield, token.
                fst,mst=struct.unpack_from("<ii",b,o+ts-56)
                mc,pc,fc,ec=struct.unpack_from("<4H",b,o+ts-24)
                token=struct.unpack_from("<I",b,o+ts-4)[0]
                if token>>24!=2: raise ValueError("invalid type token")
                if (fc and not 0<=fst<=len(fields)-fc) or (mc and not 0<=mst<=len(methods)-mc): raise ValueError("bad owner span")
                if fc:
                    rr=set(range(fst,fst+fc))
                    if rr&owned_fields: raise ValueError("overlap fields")
                    owned_fields.update(rr)
                if mc:
                    rr=set(range(mst,mst+mc))
                    if rr&owned_methods or any(methods[j][2]!=i for j in rr): raise ValueError("wrong method owner")
                    owned_methods.update(rr)
                types.append((i,name(ni),name(nsi),fst,fc,mst,mc,token))
            if len(owned_fields)!=len(fields) or len(owned_methods)!=len(methods): raise ValueError("incomplete ownership")
            valid.append((label,types,fields,methods))
        except (ValueError,UnicodeError,struct.error) as e: rejected[label]=str(e)
    result={"metadata_sha256":sha_file(p),"version":version,"sections":sections,"rejected":rejected,"valid_layouts":[v[0] for v in valid]}
    if len(valid)==1:
        label,types,fields,methods=valid[0]
        db.executemany("INSERT INTO metadata_types VALUES (?,?,?,?,?,?,?,?)",types)
        db.executemany("INSERT INTO metadata_fields VALUES (?,?,?,?)",fields)
        db.executemany("INSERT INTO metadata_methods VALUES (?,?,?,?,?)",methods)
        result.update(status="validated_definitions",layout=label,types=len(types),fields=len(fields),methods=len(methods))
    else:
        result["status"]="unresolved_layout"
    write_json(out/"metadata_summary.json",result)
    return result
def scalar(v):
    if isinstance(v,(str,int,float,bool)) or v is None: return v
    return str(v)
def main():
    ap=argparse.ArgumentParser()
    ap.add_argument("--root",type=Path,default=Path("."))
    ap.add_argument("--output",type=Path,required=True)
    a=ap.parse_args()
    out=a.output.resolve()
    source=(a.root/SOURCE/"1/Data").resolve()
    if source in out.parents or source==out or (out.exists() and any(out.iterdir())): raise SystemExit("output must be empty and outside source")
    out.mkdir(parents=True,exist_ok=True)
    aa=source/"StreamingAssets/AssetAssistant"
    import UnityPy
    from PIL import Image
    db=sqlite3.connect(out/"bdsp.sqlite")
    db.executescript("""
    CREATE TABLE metadata_types(id INTEGER PRIMARY KEY,name TEXT,namespace TEXT,field_start INT,field_count INT,method_start INT,method_count INT,token INT);
    CREATE TABLE metadata_fields(id INTEGER PRIMARY KEY,name TEXT,type_index INT,token INT);
    CREATE TABLE metadata_methods(id INTEGER PRIMARY KEY,name TEXT,declaring_type INT,return_type_index INT,token INT);
    CREATE TABLE source(path TEXT PRIMARY KEY,sha256 TEXT,size INTEGER,kind TEXT,status TEXT);
    CREATE TABLE asset(source TEXT,serialized TEXT,path_id INTEGER,type TEXT,name TEXT,status TEXT,output TEXT,sha256 TEXT,detail TEXT, PRIMARY KEY(source,serialized,path_id));
    CREATE TABLE image_key(source TEXT PRIMARY KEY,species_candidate INT,field_a INT,field_b INT,field_c INT,kind TEXT);
    CREATE TABLE image_pixel(source TEXT,serialized TEXT,path_id INT,width INT,height INT,pixel_sha256 TEXT,alpha_min INT,alpha_max INT,PRIMARY KEY(source,serialized,path_id));
    CREATE TABLE master_schema(source TEXT,serialized TEXT,path_id INT,namespace TEXT,class TEXT,assembly TEXT,fields_json TEXT,metadata_matches_json TEXT);
    CREATE TABLE master_array(source TEXT,serialized TEXT,path_id INT,field_path TEXT,length INT,row_keys_json TEXT);
    """)
    metadata=parse_metadata(source/"Managed/Metadata/global-metadata.dat",db,out)
    targets=[(aa/x,"master") for x in TARGETS]
    targets += [(p,"message") for p in sorted((aa/"Message").iterdir()) if p.is_file()]
    for group in ("pokemon_dp","pokemon_l"):
        targets += [(p,"image") for p in sorted((aa/"UIs/textures_mass"/group).iterdir()) if p.is_file()]
    counts=Counter(); per_source=Counter(); keys=Counter(); errors=[]
    for p,kind in targets:
        rel=p.relative_to(aa).as_posix()
        if kind=="image":
            key=parse_key(p.name)
            db.execute("INSERT INTO image_key VALUES (?,?,?,?,?,?)",(rel,*key))
            keys[key[-1]]+=1
        digest=sha_file(p)
        try:
            env=UnityPy.load(str(p))
            objs=list(env.objects)
            if not objs: raise ValueError("empty object list")
            src_status="indexed"
            for obj in objs:
                typ=obj.type.name
                serial=obj.assets_file.name
                pid=obj.path_id
                name=""; status="indexed"; file=None; sha=None; detail={}
                ident=hashlib.sha256((rel+"\0"+serial+"\0"+str(pid)).encode()).hexdigest()
                try:
                    name=str(obj.peek_name() or "")
                except Exception: pass
                try:
                    if kind=="image" and typ in ("Sprite","Texture2D"):
                        data=obj.read()
                        name=str(data.m_Name)
                        im=data.image.convert("RGBA")
                        w,h=im.size
                        pixel=hashlib.sha256(struct.pack("<II",w,h)+im.tobytes()).hexdigest()
                        file=out/"images"/key[-1]/p.name/(ident+".png")
                        file.parent.mkdir(parents=True,exist_ok=True)
                        im.save(file)
                        with Image.open(file) as check:
                            check.load()
                            if check.convert("RGBA").tobytes()!=im.tobytes(): raise ValueError("PNG roundtrip mismatch")
                        db.execute("INSERT INTO image_pixel VALUES (?,?,?,?,?,?,?,?)",(rel,serial,pid,w,h,pixel,*im.getchannel("A").getextrema()))
                        status="validated_png"
                    elif kind!="image" and typ in ("MonoBehaviour","TextAsset","MonoScript","AssetBundle","SpriteAtlas"):
                        tree=obj.read_typetree()
                        name=str(tree.get("m_Name",name))
                        file=out/"tables"/rel/(ident+".json")
                        write_json(file,tree)
                        status="parsed_typetree"
                        if typ=="MonoBehaviour":
                            ns=cl=assembly=""
                            try:
                                sc=obj.read().m_Script.read()
                                ns=str(sc.m_Namespace); cl=str(sc.m_ClassName); assembly=str(sc.m_AssemblyName)
                            except Exception as e: detail["script_error"]=repr(e)
                            matches=db.execute("SELECT id FROM metadata_types WHERE namespace=? AND name=?",(ns,cl)).fetchall() if cl else []
                            db.execute("INSERT INTO master_schema VALUES (?,?,?,?,?,?,?,?)",(rel,serial,pid,ns,cl,assembly,json.dumps(list(tree)),json.dumps(matches)))
                            def visit(v,path):
                                if isinstance(v,list):
                                    cols=sorted({str(k) for x in v if isinstance(x,dict) for k in x})
                                    db.execute("INSERT INTO master_array VALUES (?,?,?,?,?,?)",(rel,serial,pid,path,len(v),json.dumps(cols)))
                                    # Recurse only into lists with nested arrays/dicts, retaining indices.
                                    for i,x in enumerate(v):
                                        if isinstance(x,(dict,list)): visit(x,path+"["+str(i)+"]")
                                elif isinstance(v,dict):
                                    for k,x in v.items():
                                        if isinstance(x,(dict,list)): visit(x,path+"/"+str(k))
                            visit(tree,"")
                    if file: sha=sha_file(file)
                except Exception as e:
                    status="decode_error"; detail["error"]=repr(e)
                    if kind!="image" and typ in ("MonoBehaviour","TextAsset","MonoScript","AssetBundle","SpriteAtlas"):
                        try:
                            file=out/"tables"/rel/(ident+".raw")
                            file.parent.mkdir(parents=True,exist_ok=True)
                            file.write_bytes(obj.get_raw_data()); sha=sha_file(file); status="raw_fallback"
                        except Exception as e2: detail["raw_error"]=repr(e2)
                    if status=="decode_error": file=None;sha=None
                db.execute("INSERT INTO asset VALUES (?,?,?,?,?,?,?,?,?)",(rel,serial,pid,typ,name,status,file.relative_to(out).as_posix() if file else None,sha,json.dumps(detail)))
                counts[(kind,typ,status)]+=1
                per_source[(rel,status)]+=1
            del objs,env
        except Exception as e:
            src_status="load_error";errors.append({"source":rel,"error":repr(e)})
        db.execute("INSERT INTO source VALUES (?,?,?,?,?)",(rel,digest,p.stat().st_size,kind,src_status))
        db.commit()
    db.executescript("""
    CREATE VIEW image_lookup AS SELECT k.*,a.serialized,a.path_id,a.type,a.name,a.status,a.output,p.width,p.height,p.pixel_sha256,p.alpha_min,p.alpha_max FROM image_key k JOIN asset a ON k.source=a.source LEFT JOIN image_pixel p USING(source,serialized,path_id) WHERE a.type IN ('Texture2D','Sprite');
    CREATE VIEW metadata_type_fields AS SELECT t.namespace,t.name AS class_name,f.* FROM metadata_types t JOIN metadata_fields f ON f.id>=t.field_start AND f.id<t.field_start+t.field_count;
    """)
    db.commit()
    expected={"dp":1302,"l":542}
    groups=rows(db,"SELECT kind,count(*),count(DISTINCT species_candidate),sum(field_c=0),sum(field_c=1) FROM image_key GROUP BY kind")
    summary={"metadata":metadata,"target_sources":len(targets),"image_key_counts":dict(keys),"expected_image_keys":expected,
             "image_groups":groups,"image_sources_with_png":rows(db,"SELECT kind,count(DISTINCT source) FROM image_lookup WHERE status='validated_png' GROUP BY kind"),
             "image_sources_without_png":rows(db,"SELECT source FROM image_key WHERE source NOT IN (SELECT source FROM image_pixel)"),
             "image_distinct_pixel_hashes":rows(db,"SELECT kind,count(DISTINCT pixel_sha256) FROM image_lookup GROUP BY kind"),
             "object_counts":[[*k,v] for k,v in sorted(counts.items())],
             "master_schemas":rows(db,"SELECT source,class,namespace,assembly,metadata_matches_json FROM master_schema WHERE source IN ('Pml/personal_masterdatas','Dpr/masterdatas','UIs/masterdatas/uimasterdatas')"),
             "master_top_arrays":rows(db,"SELECT source,field_path,length,row_keys_json FROM master_array WHERE source IN ('Pml/personal_masterdatas','Dpr/masterdatas','UIs/masterdatas/uimasterdatas') AND instr(field_path,'[')=0"),
             "load_errors":errors,
             "semantic_mapping":"filename candidates only; runtime selector unverified"}
    write_json(out/"summary.json",summary)
    # Bounded log for review; full details in artifact.
    print(json.dumps({k:v for k,v in summary.items() if k not in ("master_schemas","master_top_arrays","image_sources_without_png")},indent=2))
    print("master schema counts",rows(db,"SELECT source,count(*),sum(metadata_matches_json!='[]') FROM master_schema GROUP BY source"))
    print("master schema sample",summary["master_schemas"][:30])
    print("master array sample",summary["master_top_arrays"][:30])
    print("missing PNG sources",len(summary["image_sources_without_png"]))
    db.close()
    if errors or dict(keys)!=expected or metadata["status"]!="validated_definitions": raise SystemExit(1)
if __name__=="__main__": main()
