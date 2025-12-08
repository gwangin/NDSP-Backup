#!/usr/bin/env python3
import argparse, os, struct, gzip

PAGE_SIZE = os.sysconf('SC_PAGE_SIZE')
ENTRY = 8
PFN_MASK = (1<<55) - 1

def read_maps(pid):
    vmas=[]
    with open(f"/proc/{pid}/maps") as f:
        for line in f:
            addr, perms, _ = line.split(maxsplit=2)
            if 'r' not in perms:
                continue
            s,e = [int(x,16) for x in addr.split('-')]
            if s<e: vmas.append((s,e))
    return vmas

def decode(entry):
    present = (entry>>63)&1
    swapped = (entry>>62)&1
    if present and not swapped:
        return ("PRESENT", entry & PFN_MASK)
    elif swapped:
        return ("SWAPPED", None)
    else:
        return ("NONPRESENT", None)

def snapshot(pid, out_csv_gz):
    vmas = read_maps(pid)
    fd = os.open(f"/proc/{pid}/pagemap", os.O_RDONLY)
    try:
        with gzip.open(out_csv_gz,'wt') as gf:
            gf.write("vpn_hex,status,pfn\n")
            for (s,e) in vmas:
                addr = s
                while addr < e:
                    vpn = addr//PAGE_SIZE
                    off = vpn*ENTRY
                    try:
                        data = os.pread(fd, ENTRY, off)
                        if len(data)!=ENTRY:
                            addr += PAGE_SIZE; continue
                        entry = struct.unpack("Q", data)[0]
                        st,pfn = decode(entry)
                        gf.write(f"{vpn:016x},{st},{'' if pfn is None else pfn}\n")
                    except OSError:
                        pass
                    addr += PAGE_SIZE
    finally:
        os.close(fd)

if __name__=="__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    snapshot(a.pid, a.out)
