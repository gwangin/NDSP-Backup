#!/bin/bash

echo "Generating traces for 4KB pages"
export PAGE_SHIFT=12   # 4KB

# ==== OLAP (워킹셋 ~32~48 MiB 타깃) ====
python3 examples/runner.py --kernel LtINT64Kernel     --output_dir ./traces/imdb_lt_int64       --skip_functional_sim --arg 1
echo "lt_int64 done"
python3 examples/runner.py --kernel GtEqLtINT64Kernel --output_dir ./traces/imdb_gteq_lt_int64   --skip_functional_sim --arg 1
echo "gteq_lt_int64 done"
python3 examples/runner.py --kernel GtLtFP32Kernel    --output_dir ./traces/imdb_gt_lt_fp32      --skip_functional_sim --arg 2
echo "gt_lt_fp32 done"
python3 examples/runner.py --kernel ThreeColANDKernel --output_dir ./traces/imdb_three_col_and   --skip_functional_sim --arg 64
echo "three_col_and done"

echo "Done generating traces (4KB)"
