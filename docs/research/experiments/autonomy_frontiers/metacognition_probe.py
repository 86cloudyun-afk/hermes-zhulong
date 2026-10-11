"""Offline synthetic observations: metric semantics, not an LLM experiment."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[4]
sys.dont_write_bytecode = True
sys.path.insert(0, str(REPO))
from self_model import _metrics


def pairwise_auroc(samples):
    correct = [p for p, truth in samples if truth]
    errors = [p for p, truth in samples if not truth]
    if not correct or not errors:
        return None
    return sum(1 if p > q else 0.5 if p == q else 0
               for p in correct for q in errors) / (len(correct) * len(errors))


def main():
    groups = {
        'correct_order': [(0.8, True), (0.9, True), (0.2, False), (0.1, False)],
        'reversed_order': [(0.2, True), (0.1, True), (0.8, False), (0.9, False)],
        'constant_prior': [(0.5, True), (0.5, True), (0.5, False), (0.5, False)],
    }
    rows = {}
    for name, samples in groups.items():
        metrics = _metrics(samples)
        rows[name] = {
            'synthetic_samples': [{'forecast': p, 'truth': truth} for p, truth in samples],
            'actual_repository_metrics': metrics,
            'research_only_pairwise_auroc2': pairwise_auroc(samples),
            'research_only_correct_minus_error_confidence':
                metrics['confidence_on_correct'] - metrics['confidence_on_error'],
        }
    assert all(r['actual_repository_metrics']['error_discrimination'] == 'available'
               for r in rows.values())
    assert rows['correct_order']['research_only_pairwise_auroc2'] == 1.0
    assert rows['reversed_order']['research_only_pairwise_auroc2'] == 0.0
    assert rows['constant_prior']['research_only_pairwise_auroc2'] == 0.5
    report = {
        'schema': 1,
        'repo_head': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=REPO, text=True).strip(),
        'source': 'self_model._metrics',
        'scope': 'Four synthetic observations per group; no provider calls, human subjects, consciousness test, or performance intervention.',
        'finding': 'error_discrimination is an availability flag; it has the same value under opposite confidence rankings.',
        'research_only_metrics_not_product_features': True,
        'groups': rows,
    }
    out = Path(sys.argv[1]).resolve()
    out.mkdir(parents=True, exist_ok=True)
    path = out / 'metacognition_probe.json'
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
    print(json.dumps({'report': str(path), 'repo_head': report['repo_head'],
                      'groups': {name: {'flag': row['actual_repository_metrics']['error_discrimination'],
                                        'brier': row['actual_repository_metrics']['brier'],
                                        'auroc2': row['research_only_pairwise_auroc2']}
                                 for name, row in rows.items()}}, ensure_ascii=False))


if __name__ == '__main__':
    main()
