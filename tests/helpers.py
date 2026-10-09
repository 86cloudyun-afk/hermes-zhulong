import hashlib
import json


def make_goal(ledger, now=1000.0, domain='code', source_revision='r1'):
    contract = {'type': 'file_contains', 'path': '/tmp/result', 'text': 'done', 'require_change': True}
    return ledger.create_goal(
        {'source_id': 'source-'+domain, 'contract_id': 'result', 'domain': domain,
         'objective': 'Create verified '+domain+' result', 'reason': 'Observed missing result',
         'confidence': 0.7, 'expected_benefit': 0.5},
        source_revision, contract, {'verdict': False, 'artifact_hash': None}, now, 600)


def evidence(goal, verdict=True):
    return {'verdict': verdict, 'contract_hash': goal['contract_hash'], 'artifact_hash': 'fresh', 'reason': 'checked'}
