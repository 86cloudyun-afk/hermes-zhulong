"""Protected configuration authority for certified immutable execution intents.

Settings are trusted control state, not candidate-supplied attestations. The
admission gate reads them inside Ledger's reservation transaction. Existing
submissions reconcile before this gate, so unavailable proof services never
rewrite old immutable requests or prevent their retirement.
"""
from __future__ import annotations

import json

try:
    from .autonomy_store import canonical,digest
    from .skill_evaluator import strict_json
    from . import certified_ticket as kernel
    from . import task_inputs
except ImportError:
    from autonomy_store import canonical,digest
    from skill_evaluator import strict_json
    import certified_ticket as kernel
    import task_inputs

HASH_FIELDS=('program_hash','certificate_hash','semantics_hash','domain_hash','reference_hash','checker_hash')


def normalize_program_bundle(raw,*,contract):
    if (contract.get('type')!='json_reference' or contract.get('reference_id')!=kernel.REFERENCE
        or type(contract.get('reference_version')) is not int or contract['reference_version']!=1):
        raise ValueError('unsupported_certified_contract')
    if type(raw) is not dict or set(raw)!={'schema','program','certificate'} or type(raw['schema']) is not int or raw['schema']!=1:
        raise ValueError('invalid_program_bundle')
    # Canonical copy protects against later mutation and bounds the inline intent.
    encoded=kernel.canonical_bytes(raw)
    if len(encoded)>kernel.BUNDLE_LIMIT:raise ValueError('program_bundle_too_large')
    result=kernel.strict_load(encoded,kernel.BUNDLE_LIMIT,28)
    checked=bundle_report(result)
    if checked['status']!='certified_within_scope':raise ValueError('program_bundle_'+checked['status'])
    return result


def bundle_report(bundle):
    return kernel.verify_ticket_certificate(kernel.canonical_bytes(bundle['program']),kernel.canonical_bytes(bundle['certificate']))


def validate_source(source):
    if any('program_bundle' in contract for contract in source['contracts'].values()):
        rule=task_inputs.rule_for(source)
        if rule is None or rule['fields']!=['tickets']:raise ValueError('certified_ticket_projection_required')


def configure(ledger,sources,authoritative_execution_identity):
    entries={}
    for source in sources:
        # Legacy Controllers may receive source selectors without contracts.
        if not any('program_bundle' in contract for contract in source.get('contracts',{}).values()):continue
        entry={'contracts':{},'source_path':source['path'],'rule':task_inputs.rule_for(source),'status':'ready'}
        try:
            validate_source(source)
            for cid,contract in source['contracts'].items():
                item={'contract_hash':digest(contract)}
                if 'program_bundle' in contract:
                    normalized=normalize_program_bundle(contract['program_bundle'],contract=contract)
                    report=bundle_report(normalized)
                    item['hashes']={key:report[key] for key in HASH_FIELDS}
                entry['contracts'][cid]=item
        except (ValueError,TypeError,KeyError,OSError):
            # New admission fails closed; already admitted requests can retire.
            entry['status']='unavailable'
        entries[source['id']]=entry
    registry={'schema':1,'sources':entries,'execution_identity':authoritative_execution_identity}
    with ledger._connection(True) as c:
        c.execute("INSERT INTO settings VALUES('certified_registry',?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",(canonical(registry),))


def program_binding(goal,execution_identity):
    contract=goal['contract']
    if 'program_bundle' not in contract:return None
    if goal.get('workflow') is not None:raise ValueError('certified_workflow_unsupported')
    bundle=normalize_program_bundle(contract['program_bundle'],contract=contract)
    snapshot=goal.get('task_input')
    if snapshot is None:raise ValueError('certified_input_required')
    task_inputs._validated(snapshot);kernel.validate_ticket_input(snapshot['data'])
    if (snapshot['source_id']!=goal['source_id'] or snapshot['source_revision']!=goal['source_revision']
        or digest(contract)!=goal['contract_hash']):raise ValueError('certified_goal_scope_mismatch')
    report=bundle_report(bundle)
    if report['status']!='certified_within_scope':raise ValueError('certified_checker_unavailable')
    return {'schema':1,'goal_id':goal['id'],'source_id':goal['source_id'],
            'source_revision':goal['source_revision'],'contract_id':goal['contract_id'],
            'contract_hash':goal['contract_hash'],'input_hash':snapshot['input_hash'],'rule_hash':snapshot['rule_hash'],
            'reference_id':contract['reference_id'],'reference_version':contract['reference_version'],
            'execution_identity_hash':digest(execution_identity),**{key:report[key] for key in HASH_FIELDS}}


def valid_program_binding(c,goal,execution_identity,request):
    """Validate independent current authority before any reservation side effects."""
    certified='program_bundle' in goal['contract']
    try:
        row=c.execute("SELECT value FROM settings WHERE key='certified_registry'").fetchone()
        registry=json.loads(row[0]) if row else None
        source=registry['sources'].get(goal['source_id']) if registry else None
        if (certified or source is not None) and len(request['input'].encode())>16384:return False
        try:intent=strict_json(request['input'],max_depth=task_inputs.INPUT_ENVELOPE_DEPTH)
        except (ValueError,TypeError,KeyError,UnicodeError):return not certified and source is None
        supplied=isinstance(intent,dict) and ('program_binding' in intent or 'program_bundle' in intent
                    or 'program_bundle' in intent.get('acceptance_contract',{}))
        if source is None and not certified and not supplied:return True
        if not registry or type(registry['schema']) is not int or registry['schema']!=1 or source is None:return False
        if source['status']!='ready':return False
        current=source['contracts'].get(goal['contract_id'])
        if current is None or current['contract_hash']!=goal['contract_hash'] or digest(goal['contract'])!=goal['contract_hash']:return False
        required='hashes' in current
        if not required:return not certified and not supplied
        if not certified or canonical(execution_identity)!=canonical(registry['execution_identity']):return False
        if type(request) is not dict or set(request)!={'input','session_id'} or request['session_id']!='zhulong-'+goal['id']:return False
        if len(request['input'].encode())>16384 or not isinstance(intent,dict) or 'program_bundle' in intent:return False
        if canonical(intent.get('acceptance_contract'))!=canonical(goal['contract']):return False
        if intent.get('source_path')!=source['source_path']:return False
        frozen=task_inputs.binding(c,goal['id'])
        if frozen is None or canonical(intent.get('task_input'))!=canonical(frozen) or canonical(goal['task_input'])!=canonical(frozen):return False
        if frozen['rule_hash']!=digest(source['rule']):return False
        metadata=program_binding(goal,execution_identity)
        return (canonical(intent.get('program_binding'))==canonical(metadata)
                and all(metadata[key]==current['hashes'][key] for key in HASH_FIELDS))
    except (ValueError,TypeError,KeyError,AttributeError,OSError,RecursionError):
        return False
