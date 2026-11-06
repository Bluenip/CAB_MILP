#!/usr/bin/env bash
# Run manually on 100.71.200.54 after copying this project and its dataset/.
# Usage: bash run_on_orlab.sh [--dry-run]
# Resume: OUTPUT=/absolute/path/to/existing/run bash run_on_orlab.sh
# Optional: PYTHON=/path/to/python GRB_LICENSE_FILE=/path/to/gurobi.lic
set -euo pipefail
ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
export CPU_LIST="${CPU_LIST:-0-7}"
export SCOPE=paper
if [[ "${1:-}" == --dry-run ]]; then
    [[ $# == 1 ]] || { echo 'Usage: bash run_on_orlab.sh [--dry-run]' >&2; exit 2; }
    # Planning only: does not install packages, open a license or solve a model.
    exec "${PYTHON:-python3}" "$ROOT/run_benchmarks.py" --scope paper --tier all --dry-run
fi
[[ $# == 0 ]] || { echo 'Usage: bash run_on_orlab.sh [--dry-run]' >&2; exit 2; }
command -v taskset >/dev/null || { echo 'Missing taskset (Linux util-linux).' >&2; exit 1; }
[[ -d "$ROOT/dataset" ]] || { echo 'Copy dataset/ with this project before running.' >&2; exit 1; }
# Verify the CPU allocation before installing dependencies or starting work.
"${PYTHON:-python3}" - "$CPU_LIST" <<'PY'
import os,sys
from pathlib import Path
cpus=set()
for part in sys.argv[1].split(','):
    if '-' in part:
        lo,hi=map(int,part.split('-'));cpus.update(range(lo,hi+1))
    else:cpus.add(int(part))
if len(cpus)!=8 or not cpus.issubset(os.sched_getaffinity(0)):
    raise SystemExit('CPU_LIST must select 8 permitted logical CPUs. Default 0-7 is for the inspected orlab host.')
cores=set()
for cpu in cpus:
    base=Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
    cores.add(((base/'physical_package_id').read_text().strip(),(base/'core_id').read_text().strip()))
if len(cores)!=4:
    raise SystemExit(f'Selected {len(cores)} physical cores; expected 4 physical cores / 8 logical CPUs. Set CPU_LIST for this host.')
memory=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
print(f'CPU allocation verified: {sorted(cpus)}, 4 physical cores / 8 logical CPUs. Host RAM: {memory/1e9:.1f} GB.',flush=True)
PY
if [[ -z "${PYTHON:-}" ]]; then
    if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
        python3 -m venv "$ROOT/.venv"
    fi
    export PYTHON="$ROOT/.venv/bin/python"
fi
if ! "$PYTHON" -c 'import gurobipy as g; assert g.gurobi.version() == (13,0,3)' >/dev/null 2>&1; then
    "$PYTHON" -m pip install -r "$ROOT/requirements.txt"
fi
# Prefer an explicitly supplied license; otherwise Gurobi searches its default locations.
if [[ -z "${GRB_LICENSE_FILE:-}" && -f "$ROOT/.gurobi/gurobi.lic" ]]; then
    export GRB_LICENSE_FILE="$ROOT/.gurobi/gurobi.lic"
fi
"$PYTHON" - <<'PY'
import gurobipy as gp
try:
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag',0)
        env.start()
        print('Gurobi environment/license startup OK; version='+'.'.join(map(str,gp.gurobi.version())),flush=True)
except gp.GurobiError as exc:
    raise SystemExit('Gurobi license startup failed. Configure GRB_LICENSE_FILE or a valid license on this machine. '+str(exc))
PY
export OUTPUT="${OUTPUT:-$ROOT/paper_runs/paper_comparison_$(date +%Y%m%d_%H%M%S)}"
printf 'Output: %s\n' "$OUTPUT"
printf '%s\n' 'Protocol: paper manifest; 150s tier then 1800s tier; 4-thread run then 8-thread run; seed=0; Gurobi SoftMemLimit=30GB.'
printf '%s\n' 'SAT-CAB uses 4/8 processes; these are corresponding Gurobi thread budgets, not identical search algorithms or hardware.'

# Record the protocol, run both configurations, then merge results.
mkdir -p "$OUTPUT"
"$PYTHON" - "$OUTPUT" "$CPU_LIST" "$SCOPE" <<'PY'
import os,platform,json,sys
from pathlib import Path
output=Path(sys.argv[1])
allowed=sorted(os.sched_getaffinity(0))
requested=sys.argv[2]
if requested:
    chosen=set()
    for part in requested.split(','):
        if '-' in part:
            lo,hi=map(int,part.split('-')); chosen.update(range(lo,hi+1))
        else: chosen.add(int(part))
    if len(chosen)!=8 or not chosen.issubset(allowed):
        raise SystemExit('CPU_LIST must specify exactly 8 allowed logical CPUs')
else:
    # Prefer 4 physical cores with 2 logical siblings each, where exposed by Linux.
    groups={}
    for cpu in allowed:
        base=Path(f'/sys/devices/system/cpu/cpu{cpu}/topology')
        try:key=((base/'physical_package_id').read_text().strip(),(base/'core_id').read_text().strip())
        except OSError:key=('unknown',str(cpu))
        groups.setdefault(key,[]).append(cpu)
    paired=[g for g in groups.values() if len(g)>=2]
    chosen=set(cpu for g in paired[:4] for cpu in g[:2]) if len(paired)>=4 else set(allowed[:8])
    if len(chosen)!=8:raise SystemExit('This protocol requires at least 8 allowed logical CPUs')
cpus=','.join(map(str,sorted(chosen)))
mem=os.sysconf('SC_PAGE_SIZE')*os.sysconf('SC_PHYS_PAGES')
config=dict(threads=[4,8],time_tiers=[150,1800],seed=0,soft_memory_limit_gb=30,
            cpu_affinity=sorted(chosen),scope=sys.argv[3],aggregation='best CAB of 4/8-thread runs',
            caveat='Gurobi threads are not SAT-CAB processes; hardware/OS must be reported separately')
p=output/'protocol.json'
if p.exists() and json.loads(p.read_text())!=config:raise SystemExit('Resume protocol mismatch; choose a new OUTPUT')
p.write_text(json.dumps(config,indent=2)+'\n')
(output/'cpu_list.txt').write_text(cpus+'\n')
(output/'machine.json').write_text(json.dumps(dict(platform=platform.platform(),python=sys.version,
    logical_cpus_allowed=allowed,cpu_affinity=sorted(chosen),physical_memory_bytes=mem),indent=2)+'\n')
print(f'CPU affinity={cpus}; physical RAM={mem/1e9:.1f} GB; 4/8 threads, 150/1800s, Gurobi soft cap=30 GB',flush=True)
print('Paper host: Debian 12, 4 cores/8 vCPU, 64 GB RAM; SAT-CAB uses 4/8 processes. This host is recorded, not claimed identical.',flush=True)
PY
CPU_LIST="$(cat "$OUTPUT/cpu_list.txt")"
for count in 4 8; do
    taskset -c "$CPU_LIST" "$PYTHON" -u "$ROOT/run_benchmarks.py" \
        --scope "$SCOPE" --tier all --threads "$count" --seed 0 --memory-limit-gb 30 \
        --output "$OUTPUT/threads_$count" --resume 2>&1 | tee "$OUTPUT/console_threads_$count.log"
done
"$PYTHON" "$ROOT/collect_paper_best.py" "$OUTPUT"
echo "Completed: $OUTPUT/best_results.csv"
