"""Plan disjoint agent shards, then validate and merge candidate JSON outputs."""
import argparse
from pathlib import Path
from collections import Counter
from ocr_common import ROOT, RunLock, read_json, atomic_json, validate


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    sub = ap.add_subparsers(dest='command', required=True)
    plan = sub.add_parser('plan')
    plan.add_argument('--shards', type=int, default=3)
    plan.add_argument('--out', type=Path, default=ROOT / 'runs/agent-plan')
    merge = sub.add_parser('merge')
    merge.add_argument('--plan', type=Path, required=True)
    merge.add_argument('--input', type=Path, action='append', required=True, help='Candidate directory; repeat for each shard')
    merge.add_argument('--force', action='store_true')
    args = ap.parse_args()
    questions = read_json(ROOT / 'manifest.json')['questions']
    if args.command == 'plan':
        if args.shards < 1 or args.shards > len(questions): ap.error('Invalid shard count')
        if args.out.exists(): ap.error('Plan directory already exists; choose a new path')
        for field in ('qid', 'item_id', 'seq'):
            if len({q[field] for q in questions}) != len(questions): raise ValueError(f'Duplicate {field}')
        args.out.mkdir(parents=True)
        assignments = []
        for index in range(args.shards):
            group = questions[index::args.shards]
            name = f'shard-{index + 1:02d}'
            task = {'shard': name, 'prompt': 'work/ocr-ai/prompt.md',
                    'schema': 'work/ocr-ai/output.schema.json',
                    'output': f'runs/candidates/{name}', 'questions': group,
                    'policy': 'Read only images.question in listed order; do not solve; write one JSON per item_id; never edit canonical files.'}
            atomic_json(args.out / (name + '.json'), task)
            assignments.append({'shard': name, 'item_ids': [q['item_id'] for q in group]})
        atomic_json(args.out / 'plan.json', {'schema_version': 1, 'assignments': assignments})
        print(f'Planned {len(questions)} questions in {args.shards} disjoint shards')
        return 0
    plan_data = read_json(args.plan)
    ordered = [i for shard in plan_data['assignments'] for i in shard['item_ids']]
    counts = Counter(ordered)
    if any(v != 1 for v in counts.values()): raise ValueError('Duplicate assignment')
    qmap = {q['item_id']: q for q in questions}
    if set(ordered) != set(qmap): raise ValueError('Plan coverage differs from manifest')
    candidates = {}
    for directory in args.input:
        if not directory.is_dir(): raise ValueError(f'Missing candidate directory: {directory}')
        for f in sorted(directory.glob('*.json')):
            if f.stem not in qmap or f.stem in candidates: raise ValueError(f'Unknown or duplicate candidate: {f.name}')
            obj = read_json(f)
            validate(obj, qmap[f.stem])
            if obj['status'] == 'failed': raise ValueError(f'Failed candidate: {f.name}')
            candidates[f.stem] = obj
    if set(candidates) != set(ordered): raise ValueError('Missing candidate results')
    with RunLock():
        if not args.force and any((ROOT / 'json/ocr/question' / (i + '.json')).exists() for i in ordered):
            raise ValueError('Canonical result exists; use --force after reviewing candidates')
        # All validation completes before the first mutation. Each file replacement is atomic.
        for item_id in ordered:
            atomic_json(ROOT / 'json/ocr/question' / (item_id + '.json'), candidates[item_id])
        atomic_json(ROOT / 'runs/merge-report.json', {'merged': len(ordered), 'manual_overlays_preserved': True})
    print(f'Merged {len(ordered)} results; manual overlays preserved')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
