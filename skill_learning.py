"""Budgeted executable synthesis; trusted evaluation owns publication decisions."""
from __future__ import annotations

import time

try:
    from .autonomy_store import canonical
except ImportError:
    from autonomy_store import canonical


class SkillLearner:
    def __init__(self, store, llm, budget, evaluator, clock=time.time, daily_evaluations=16):
        self.store, self.llm, self.budget, self.evaluator = store, llm, budget, evaluator
        self.clock, self.daily_evaluations = clock, daily_evaluations

    def tick(self, now, admissible):
        with self.evaluator.locked() as acquired:
            if not acquired: return {'generated': 0, 'reason': 'evaluation_busy'}
            self.store.sync(now)  # Trusted settled reuse can retire while paused.
            if not self.store.tasks and not self.store.needs_cleanup(): return {'generated': 0}
            if not self.evaluator.cleanup(): return {'generated': 0, 'reason': 'cleanup_unknown'}
            if not admissible() or not self.store.evaluation_available(now, self.daily_evaluations): return {'generated': 0}
            job = self.store.claim(now)
            if job is None: return {'generated': 0}
            generated = 0
            try:
                if not job['code']:
                    if self.llm is None or not self.budget.take():
                        self.store.defer(job, self.clock(), 'model_or_budget_unavailable'); return {'generated': 0}
                    if not admissible() or not self.store.begin(job, self.clock()):
                        self.store.defer(job, self.clock(), 'admission_closed'); return {'generated': 0}
                    payload = {'task': {key: job['task'][key] for key in ('description', 'examples')},
                               'origin': {key: job['payload'][key] for key in ('objective', 'receipt', 'reason')}}
                    response = self.llm.complete_structured(
                        instructions='Write a standalone Python 3 standard-library program. Read one JSON value from stdin and print exactly one JSON value to stdout. Implement the given functional specification, including unseen cases. No shell commands, network, permissions, host changes, file access or extra commentary. The failure receipt is limited provenance, not an explanation of root cause. Return only code, at most 6000 UTF-8 bytes.',
                        input=[{'type': 'text', 'text': canonical(payload)}],
                        json_schema={'type': 'object', 'additionalProperties': False, 'required': ['code'],
                                     'properties': {'code': {'type': 'string', 'minLength': 1, 'maxLength': 6000}}},
                        json_mode=True, max_tokens=1800, timeout=45, purpose='zhulong.skill.learn')
                    parsed = getattr(response, 'parsed', None)
                    if not isinstance(parsed, dict) or set(parsed) != {'code'}: raise ValueError('invalid_skill_response')
                    # Persist an already-paid response while its lease is owned.
                    # Closing admission prevents execution, not saving this work.
                    if not self.store.freeze(job, parsed['code'], self.clock()):
                        self.store.defer(job, self.clock(), 'late_or_invalid_code'); return {'generated': 0}
                    generated = 1
                def gate(): return admissible() and self.store.owned(job, self.clock())
                if not gate() or not self.store.reserve_evaluation(self.clock(), self.daily_evaluations):
                    self.store.defer(job, self.clock(), 'evaluation_budget_or_admission'); return {'generated': generated}
                report = self.evaluator.evaluate(job['code'], job['task'], job['token'], gate)
                if not gate() or not self.store.finish(job, report, self.clock()):
                    self.store.defer(job, self.clock(), 'evaluation_unknown')
                    return {'generated': generated, 'reason': 'evaluation_unknown'}
                return {'generated': generated, 'evaluated': 1, 'published': int(report['verdict'] is True)}
            except Exception:
                self.store.defer(job, self.clock(), 'invalid_or_unavailable_skill')
                return {'generated': generated, 'reason': 'invalid_or_unavailable_skill'}
