#!/usr/bin/env python3
import argparse, gzip, csv
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
def diff(prev,curr):
    P=load(prev); C=load(curr)
    add=chg=rm=0
    Pp={v:x for v,x in P.items() if x[0]=="PRESENT"}
    Cp={v:x for v,x in C.items() if x[0]=="PRESENT"}
    for v,(s,p) in Cp.items():
        if v not in Pp: add+=1
        elif Pp[v][1]!=p: chg+=1
    for v in Pp.keys():
        if v not in Cp: rm+=1
    return add, chg, rm
if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--prev",required=True); ap.add_argument("--curr",required=True)
    a=ap.parse_args()
    A,C,R = diff(a.prev,a.curr)
    print(f"added={A} changed={C} removed={R}")
