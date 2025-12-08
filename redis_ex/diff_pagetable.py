#!/usr/bin/env python3
import argparse, gzip, csv, os, sys
def load(path):
    t={}
    op = gzip.open if path.endswith(".gz") else open
    with op(path,'rt') as f:
        rd = csv.DictReader(f)
        for r in rd:
            vpn=int(r["vpn_hex"],16)
            st=r["status"]; pfn=int(r["pfn"]) if r["pfn"] else None
            t[vpn]=(st,pfn)
    return t
def diff(prev,curr,outdir):
    P=load(prev); C=load(curr)
    add=[]; chg=[]; rm=[]
    Pp={v:x for v,x in P.items() if x[0]=="PRESENT"}
    Cp={v:x for v,x in C.items() if x[0]=="PRESENT"}
    for v,(s,p) in Cp.items():
        if v not in Pp: add.append((v,None,p))
        elif Pp[v][1]!=p: chg.append((v,Pp[v][1],p))
    for v,(s,p) in Pp.items():
        if v not in Cp: rm.append((v,p,None))
    os.makedirs(outdir,exist_ok=True)
    bp=lambda x: os.path.basename(x).replace(".csv.gz","")
    bprev, bcurr = bp(prev), bp(curr)
    def dump(name,rows):
        path=os.path.join(outdir,name)
        with open(path,'w') as f:
            f.write("vpn_hex,old_pfn,new_pfn\n")
            for v,op,np in rows:
                f.write(f"{v:016x},{'' if op is None else op},{'' if np is None else np}\n")
        return path
    dump(f"{bprev}__to__{bcurr}.added.csv",add)
    dump(f"{bprev}__to__{bcurr}.changed.csv",chg)
    dump(f"{bprev}__to__{bcurr}.removed.csv",rm)
    with open(os.path.join(outdir,f"{bprev}__to__{bcurr}.summary.txt"),"w") as f:
        f.write(f"added={len(add)} changed={len(chg)} removed={len(rm)}\n")
    print(f"added={len(add)} changed={len(chg)} removed={len(rm)}")
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--prev",required=True); ap.add_argument("--curr",required=True)
    ap.add_argument("--outdir",required=True)
    a=ap.parse_args(); diff(a.prev,a.curr,a.outdir)
