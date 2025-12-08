#!/usr/bin/env python3
import argparse, os, struct, gzip

PAGE_SIZE = os.sysconf('SC_PAGE_SIZE')
ENTRY = 8
PFN_MASK = (1<<55) - 1

def read_maps(pid, only_readable=True):
    vmas=[]
    with open(f"/proc/{pid}/maps") as f:
        for line in f:
            addr, perms, *_ = line.split(maxsplit=2)
            if only_readable and 'r' not in perms:
                continue
            s,e = [int(x,16) for x in addr.split('-')]
            if s<e: vmas.append((s,e,line.rstrip()))
    return vmas

def decode(entry):
    present = (entry>>63)&1
    swapped = (entry>>62)&1
    softdirty = (entry>>55)&1
    if present:
        return ("PRESENT", entry & PFN_MASK, softdirty, swapped)
    elif swapped:
        return ("SWAPPED", None, softdirty, swapped)
    else:
        return ("NONPRESENT", None, softdirty, swapped)

def snapshot(pid, out_csv_gz, out_maps_txt=None, all_perms=False):
    vmas = read_maps(pid, only_readable=not all_perms)
    if out_maps_txt:
        with open(out_maps_txt,'w') as mf:
            for *_, line in vmas: mf.write(line+"\n")
    fd = os.open(f"/proc/{pid}/pagemap", os.O_RDONLY)
    try:
        with gzip.open(out_csv_gz,'wt') as gf:
            gf.write("vpn_hex,status,pfn,softdirty,swapped\n")
            for (s,e,_) in vmas:
                for addr in range(s,e,PAGE_SIZE):
                    vpn = addr//PAGE_SIZE
                    off = vpn*ENTRY
                    try:
                        data = os.pread(fd, ENTRY, off)
                        if len(data)!=ENTRY: continue
                        entry = struct.unpack("Q", data)[0]
                        st,pfn,sd,sw = decode(entry)
                        gf.write(f"{vpn:016x},{st},{'' if pfn is None else pfn},{sd},{sw}\n")
                    except OSError:
                        continue
    finally:
        os.close(fd)

if __name__=="__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--out", required=True)
    ap.add_argument("--maps", default=None, help="maps 출력 경로(옵션)")
    ap.add_argument("--all-perms", action="store_true")
    a = ap.parse_args()
    snapshot(a.pid, a.out, out_maps_txt=a.maps, all_perms=a.all_perms)
