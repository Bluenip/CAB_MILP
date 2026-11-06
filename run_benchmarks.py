#!/usr/bin/env python3
"""Validate manifests, schedule 150s before 1800s, run/resume direct MILP."""
import argparse
from collections import Counter
import csv
import hashlib
import json
from pathlib import Path
import platform
import sys
import time
from cab_milp import read_graph, solve, validate_labels, write_json

ROOT = Path(__file__).resolve().parent


def plan(dataset, manifest, scope, tier, extra_seconds):
    doc = json.loads(manifest.read_text())
    rows, missing, assigned = [], [], set()
    for original in doc['instances']:
        row = dict(original)
        relative = row['instance']
        if relative is None or not (dataset/relative).is_file():
            missing.append(row); continue
        path = (dataset/relative).resolve()
        if not path.is_relative_to(dataset.resolve()):
            raise ValueError(f'Path outside dataset: {relative}')
        n, edges, _, _ = read_graph(path)
        if (n, len(edges)) != (row['n'], row['m']):
            raise ValueError(f'Size mismatch: {relative}')
        key = (relative, row['seconds'])
        if key in assigned:
            raise ValueError(f'Duplicate manifest row: {key}')
        assigned.add(key)
        row['source'] = 'old_manifest'
        rows.append(row)
    extras = []
    named = {r['instance'] for r in rows}
    for path in sorted(dataset.rglob('*')):
        if not path.is_file():
            continue
        relative = path.relative_to(dataset).as_posix()
        if relative in named:
            continue
        n, edges, _, _ = read_graph(path)  # Fail visibly on any unsupported file.
        extras.append(dict(instance=relative, seconds=extra_seconds, n=n, m=len(edges),
                           table='', paper_instance='', source='extra_dataset'))
    selected = rows if scope == 'paper' else extras if scope == 'extras' else rows+extras
    selected = [r for r in selected if tier == 'all' or r['seconds'] == int(tier)]
    # Exactly matches old solve.py graph_order within each time tier.
    selected.sort(key=lambda r: (r['seconds'], r['n'], r['instance']))
    for order, row in enumerate(selected, 1):
        row['order'] = order
    return dict(source=doc['source'], scope=scope, selected=selected, missing=missing,
                extra_files=len(extras), dataset_files=len(named)+len(extras))


def save_plan(output, schedule):
    write_json(output/'manifest.json', schedule)
    fields = ['order','seconds','instance','n','m','table','paper_instance','source']
    with (output/'schedule.csv').open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader(); w.writerows(schedule['selected'])
    write_json(output/'missing_instances.json', schedule['missing'])


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--dataset', type=Path, default=ROOT/'dataset')
    p.add_argument('--manifest', type=Path, default=ROOT/'paper_instances.json')
    p.add_argument('--scope', choices=['paper','all','extras'], default='paper')
    p.add_argument('--tier', choices=['all','150','1800'], default='all')
    p.add_argument('--extra-seconds', type=int, choices=[150,1800], default=150)
    p.add_argument('--output', type=Path)
    p.add_argument('--dry-run', action='store_true')
    p.add_argument('--resume', action='store_true')
    p.add_argument('--threads', type=int, default=2)
    p.add_argument('--seed', type=int, default=0)
    p.add_argument('--window-cuts', action='store_true')
    p.add_argument('--heuristic-seconds', type=float, default=0.2)
    p.add_argument('--memory-limit-gb', type=float, help='Gurobi SoftMemLimit, decimal GB')
    p.add_argument('--limit', type=int, help='Smoke test: first N scheduled runs')
    p.add_argument('--time-limit-override', type=float, help='Smoke test ONLY: replace per-graph budgets')
    args = p.parse_args()
    if args.threads < 1 or not 0 <= args.seed <= 2000000000 or args.heuristic_seconds < 0:
        p.error('Invalid parameters')
    if args.memory_limit_gb is not None and args.memory_limit_gb <= 0:
        p.error('Memory limit must be positive')
    if args.time_limit_override is not None and args.time_limit_override <= 0:
        p.error('Override must be positive')
    if args.limit is not None and args.limit < 1:
        p.error('Limit must be positive')
    schedule = plan(args.dataset, args.manifest, args.scope, args.tier, args.extra_seconds)
    if args.limit:
        schedule['selected'] = schedule['selected'][:args.limit]
    rows = schedule['selected']
    print(f"Dataset files validated: {schedule['dataset_files']}; extra files: {schedule['extra_files']}", flush=True)
    counts = Counter(r['seconds'] for r in rows)
    print(f"Selected: {len(rows)} runs, budgets={dict(counts)}; missing paper entries={len(schedule['missing'])}", flush=True)
    print(f"Sequential budget sum: {sum(r['seconds'] for r in rows)/3600:.2f} hours; build/solver deadlines are soft.", flush=True)
    for row in rows:
        if args.dry_run:
            print(f"{row['order']:03d} {row['seconds']:4d}s n={row['n']:5d} m={row['m']:6d} {row['instance']}")
    if args.dry_run:
        if args.output:
            args.output.mkdir(parents=True, exist_ok=True); save_plan(args.output, schedule)
        return
    if not rows:
        p.error('No selected datasets')
    output = args.output or ROOT/'paper_runs'/time.strftime('run_%Y%m%d_%H%M%S')
    output.mkdir(parents=True, exist_ok=True)
    if (output/'manifest.json').exists():
        if not args.resume:
            p.error('Output already contains a run; use a new directory or --resume')
        if json.loads((output/'manifest.json').read_text()) != schedule:
            p.error('Resume schedule differs from original run')
    save_plan(output, schedule)
    import gurobipy as gp
    settings = dict(threads=args.threads, seed=args.seed, window_cuts=args.window_cuts,
                    heuristic_seconds=args.heuristic_seconds, time_limit_override=args.time_limit_override)
    if args.memory_limit_gb is not None:
        settings['memory_limit_gb'] = args.memory_limit_gb
    config = output/'settings.json'
    if args.resume and config.exists() and json.loads(config.read_text()) != settings:
        p.error('Resume solver settings differ from original run')
    write_json(config, settings)
    write_json(output/'environment.json', dict(python=sys.version, executable=sys.executable,
               platform=platform.platform(), gurobi_version=gp.gurobi.version()))
    failures = 0
    fields = ['order','instance','time_limit','status','objective','upper_bound','relative_gap',
              'solver_status','build_seconds','runtime_seconds','total_seconds','num_vars',
              'num_constraints','nodes','error']
    with gp.Env(empty=True) as env:
        env.setParam('OutputFlag', 0); env.start()
        with (output/'summary.csv').open('w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore'); writer.writeheader(); f.flush()
            for row in rows:
                path = args.dataset/row['instance']
                budget = args.time_limit_override or row['seconds']
                target = output/'solutions'/str(row['seconds'])/(row['instance']+'.json')
                fingerprint = hashlib.sha256(path.read_bytes()).hexdigest()
                result = None
                if args.resume and target.exists():
                    prior = json.loads(target.read_text())
                    if prior.get('status') in ('OPTIMAL','FEASIBLE_UNPROVEN'):
                        n, edges, _, _ = read_graph(path)
                        if prior.get('input_sha256') != fingerprint:
                            raise ValueError(f'Input changed: {path}')
                        if len(prior['labels']) != n or validate_labels(prior['labels'], edges) != prior['objective']:
                            raise ValueError(f'Invalid saved result: {target}')
                        result = prior
                        print(f"[{row['order']}/{len(rows)}] RESUME skip {row['instance']}", flush=True)
                if result is None:
                    print(f"[{row['order']}/{len(rows)}] START {row['instance']} budget={budget}s", flush=True)
                    try:
                        n, edges, start, cliques = read_graph(path)
                        log = output/'gurobi_logs'/str(row['seconds'])/(row['instance']+'.log')
                        log.parent.mkdir(parents=True, exist_ok=True)
                        result = solve(n, edges, start, cliques, time_limit=budget, threads=args.threads,
                                       seed=args.seed, heuristic_seconds=args.heuristic_seconds,
                                       window_cuts=args.window_cuts, env=env, log_file=log,
                                       memory_limit_gb=args.memory_limit_gb)
                    except Exception as exc:
                        result = dict(status='ERROR', error=f'{type(exc).__name__}: {exc}', time_limit=budget)
                    result.update(instance=row['instance'], order=row['order'], input_sha256=fingerprint,
                                  scheduled_seconds=row['seconds'])
                    write_json(target, result)
                    print(f"  {result['status']}: CAB={result.get('objective')} UB={result.get('upper_bound')} {result.get('error','')}", flush=True)
                failures += result['status'] == 'ERROR'
                writer.writerow(result); f.flush()
    print(f'Finished: {output}; errors={failures}', flush=True)
    if failures:
        raise SystemExit(1)

if __name__ == '__main__':
    main()
