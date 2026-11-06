#!/usr/bin/env python3
"""Direct cyclic antibandwidth MILP, equations (1)-(8), PDF 30/10/2026.

Exactly one optimize() per graph. No threshold feasibility search or CP-SAT.
"""
from __future__ import annotations
import argparse
from collections import defaultdict
import json
import math
from pathlib import Path
import random
import time


def read_graph(path):
    path = Path(path)
    if path.suffix == '.json':
        doc = json.loads(path.read_text())
        n = doc['n']
        if type(n) is not int or n < 2:
            raise ValueError('n must be an integer >= 2')
        edges = set()
        for pair in doc['edges']:
            if len(pair) != 2 or any(type(v) is not int for v in pair):
                raise ValueError('Invalid edge')
            u, v = pair
            if not (0 <= u < n and 0 <= v < n) or u == v:
                raise ValueError('Invalid endpoints/self-loop')
            edges.add(tuple(sorted((u, v))))
        start, cliques = doc.get('start'), doc.get('cliques', [])
    else:
        n, edges = None, set()
        for line_no, line in enumerate(path.read_text().splitlines(), 1):
            tokens = line.split()
            if not tokens:
                continue
            if n is None:
                if len(tokens) in (2, 3) and all(t.isdigit() for t in tokens):
                    header = list(map(int, tokens))
                    if header[0] != header[1] or header[0] < 2:
                        raise ValueError(f'Invalid header at line {line_no}')
                    n = header[0]  # Third field is an annotation, never an objective bound.
                continue
            if len(tokens) != 2:
                raise ValueError(f'Invalid edge at line {line_no}')
            u, v = (int(t) - 1 for t in tokens)
            if not (0 <= u < n and 0 <= v < n) or u == v:
                raise ValueError(f'Invalid endpoints at line {line_no}')
            edges.add(tuple(sorted((u, v))))
        start, cliques = None, []
    if n is None or not edges:
        raise ValueError('Requires n >= 2 and at least one edge')
    if start is not None:
        if len(start) != n:
            raise ValueError('Invalid start length')
        validate_labels(start, edges)
    for clique in cliques:
        if len(clique) < 2 or len(set(clique)) != len(clique):
            raise ValueError('Invalid clique')
        if any(type(v) is not int or not 0 <= v < n for v in clique):
            raise ValueError('Invalid clique vertex')
        if any(tuple(sorted((u, v))) not in edges for i, u in enumerate(clique) for v in clique[i+1:]):
            raise ValueError('Supplied clique is not complete')
    return n, sorted(edges), start, cliques


def validate_labels(labels, edges):
    n = len(labels)
    if any(type(x) is not int for x in labels) or sorted(labels) != list(range(n)):
        raise ValueError('Labels must be a permutation of 0,...,n-1')
    return min(min(abs(labels[u]-labels[v]), n-abs(labels[u]-labels[v])) for u, v in edges)


def prepare(n, edges, start, cliques, seed, deadline, reflection=True, leaf_symmetry=True):
    adj = [set() for _ in range(n)]
    for u, v in edges:
        adj[u].add(v); adj[v].add(u)
    root = max(range(n), key=lambda v: (len(adj[v]), -v))
    upper = min(n//2, (n+1-max(map(len, adj)))//2,
                min((n//len(c) for c in cliques), default=n//2))
    best = list(range(n)) if start is None else list(start)
    lower = validate_labels(best, edges)
    rng = random.Random(seed)
    for _ in range(100):
        if time.perf_counter() >= deadline or lower == upper:
            break
        candidate = list(range(n)); rng.shuffle(candidate)
        value = validate_labels(candidate, edges)
        if value > lower:
            best, lower = candidate, value
    best = [(x-best[root]) % n for x in best]
    pair = tuple(v for v in range(n) if v != root)[:2] if reflection and n >= 3 else ()
    if pair and best[pair[0]] > best[pair[1]]:
        best = [(-x) % n for x in best]
    leaves = defaultdict(list)
    if leaf_symmetry:
        for v in range(n):
            if len(adj[v]) == 1 and v not in (root, *pair):
                leaves[next(iter(adj[v]))].append(v)
    groups = [vs for vs in leaves.values() if len(vs) > 1]
    for group in groups:
        for v, label in zip(group, sorted(best[v] for v in group)):
            best[v] = label
    assert validate_labels(best, edges) == lower
    domains = [([0] if v == root else range(lower, n-lower+1) if v in adj[root]
                else range(1, n)) for v in range(n)]
    return best, lower, upper, root, pair, groups, domains


def solve(n, edges, start=None, cliques=(), *, time_limit=150., threads=2, seed=0,
          heuristic_seconds=0.2, window_cuts=False, reflection=True, leaf_symmetry=True,
          env=None, log_file=None, export_lp=None, memory_limit_gb=None):
    import gurobipy as gp
    from gurobipy import GRB
    if time_limit <= 0 or not math.isfinite(time_limit) or threads < 1 or seed < 0 or heuristic_seconds < 0:
        raise ValueError('Invalid time/thread/seed settings')
    if memory_limit_gb is not None and (not math.isfinite(memory_limit_gb) or memory_limit_gb <= 0):
        raise ValueError('Memory limit must be positive and finite')
    began = time.perf_counter()
    best, lower, upper, root, pair, groups, domains = prepare(
        n, edges, start, cliques, seed,
        began+min(heuristic_seconds, time_limit*0.05), reflection, leaf_symmetry)
    if lower > upper:
        raise ValueError('Inconsistent bounds')
    with gp.Model('CAB_direct', env=env) as model:
        model.Params.OutputFlag = 1 if log_file else 0
        model.Params.LogToConsole = 0
        if log_file:
            model.Params.LogFile = str(log_file)
        model.Params.Threads = threads
        model.Params.Seed = seed
        if memory_limit_gb is not None:
            model.Params.SoftMemLimit = memory_limit_gb
        model.Params.MIPGap = 0
        model.Params.MIPGapAbs = 0
        # Sparse assignments; continuous p is integral through its defining equality.
        x = model.addVars(((v, label) for v in range(n) for label in domains[v]),
                          vtype=GRB.BINARY, name='x')
        p = model.addVars(n, lb=0, ub=n-1, name='p')
        b = model.addVars(edges, vtype=GRB.BINARY, name='b')
        K = model.addVar(lb=lower, ub=upper, vtype=GRB.INTEGER, name='K')
        columns = [[] for _ in range(n)]
        for v in range(n):
            row = [x[v, label] for label in domains[v]]
            model.addConstr(gp.quicksum(row) == 1, name=f'vertex_{v}')
            model.addConstr(p[v] == gp.LinExpr(list(domains[v]), row), name=f'position_{v}')
            for label in domains[v]:
                columns[label].append(x[v, label])
        for label, column in enumerate(columns):
            model.addConstr(gp.quicksum(column) == 1, name=f'label_{label}')
        del columns
        for u, v in edges:
            delta = p[u]-p[v]+n*b[u, v]
            model.addConstr(K <= delta, name=f'edge_lo_{u}_{v}')
            model.addConstr(delta <= n-K, name=f'edge_hi_{u}_{v}')
        if pair:
            model.addConstr(p[pair[0]]+1 <= p[pair[1]], name='reflection')
        for group in groups:
            for u, v in zip(group, group[1:]):
                model.addConstr(p[u]+1 <= p[v], name=f'leaves_{u}_{v}')
        if window_cuts and lower > 1:
            for ci, clique in enumerate([*edges, *cliques]):
                for s in range(n):
                    terms = [x[v, label] for v in clique
                             for j in range(lower) if (v, label := (s+j) % n) in x]
                    if len(terms) > 1:
                        model.addConstr(gp.quicksum(terms) <= 1, name=f'window_{ci}_{s}')
        model.setObjective(K, GRB.MAXIMIZE)
        model.update()
        model.setAttr('Start', list(x.values()), [int(best[v] == label) for v, label in x])
        model.setAttr('Start', list(p.values()), best)
        model.setAttr('Start', list(b.values()), [int(best[u] < best[v]) for u, v in edges])
        K.Start = lower
        if export_lp:
            model.write(str(export_lp))
        build = time.perf_counter()-began
        model.Params.TimeLimit = max(0., time_limit-build)
        model.optimize()  # The ONLY optimize call. Even if L==U, retains one-call workflow.
        solver_status = model.Status
        if solver_status in (GRB.INFEASIBLE, GRB.INF_OR_UNBD, GRB.UNBOUNDED):
            raise RuntimeError(f'Unexpected solver status {solver_status}; feasible start exists')
        obj, raw_bound, gap = None, None, None
        if model.SolCount:
            labels = [int(round(p[v].X)) for v in range(n)]
            value = validate_labels(labels, edges)
            obj = K.X
            if value+1e-6 < obj:
                raise RuntimeError('Solver objective exceeds checked CAB')
            if value > lower:
                best, lower = labels, value
            gap = model.MIPGap
        try:
            raw_bound = model.ObjBound
        except (gp.GurobiError, AttributeError):
            pass
        bound = min(upper, raw_bound) if raw_bound is not None and math.isfinite(raw_bound) else upper
        if bound < lower-1e-5:
            raise RuntimeError('Solver upper bound below verified labeling')
        certified = solver_status == GRB.OPTIMAL or bound < lower+1-1e-6
        bound = lower if certified else max(lower, bound)
        result = dict(status='OPTIMAL' if certified else 'FEASIBLE_UNPROVEN',
                      n=n, m=len(edges), objective=lower, labels=best, upper_bound=bound,
                      relative_gap=(bound-lower)/lower, initial_lower_bound=K.LB,
                      analytical_upper_bound=upper, gurobi_objective=obj,
                      gurobi_bound=raw_bound if raw_bound is not None and math.isfinite(raw_bound) else None,
                      gurobi_gap=gap if gap is not None and math.isfinite(gap) else None,
                      solver_status=solver_status, build_seconds=build, runtime_seconds=model.Runtime,
                      total_seconds=time.perf_counter()-began, num_vars=model.NumVars,
                      num_constraints=model.NumConstrs, nodes=model.NodeCount,
                      optimize_calls=1, time_limit=time_limit, threads=threads, seed=seed,
                      memory_limit_gb=memory_limit_gb)
    return result


def write_json(path, doc):
    path = Path(path); path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(doc, indent=2, ensure_ascii=False, allow_nan=False)+'\n')
    temp.replace(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('graph', type=Path)
    parser.add_argument('--time-limit', type=float, default=150)
    parser.add_argument('--threads', type=int, default=2)
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--heuristic-seconds', type=float, default=0.2)
    parser.add_argument('--window-cuts', action='store_true')
    parser.add_argument('--export-lp', type=Path)
    parser.add_argument('--output', type=Path, default=Path('cab_result.json'))
    args = parser.parse_args()
    n, edges, start, cliques = read_graph(args.graph)
    result = solve(n, edges, start, cliques, time_limit=args.time_limit, threads=args.threads,
                   seed=args.seed, heuristic_seconds=args.heuristic_seconds,
                   window_cuts=args.window_cuts, export_lp=args.export_lp)
    write_json(args.output, result)
    print(f"{result['status']}: CAB={result['objective']}, UB={result['upper_bound']}; {args.output}")

if __name__ == '__main__':
    main()
