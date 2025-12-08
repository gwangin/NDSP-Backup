#!/usr/bin/env python3
import os, sys, glob, subprocess

BASE = os.path.dirname(__file__)
SNAPDIR = os.path.join(BASE, "snapshots")
DIFFDIR = os.path.join(BASE, "diffs")
LIVE_DIR = os.path.join(DIFFDIR, "live")
STREAM_CSV = os.path.join(DIFFDIR, "stream_summary.csv")
TOTALS_TXT = os.path.join(DIFFDIR, "stream_totals.txt")
START_EPOCH_FILE = os.path.join(BASE, "start_epoch")
CAP_INTERVAL_FILE = os.path.join(BASE, "capture_interval")
PIDFILE = os.path.join(BASE, "redis.pid")

def last_two_snaps():
    snaps = sorted(glob.glob(os.path.join(SNAPDIR, "pt_*.csv.gz")))
    if len(snaps) < 2: return None, None
    return snaps[-2], snaps[-1]

def parse_summary(path):
    with open(path, 'r') as f:
        line = f.read().strip()
    toks = line.replace("added=","").replace("changed="," ").replace("removed="," ").split()
    return int(toks[0]), int(toks[1]), int(toks[2])

def read_totals():
    if not os.path.exists(TOTALS_TXT): return 0,0,0
    with open(TOTALS_TXT,'r') as f: line=f.read().strip()
    if not line: return 0,0,0
    vals={}
    for token in line.split():
        if '=' in token:
            k,v=token.split('=',1)
            try: vals[k]=int(v)
            except: pass
    return vals.get('added',0), vals.get('changed',0), vals.get('removed',0)

def write_totals(A,C,R):
    with open(TOTALS_TXT,'w') as f:
        f.write(f"TOTAL added={A} changed={C} removed={R}\n")

def get_epoch_from_snap(path):
    b=os.path.basename(path)
    return int(b[len("pt_"):-len(".csv.gz")])

def read_start_and_interval():
    try:
        with open(START_EPOCH_FILE) as f: start=int(f.read().strip())
    except: start=None
    try:
        with open(CAP_INTERVAL_FILE) as f:
            step=int(f.read().strip()); 
            if step<=0: step=5
    except: step=5
    return start, step

def quantize_offset(epoch, start, step):
    if start is None or epoch < start: return 0
    delta = epoch - start
    return (delta // step) * step

def read_rss_kb(pid):
    try:
        with open(f"/proc/{pid}/smaps_rollup") as f:
            for line in f:
                if line.startswith("Rss:"):
                    return int(line.split()[1])
    except: pass
    try:
        with open(f"/proc/{pid}/status") as f:
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1])
    except: pass
    try:
        with open(f"/proc/{pid}/statm") as f:
            parts=f.read().split()
            if len(parts)>=2:
                resident=int(parts[1])
                page_size=os.sysconf('SC_PAGE_SIZE')//1024
                return resident*page_size
    except: pass
    return 0

def mib(kb): return kb/1024.0

def append_csv_row(t_prev_s, t_curr_s, prev, curr, interval_s, a,c,r, A,C,R, rss_kb):
    header = ("t_prev_s,t_curr_s,prev_snap,curr_snap,interval_s,"
              "added,changed,removed,cum_added,cum_changed,cum_removed,"
              "rss_kb,rss_mib\n")
    need_header = not os.path.exists(STREAM_CSV) or os.path.getsize(STREAM_CSV)==0
    with open(STREAM_CSV,'a') as f:
        if need_header: f.write(header)
        f.write(f"{t_prev_s},{t_curr_s},{os.path.basename(prev)},{os.path.basename(curr)},"
                f"{interval_s},{a},{c},{r},{A},{C},{R},{rss_kb},{mib(rss_kb):.2f}\n")

def ensure_pair_diff(prev, curr):
    os.makedirs(LIVE_DIR, exist_ok=True)
    bprev = os.path.basename(prev).replace(".csv.gz","")
    bcurr = os.path.basename(curr).replace(".csv.gz","")
    summary = os.path.join(LIVE_DIR, f"{bprev}__to__{bcurr}.summary.txt")
    if not os.path.exists(summary):
        # suppress stdout/stderr from diff_pagetable.py to avoid duplicate log lines
        subprocess.run(
            [sys.executable, os.path.join(BASE,"diff_pagetable.py"),
             "--prev", prev, "--curr", curr, "--outdir", LIVE_DIR],
            check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL
        )
    return summary

def main():
    prev, curr = last_two_snaps()
    if not prev:
        print("[live] not enough snapshots yet", file=sys.stderr); sys.stdout.flush(); return 0

    summary = ensure_pair_diff(prev, curr)
    a,c,r = parse_summary(summary)

    A,C,R = read_totals(); A+=a; C+=c; R+=r; write_totals(A,C,R)

    start_epoch, step = read_start_and_interval()
    ep_prev = get_epoch_from_snap(prev); ep_curr = get_epoch_from_snap(curr)
    t_prev_s = quantize_offset(ep_prev, start_epoch, step)
    t_curr_s = quantize_offset(ep_curr, start_epoch, step)

    pid = None
    try:
        with open(PIDFILE) as f: pid=int(f.read().strip())
    except: pass
    rss_kb = read_rss_kb(pid) if pid else 0

    append_csv_row(t_prev_s, t_curr_s, prev, curr, max(0, t_curr_s - t_prev_s),
                   a,c,r, A,C,R, rss_kb)

    # print only ONE line including RSS
    sys.stdout.write(f"added={a} changed={c} removed={r} RSS={mib(rss_kb):.2f}MiB\n")
    sys.stdout.flush()
    return 0

if __name__ == "__main__":
    sys.exit(main())
