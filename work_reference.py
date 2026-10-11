"""Trusted, versioned business rules over explicitly frozen JSON inputs."""
from __future__ import annotations

try:
    from .autonomy_store import canonical
    from .skill_evaluator import strict_json
except ImportError:
    from autonomy_store import canonical
    from skill_evaluator import strict_json


REFERENCE_IDS = ('workload_summary_v1', 'ticket_priority_v1', 'source_index_v1')

_RULES = {
    'workload_summary_v1': (
        'Input: {"tasks":[{"id":string,"team":string,"minutes":integer,"done":boolean}]}. '
        'Minutes must be 0..1000000. Output exactly {"task_count":number of tasks,'
        '"total_minutes":sum of all minutes,"open_minutes":sum of minutes where done is false,'
        '"teams":[{"team":team,"task_count":number of tasks in team,"open_count":number not done,'
        '"total_minutes":sum in team,"open_minutes":sum not done in team}]}. Sort teams ascending by team.'),
    'ticket_priority_v1': (
        'Input: {"tickets":[{"id":string,"severity":integer,"age_hours":integer,"blocked":boolean}]}. '
        'Severity must be 1..5; age_hours 0..87600. Score = severity*100 + min(age_hours,168) '
        '+ (50 if blocked else 0). Priority is "urgent" for score>=500, "high" for score>=300, '
        'otherwise "normal". Output exactly {"tickets":[{"id":id,"score":integer,"priority":string}]} '
        'sorted by descending score, then ascending id.'),
    'source_index_v1': (
        'Input: {"sources":[{"id":string,"title":string,"url":string,"tags":[string]}]}. '
        'Tags must be unique within a source, at most 16. Output exactly {"source_count":number of sources,'
        '"sources":all input source records sorted by id with tags sorted ascending,'
        '"tag_index":[{"tag":tag,"source_ids":sorted ids containing tag}]} with tag_index sorted ascending by tag.'),
}


def reference_instructions(reference_id):
    """Describe the rule; this never consumes inputs or discloses an answer."""
    if reference_id not in REFERENCE_IDS: raise ValueError('unknown_reference')
    return (_RULES[reference_id] + ' Input fields and types are exact. The input list has at most 64 records '
            'with unique ids. All strings are nonempty, at most 200 characters (url at most 500). '
            'All output counts, sums, and scores are integers. Write only the complete JSON output.')


def _fields(value, names):
    if not isinstance(value, dict) or set(value) != set(names): raise ValueError('invalid_reference_fields')


def _text(value, limit=200):
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        raise ValueError('invalid_reference_text')
    return value


def _integer(value, low, high):
    if type(value) is not int or not low <= value <= high: raise ValueError('invalid_reference_integer')
    return value


def _boolean(value):
    if type(value) is not bool: raise ValueError('invalid_reference_boolean')
    return value


def _records(data, key, fields):
    _fields(data, (key,))
    records = data[key]
    if not isinstance(records, list) or len(records) > 64: raise ValueError('invalid_reference_records')
    ids = set()
    for record in records:
        _fields(record, fields)
        sid = _text(record['id'])
        if sid in ids: raise ValueError('duplicate_reference_id')
        ids.add(sid)
    return records


def reference_output(reference_id, data):
    """Compute a useful deterministic result without reading a mutable source."""
    if reference_id not in REFERENCE_IDS: raise ValueError('unknown_reference')
    # Canonical copy rejects non-JSON inputs/nonfinite numbers and preserves types.
    encoded = canonical(data)
    if len(encoded.encode('utf-8')) > 4096: raise ValueError('reference_input_too_large')
    data = strict_json(encoded)
    if reference_id == 'workload_summary_v1':
        records = _records(data, 'tasks', ('id', 'team', 'minutes', 'done'))
        teams = {}
        for record in records:
            team = _text(record['team']); minutes = _integer(record['minutes'], 0, 1000000)
            done = _boolean(record['done'])
            item = teams.setdefault(team, {'team':team, 'task_count':0, 'open_count':0,
                                          'total_minutes':0, 'open_minutes':0})
            item['task_count'] += 1; item['total_minutes'] += minutes
            if not done: item['open_count'] += 1; item['open_minutes'] += minutes
        rows = [teams[key] for key in sorted(teams)]
        return {'task_count':len(records), 'total_minutes':sum(row['total_minutes'] for row in rows),
                'open_minutes':sum(row['open_minutes'] for row in rows), 'teams':rows}
    if reference_id == 'ticket_priority_v1':
        records = _records(data, 'tickets', ('id', 'severity', 'age_hours', 'blocked'))
        rows = []
        for record in records:
            score = (_integer(record['severity'], 1, 5)*100 + min(_integer(record['age_hours'], 0, 87600), 168)
                     + (50 if _boolean(record['blocked']) else 0))
            rows.append({'id':record['id'], 'score':score,
                         'priority':'urgent' if score >= 500 else 'high' if score >= 300 else 'normal'})
        return {'tickets':sorted(rows, key=lambda row:(-row['score'], row['id']))}
    records = _records(data, 'sources', ('id', 'title', 'url', 'tags'))
    rows = []; index = {}
    for record in records:
        _text(record['title']); _text(record['url'], 500)
        tags = record['tags']
        if not isinstance(tags, list) or len(tags) > 16: raise ValueError('invalid_reference_tags')
        for tag in tags: _text(tag)
        if len(set(tags)) != len(tags): raise ValueError('duplicate_reference_tag')
        rows.append({**record, 'tags':sorted(tags)})
        for tag in tags: index.setdefault(tag, []).append(record['id'])
    return {'source_count':len(records), 'sources':sorted(rows, key=lambda row:row['id']),
            'tag_index':[{'tag':tag, 'source_ids':sorted(index[tag])} for tag in sorted(index)]}
