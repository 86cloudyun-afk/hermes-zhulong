import copy
import importlib
import importlib.util
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from autonomy_checks import Verifier, contract_policy
from autonomy_store import canonical, digest
from skill_evaluator import validate_skills
from task_inputs import project
from test_skill_evaluator import task, sources


class ReferenceTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('work_reference'),'trusted business references missing')
        self.m=importlib.import_module('work_reference')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)
        self.policy={'base':str(self.root),'workspace_roots':[str(self.root)]}
        self.contract={'type':'json_reference','path':str(self.root/'out.json'),
                       'reference_id':'workload_summary_v1','reference_version':1,'require_change':True,'safe_retry':True}
        self.data={'tasks':[{'id':'b','team':'ops','minutes':20,'done':False},
                            {'id':'a','team':'dev','minutes':10,'done':True}]}
        self.source={'id':'source','input_fields':['tasks'],'persist_input_fields':['tasks']}
        self.binding={**project(self.source,self.data),'source_revision':'revision-1'}

    def test_workload_summary_aggregates_and_sorts_teams(self):
        before=copy.deepcopy(self.data)
        self.assertEqual(self.m.reference_output('workload_summary_v1',self.data),
            {'task_count':2,'total_minutes':30,'open_minutes':20,'teams':[
                {'team':'dev','task_count':1,'open_count':0,'total_minutes':10,'open_minutes':0},
                {'team':'ops','task_count':1,'open_count':1,'total_minutes':20,'open_minutes':20}]})
        self.assertEqual(self.data,before)

    def test_ticket_priority_and_ties_use_id_order(self):
        data={'tickets':[{'id':'b','severity':3,'age_hours':200,'blocked':False},
                         {'id':'a','severity':3,'age_hours':500,'blocked':False},
                         {'id':'c','severity':5,'age_hours':0,'blocked':True}]}
        self.assertEqual(self.m.reference_output('ticket_priority_v1',data),{'tickets':[
            {'id':'c','score':550,'priority':'urgent'},{'id':'a','score':468,'priority':'high'},
            {'id':'b','score':468,'priority':'high'}]})

    def test_source_index_sorts_sources_and_tag_cross_references(self):
        data={'sources':[{'id':'b','title':'B','url':'https://b','tags':['z','a']},
                         {'id':'a','title':'A','url':'https://a','tags':['z']}]}
        self.assertEqual(self.m.reference_output('source_index_v1',data),{'source_count':2,
            'sources':[data['sources'][1],{**data['sources'][0],'tags':['a','z']}],
            'tag_index':[{'tag':'a','source_ids':['b']},{'tag':'z','source_ids':['a','b']}]})

    def test_reference_rejects_wrong_types_duplicates_and_unknown_fields(self):
        for patch in [{'minutes':True},{'minutes':1.0},{'minutes':-1},{'minutes':1000001},
                      {'done':1},{'id':''},{'team':'x'*201},{'extra':1}]:
            bad=copy.deepcopy(self.data);bad['tasks'][0].update(patch)
            with self.subTest(patch=patch),self.assertRaises(ValueError):self.m.reference_output('workload_summary_v1',bad)
        bad=copy.deepcopy(self.data);bad['tasks'][1]['id']='b'
        with self.assertRaises(ValueError):self.m.reference_output('workload_summary_v1',bad)
        for reference in ['missing',None]:
            with self.assertRaises(ValueError):self.m.reference_output(reference,self.data)

    def test_verifier_uses_frozen_input_and_exact_complete_output(self):
        verifier=Verifier(self.policy)
        baseline=verifier.capture(self.contract,self.binding)
        self.assertIs(baseline['verdict'],False)
        expected=self.m.reference_output('workload_summary_v1',self.data)
        (self.root/'out.json').write_text(canonical(expected))
        result=verifier.check(self.contract,baseline,self.binding)
        self.assertIs(result['verdict'],True)
        self.assertEqual(result['input_hash'],digest(self.data))
        self.assertEqual(result['check_version'],2)
        expected['total_minutes']=30.0
        (self.root/'out.json').write_text(canonical(expected))
        self.assertIs(verifier.capture(self.contract,self.binding)['verdict'],False)

    def test_binding_missing_mutated_or_bad_metadata_and_versions_are_unknown(self):
        (self.root/'out.json').write_text(canonical(self.m.reference_output('workload_summary_v1',self.data)))
        for change in [{'input_hash':'wrong'},{'rule_hash':'wrong'},{'size':True},{'size':999},
                       {'data':{'tasks':[]}},{'schema':True},{'source_revision':''}]:
            with self.subTest(change=change):
                self.assertEqual(Verifier(self.policy).capture(self.contract,dict(self.binding,**change))['verdict'],'unknown')
        self.assertEqual(Verifier(self.policy).capture(self.contract)['verdict'],'unknown')
        for version in [2,True,'1']:
            with self.subTest(version=version):
                self.assertEqual(Verifier(self.policy).capture(dict(self.contract,reference_version=version),self.binding)['verdict'],'unknown')
        baseline=Verifier(self.policy).capture(self.contract,self.binding)
        bad=dict(self.binding,input_hash='wrong')
        self.assertEqual(Verifier(self.policy).check(self.contract,baseline,bad)['verdict'],'unknown')

    def test_changed_business_input_uses_same_contract_without_answer_disclosure(self):
        first=Verifier(self.policy).capture(self.contract,self.binding)
        data={'tasks':[{'id':'c','team':'ops','minutes':7,'done':False}]}
        bound={**project(self.source,data),'source_revision':'revision-2'}
        (self.root/'out.json').write_text(canonical(self.m.reference_output('workload_summary_v1',data)))
        second=Verifier(self.policy).capture(self.contract,bound)
        self.assertEqual(first['contract_hash'],second['contract_hash'])
        self.assertNotEqual(first['input_hash'],second['input_hash'])
        self.assertIs(second['verdict'],True)
        self.assertNotIn('data',second)
        for reference in self.m.REFERENCE_IDS:
            self.assertIsInstance(self.m.reference_instructions(reference),str)
            self.assertNotIn(canonical(data),self.m.reference_instructions(reference))

    def test_reference_whole_artifact_rejects_extra_duplicate_and_nonfinite_fields(self):
        expected=canonical(self.m.reference_output('workload_summary_v1',self.data))
        for tail in [',"extra":0}',',"extra":1e999}',',"task_count":2}']:
            (self.root/'out.json').write_text(expected[:-1]+tail)
            result=Verifier(self.policy).capture(self.contract,self.binding)
            self.assertEqual(result['verdict'],False if tail==',"extra":0}' else 'unknown')

    def test_ticket_and_source_bounds_and_empty_inputs(self):
        self.assertEqual(self.m.reference_output('workload_summary_v1',{'tasks':[]}),
                         {'task_count':0,'total_minutes':0,'open_minutes':0,'teams':[]})
        self.assertEqual(self.m.reference_output('ticket_priority_v1',{'tickets':[]}),{'tickets':[]})
        self.assertEqual(self.m.reference_output('source_index_v1',{'sources':[]}),
                         {'source_count':0,'sources':[],'tag_index':[]})
        ticket={'id':'a','severity':1,'age_hours':0,'blocked':False}
        for patch in [{'severity':0},{'severity':6},{'severity':True},{'severity':1.0},
                      {'age_hours':-1},{'age_hours':87601},{'blocked':0}]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                self.m.reference_output('ticket_priority_v1',{'tickets':[{**ticket,**patch}]})
        source={'id':'a','title':'A','url':'https://a','tags':[]}
        for patch in [{'tags':['a','a']},{'tags':[1]},{'tags':[' ']},
                      {'tags':[str(i) for i in range(17)]},{'url':'a'*501},{'title':''}]:
            with self.subTest(patch=patch),self.assertRaises(ValueError):
                self.m.reference_output('source_index_v1',{'sources':[{**source,**patch}]})
        for data in [{'tickets':[dict(ticket,id=str(i)) for i in range(65)]},
                     {'tickets':[ticket],'extra':0}]:
            with self.assertRaises(ValueError):self.m.reference_output('ticket_priority_v1',data)

    def test_manifest_wrapper_does_not_reduce_business_depth(self):
        nested=0
        for _ in range(32):nested=[nested]
        raw=task();raw['examples']=[{'input':nested,'output':nested}]
        normalized=validate_skills([raw],sources())[0]
        self.assertEqual(normalized['examples'][0]['input'],nested)
        nested=[nested];raw['examples']=[{'input':nested,'output':0}]
        with self.assertRaises(ValueError):validate_skills([raw],sources())


if __name__=='__main__':unittest.main()
