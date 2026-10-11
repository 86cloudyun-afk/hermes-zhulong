"""Independent test producers; never imported by the trusted checker."""
import copy
import importlib.util
import json
import unittest


def encoded(x):
    return json.dumps(x,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()


def program(alternative=False):
    score=['add',['mul',100,['severity']],['min',['age'],['int',168]],['if',['blocked'],['int',50],['int',0]]]
    if alternative:
        score=['add',['mul',50,['severity']],['mul',50,['severity']],
               ['if',['ge',['int',167],['age']],['age'],['int',168]],['if',['blocked'],['int',50],['int',0]]]
    return {'schema':1,'kind':'ticket_priority_v1','score':score,
            'priority':['if',['ge',['score'],['int',500]],['text','urgent'],
                        ['if',['ge',['score'],['int',300]],['text','high'],['text','normal']]]}


def certificate():
    cells=[]
    for s in range(1,6):
        for b in (False,True):
            base=100*s+50*b
            cuts=sorted({0,168,87601}|{t-base for t in (300,500) if 0<t-base<168})
            for lo,end in zip(cuts,cuts[1:]):
                score=base+min(lo,168)
                cells.append({'severity':s,'blocked':b,'lo':lo,'hi':end-1,
                              'score_affine':[1,base] if lo<168 else [0,base+168],
                              'priority':'urgent' if score>=500 else 'high' if score>=300 else 'normal'})
    return {'schema':1,'kind':'ticket_priority_v1','cells':cells}


def bundle():return {'schema':1,'program':program(),'certificate':certificate()}


class CertifiedTicketTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('certified_ticket'),'total certificate kernel missing')
        import certified_ticket
        self.k=certified_ticket

    def verify(self,p=None,c=None):
        return self.k.verify_ticket_certificate(encoded(program() if p is None else p),encoded(certificate() if c is None else c))

    def test_complete_cover_and_distinct_equivalent_program(self):
        for p in (program(),program(True)):
            r=self.verify(p);self.assertEqual(r['status'],'certified_within_scope',r)
            self.assertEqual(r['work']['covered_rows'],876010);self.assertEqual(r['work']['cells_checked'],26)
            self.assertGreater(r['work']['rule_applications'],26);self.assertGreater(r['work']['ast_nodes'],1)
            self.assertEqual(r['checker_soundness'],'reviewed_argument_not_machine_formalized')
            for k in ('program_hash','certificate_hash','semantics_hash','domain_hash','reference_hash','checker_hash'):
                self.assertRegex(r[k],r'^[0-9a-f]{64}$')
        self.assertNotEqual(self.verify()['program_hash'],self.verify(program(True))['program_hash'])

    def test_score_threshold_and_witness_tampering(self):
        p=program();p['score'][1][1]=99;self.assertEqual(self.verify(p)['status'],'rejected')
        p=program();p['priority'][1][2][1]=501;self.assertEqual(self.verify(p)['status'],'rejected')
        for key,value in (('score_affine',[1,101]),('priority','urgent')):
            c=certificate();c['cells'][0][key]=value;self.assertEqual(self.verify(c=c)['status'],'rejected')

    def test_cover_gap_overlap_duplicate_domain_and_strict_types(self):
        variants=[]
        for field,value in (('lo',1),('hi',168),('severity',6),('severity',True),('blocked',0),('extra',True)):
            c=certificate();c['cells'][0][field]=value;variants.append(c)
        c=certificate();c['cells'].pop();variants.append(c)
        c=certificate();c['cells'].append(copy.deepcopy(c['cells'][0]));variants.append(c)
        c=certificate();c['domain']={'max_age':167};variants.append(c)
        for c in variants:self.assertEqual(self.verify(c=c)['status'],'rejected')

    def test_negative_slopes_min_ties_singletons(self):
        p=program();p['score'][2]=['mul',-1,['min',['mul',-1,['age']],['int',-168]]]
        self.assertEqual(self.verify(p)['status'],'rejected')
        p=program(True);p['score'][3]=['if',['ge',['mul',-1,['age']],['int',-168]],['age'],['int',168]]
        c=certificate()
        for cell in list(c['cells']):
            if cell['lo']==168:
                old=copy.deepcopy(cell);old['lo']=169;cell['hi']=168;c['cells'].append(old)
        self.assertEqual(self.verify(p,c)['status'],'certified_within_scope')
        cell=next(x for x in c['cells'] if x['lo']==168);cell['score_affine']=[1,cell['score_affine'][1]-168]
        self.assertEqual(self.verify(p,c)['status'],'certified_within_scope')

    def test_unreachable_illegal_branches_types_arity_recursion(self):
        for expr in (['call','print'],['int',True],['mul',True,['age']],['add',['int',1]],
                     ['age',1],['if',['int',1],['int',2],['int',3]],['score']):
            p=program();p['score']=['if',['ge',['severity'],['int',0]],p['score'],expr]
            with self.subTest(expr=expr):self.assertEqual(self.verify(p)['status'],'rejected')
        p=program();p['priority']=['text','root'];self.assertEqual(self.verify(p)['status'],'rejected')

    def test_nonuniform_cells_are_not_endpoint_samples(self):
        p=program();p['score']=['if',['ge',['age'],['int',23]],p['score'],
                              ['add',p['score'],['if',['ge',['age'],['int',1]],['int',1],['int',0]]]]
        self.assertEqual(self.verify(p)['status'],'rejected')

    def test_strict_json_canonical_identity_and_bounded_resources(self):
        p=encoded(program());c=encoded(certificate());r=self.k.verify_ticket_certificate(p,c)
        self.assertEqual(r['program_hash'],self.k.verify_ticket_certificate(json.dumps(program(),indent=2).encode(),c)['program_hash'])
        for bad in (p.replace(b'"schema":1',b'"schema":1,"schema":1'),p.replace(b'100',b'1e999'),p.replace(b'100',b'NaN'),p.replace(b'100',b'100.0')):
            self.assertEqual(self.k.verify_ticket_certificate(bad,c)['status'],'rejected')
        for bad in (b' '*16385,p.replace(b'100',b'9'*5000)):
            self.assertEqual(self.k.verify_ticket_certificate(bad,c)['status'],'unavailable')
        deep=['age']
        for _ in range(25):deep=['mul',1,deep]
        p1=program();p1['score']=deep;self.assertEqual(self.verify(p1)['status'],'unavailable')
        p1=program();p1['score']=['add']+[['int',1]]*256;self.assertEqual(self.verify(p1)['status'],'unavailable')
        c1=certificate();c1['cells']*=20;self.assertEqual(self.verify(c=c1)['status'],'unavailable')
        self.assertEqual(self.k.verify_ticket_certificate(p,c,expected_reference='other')['status'],'rejected')

    def test_interpreter_boundaries_empty_unicode_and_forged_reports(self):
        from work_reference import reference_output
        p=encoded(program());c=encoded(certificate())
        self.assertEqual(self.k.execute_ticket_program(p,c,{'tickets':[]}),{'tickets':[]})
        for s in range(1,6):
            for b in (False,True):
                data={'tickets':[{'id':str(a),'severity':s,'age_hours':a,'blocked':b} for a in (0,49,50,99,100,149,150,167,168,87600)]}
                self.assertEqual(self.k.execute_ticket_program(p,c,data),reference_output('ticket_priority_v1',data))
        data={'tickets':[{'id':i,'severity':3,'age_hours':0,'blocked':False} for i in ('😀','é','a',' Z','A')]}
        self.assertEqual([r['id'] for r in self.k.execute_ticket_program(p,c,data)['tickets']],sorted(r['id'] for r in data['tickets']))
        with self.assertRaises((ValueError,TypeError)):self.k.execute_ticket_program({'status':'certified_within_scope'},c,data)
        bad=program();bad['score']=['int',1]
        with self.assertRaises(ValueError):self.k.execute_ticket_program(encoded(bad),c,data)

    def test_exact_independent_input_validator(self):
        base={'tickets':[{'id':'one','severity':1,'age_hours':0,'blocked':False}]};invalid=[]
        for k,v in (('id','  '),('id','x'*201),('severity',True),('severity',0),('severity',6),('age_hours',True),('age_hours',87601),('age_hours',-1),('blocked',0),('extra',1)):
            x=copy.deepcopy(base);x['tickets'][0][k]=v;invalid.append(x)
        x=copy.deepcopy(base);x['tickets']*=2;invalid.append(x)
        invalid += [{'tickets':[],'extra':1},{'tickets':[{'id':str(i),'severity':1,'age_hours':0,'blocked':False} for i in range(65)]},
                    {'tickets':[{'id':str(i)+'x'*150,'severity':1,'age_hours':0,'blocked':False} for i in range(25)]}]
        for data in invalid:
            with self.assertRaises(ValueError):self.k.execute_ticket_program(encoded(program()),encoded(certificate()),data)

    def test_boolean_if_is_outside_exact_grammar(self):
        p=program();p['score'][3][1]=['if',['blocked'],['blocked'],['blocked']]
        self.assertEqual(self.verify(p)['status'],'rejected')

    def test_negative_affine_min_derivation_and_largest_legal_list(self):
        from work_reference import reference_output
        p=program();p['score'][2]=['add',['age'],['int',168],['min',['mul',-1,['age']],['int',-168]]]
        self.assertEqual(self.verify(p)['status'],'certified_within_scope')
        data={'tickets':[{'id':str(i),'severity':1,'age_hours':i,'blocked':False} for i in range(64)]}
        self.assertEqual(self.k.execute_ticket_program(encoded(p),encoded(certificate()),data),reference_output('ticket_priority_v1',data))
