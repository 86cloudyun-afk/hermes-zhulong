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


def policy_config(root):
    return {'enabled': True, 'mission': 'Improve the observed work within configured contracts',
            'workspace_roots': [str(root)], 'api_url': 'http://127.0.0.1:8642',
            'api_identity_version': 'test-v1', 'sources': [
                {'id': 'code-facts', 'domain': 'code', 'path': str(root / 'facts.json'),
                 'contracts': {'result': {'type': 'file_contains', 'path': str(root / 'result.txt'),
                                         'text': 'done', 'require_change': True}}}]}
