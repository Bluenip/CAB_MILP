#!/usr/bin/env python3
"""Combine complete 4/8-thread runs without conflating separate time tiers."""
import csv
import json
from pathlib import Path
import sys
from cab_milp import read_graph, validate_labels, write_json

ROOT=Path(__file__).resolve().parent
SAT_HYPERCUBES={4:'4',5:'9',6:'19',7:'36',8:'51',9:'TO',10:'MO'}


def main():
    output=Path(sys.argv[1])
    schedules=[json.loads((output/f'threads_{t}/manifest.json').read_text()) for t in (4,8)]
    if schedules[0]!=schedules[1]:raise ValueError('Configurations have different schedules')
    rows=[]
    for row in schedules[0]['selected']:
        candidates=[]
        for threads in (4,8):
            p=output/f'threads_{threads}/solutions'/str(row['seconds'])/(row['instance']+'.json')
            d=json.loads(p.read_text())
            if d['status'] not in ('OPTIMAL','FEASIBLE_UNPROVEN'):
                raise ValueError(f'Unfinished/error result: {p}')
            n,edges,_,_=read_graph(ROOT/'dataset'/row['instance'])
            if len(d['labels'])!=n or validate_labels(d['labels'],edges)!=d['objective']:
                raise ValueError(f'Invalid labeling: {p}')
            if d['threads']!=threads or d['time_limit']!=row['seconds']:
                raise ValueError(f'Wrong resource settings: {p}')
            candidates.append(d)
        best=max(candidates,key=lambda d:(d['objective'],d['status']=='OPTIMAL',-d['upper_bound'],-d['total_seconds']))
        target=output/'best_solutions'/str(row['seconds'])/(row['instance']+'.json')
        write_json(target,dict(best,best_of_threads=[4,8]))
        sat=''
        if row['instance'].startswith('hypercubes/'):
            dimension=int(Path(row['instance']).name.split('_')[1]);sat=SAT_HYPERCUBES[dimension]
        rows.append(dict(instance=row['instance'],seconds=row['seconds'],
            CAB_4threads=candidates[0]['objective'],CAB_8threads=candidates[1]['objective'],
            CAB_best=best['objective'],selected_threads=best['threads'],
            upper_bound=best['upper_bound'],status=best['status'],
            seconds_4=candidates[0]['total_seconds'],seconds_8=candidates[1]['total_seconds'],
            SAT_CAB_paper_B4=sat,delta_vs_SAT=best['objective']-int(sat) if sat.isdigit() else ''))
    if not rows:raise ValueError('No results')
    with (output/'best_results.csv').open('w',newline='') as f:
        w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
    print(f'Combined {len(rows)} runs; labels verified; missing paper instances remain listed in manifests.')
    print('SAT values are populated only for hypercube Table B4, which was checked against the paper; blank elsewhere means not yet transcribed.')

if __name__=='__main__':main()
