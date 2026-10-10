"""Private trusted evaluation plans from immutable failed goal inputs."""
from __future__ import annotations

try:
    from .autonomy_store import canonical, digest
    from .skill_evaluator import strict_json
    from .task_inputs import _validated, INPUT_ENVELOPE_DEPTH
except ImportError:
    from autonomy_store import canonical, digest
    from skill_evaluator import strict_json
    from task_inputs import _validated, INPUT_ENVELOPE_DEPTH


def field(value, path):
    for part in path.split('.'):
        if not isinstance(value, dict) or part not in value: raise KeyError(path)
        value = value[part]
    return value


def evaluation_task(task, goal, submission):
    if not task.get('replay_origin'): return task
    try:
        snapshot = goal['task_input']; _validated(snapshot)
        intent = strict_json(submission['request']['input'],max_depth=INPUT_ENVELOPE_DEPTH)
        contract = goal['contract']
        if (canonical(intent['task_input']) != canonical(snapshot)
            or submission['goal_id'] != goal['id'] or snapshot['source_id'] != task['source_id']
            or snapshot['source_revision'] != goal['source_revision']
            or snapshot['rule_hash'] != task['input_rule_hash']
            or goal['contract_hash'] != task['contract_hash'] or digest(contract) != task['contract_hash']
            or contract['type'] != 'json_equals'): raise ValueError('binding_mismatch')
        predicate = {'field': contract['field'], 'value': contract['value']}
    except (KeyError, TypeError, ValueError, UnicodeError):
        raise ValueError('replay_unavailable') from None
    cases = strict_json(canonical(task['examples']+task['holdout']))
    index = next((i for i, case in enumerate(cases) if digest(case['input']) == snapshot['input_hash']), len(cases))
    if index < len(cases):
        try:
            if canonical(field(cases[index]['output'], predicate['field'])) != canonical(predicate['value']):
                raise ValueError('conflicting_output')
        except (KeyError, ValueError): raise ValueError('spec_conflict') from None
        cases[index]['predicate'] = predicate
    else:
        cases.append({'input': snapshot['data'], 'predicate': predicate})
    origin = {'schema':1, 'submission_id':submission['id'], 'input_hash':snapshot['input_hash'],
              'rule_hash':snapshot['rule_hash'], 'contract_hash':goal['contract_hash'], 'case_index':index}
    return {**task, '_evaluation_cases':cases, 'origin_replay':origin,
            'evaluation_digest':digest([task['task_digest'], origin, cases])}
