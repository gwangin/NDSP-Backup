#!/usr/bin/env python3
import argparse, subprocess, os

def read_rss_kb(pid):
    for path, key in [(f"/proc/{pid}/smaps_rollup","Rss:"),(f"/proc/{pid}/status","VmRSS:")]:
        try:
            with open(path) as f:
                for ln in f:
                    if ln.startswith(key):
                        return int(ln.split()[1])
        except: pass
    try:
        with open(f"/proc/{pid}/statm") as f:
            parts=f.read().split()
            if len(parts)>=2:
                resident=int(parts[1])
                page_kb=os.sysconf('SC_PAGE_SIZE')//1024
                return resident*page_kb
    except: pass
    return 0

if __name__=="__main__":
    ap=argparse.ArgumentParser()
    ap.add_argument("--prev", required=True)
    ap.add_argument("--curr", required=True)
    ap.add_argument("--pid", required=True, type=int)
    ap.add_argument("--log", required=True)
    ap.add_argument("--rss-kb", type=int, default=None)
    args=ap.parse_args()

    out = subprocess.check_output(
        ["python3", os.path.join(os.path.dirname(__file__),"diff_pagetable.py"),
         "--prev", args.prev, "--curr", args.curr],
        text=True).strip()

    rss_kb = args.rss_kb if args.rss_kb is not None else read_rss_kb(args.pid)
    rss_mib = rss_kb/1024.0
    with open(args.log,"a") as f:
        f.write(f"{out} RSS={rss_mib:.2f}MiB\n")
    print(f"{out} RSS={rss_mib:.2f}MiB")



