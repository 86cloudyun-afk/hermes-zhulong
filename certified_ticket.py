"""Total, effect-free ticket expressions and checked complete interval certificates.

Soundness argument (reviewed mathematics, not a machine-formalized theorem):
Each checked cell denotes all integer ages in its closed interval. Induction on
an expression derives its affine value, uniform Boolean, or constant text;
linear extrema occur at endpoints even for negative slopes. A min/if rule is
used only after establishing its choice throughout the cell. The independent
score/priority relations then hold throughout each cell. Exact disjoint cover
extends this to all 876010 numeric rows. All syntax branches are typed first.
Evaluation decreases finite AST structure; mapping and insertion sort decrease
finite list/prefix lengths. The fixed wrapper preserves IDs and gives the unique
(-score, Unicode ID) order. Parser, checker, interpreter, wrapper, Python integer/
string semantics, and protected deployment remain trusted. Hashes identify code;
they do not establish its soundness or an arbitrary Python program's correctness.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

REFERENCE = 'ticket_priority_v1'
PROGRAM_LIMIT = 16384
CERTIFICATE_LIMIT = 65536
BUNDLE_LIMIT = 6000
SEMANTICS = {'version':1,'language':'typed_ticket_affine','integers':'mathematical',
             'min':'left_on_equal','guard':'ge','evaluation':'selected_if_branch',
             'list_wrapper':'insertion_sort_desc_score_unicode_id'}
DOMAIN = {'version':1,'severity':[1,5],'age_hours':[0,87600],'blocked':[False,True],
          'rows':876010,'list_max':64,'input_bytes':4096,'input_depth':32,
          'id_max':200,'id_nonwhitespace':True,'unique_ids':True,
          'fields':['id','severity','age_hours','blocked'],'root':'tickets'}
SPEC = {'id':REFERENCE,'version':1,'score':'100*severity+min(age_hours,168)+50*blocked',
        'priority':[['urgent',500],['high',300],['normal',None]]}


class ResourceLimit(ValueError):
    pass


def canonical_bytes(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode('utf-8')


def sha256(value):
    return hashlib.sha256(value).hexdigest()


def _depth(value,depth=0,limit=28):
    if depth>limit:raise ResourceLimit('json_depth_limit')
    if isinstance(value,dict):
        for item in value.values():_depth(item,depth+1,limit)
    elif isinstance(value,list):
        for item in value:_depth(item,depth+1,limit)


def strict_load(raw,limit=PROGRAM_LIMIT,depth=28):
    if type(raw) is not bytes:raise ValueError('bytes_required')
    if len(raw)>limit:raise ResourceLimit('raw_byte_limit')
    def pairs(items):
        result={}
        for key,value in items:
            if key in result:raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    def integer(text):
        if len(text)>8:raise ResourceLimit('integer_text_limit')
        return int(text)
    def invalid(_):raise ValueError('noninteger_json_number')
    try:
        value=json.loads(raw.decode('utf-8'),object_pairs_hook=pairs,parse_int=integer,
                         parse_float=invalid,parse_constant=invalid)
    except RecursionError:raise ResourceLimit('json_depth_limit') from None
    _depth(value,limit=depth)
    return value


def _fields(value,names):
    if type(value) is not dict or set(value)!=set(names):raise ValueError('invalid_fields')


def _int(value,lo=-1000000,hi=1000000):
    if type(value) is not int:raise ValueError('integer_required')
    if not lo<=value<=hi:raise ValueError('integer_out_of_domain')
    return value


def _ast(node,kind,score_allowed,work,depth=0):
    if depth>24:raise ResourceLimit('ast_depth_limit')
    work['ast_nodes']+=1
    if work['ast_nodes']>256:raise ResourceLimit('ast_node_limit')
    if type(node) is not list or not node or type(node[0]) is not str:raise ValueError('invalid_expression')
    op=node[0];args=node[1:]
    if op=='if':
        if kind=='bool':raise ValueError('unsupported_boolean_if')
        if len(args)!=3:raise ValueError('invalid_arity')
        return (op,_ast(args[0],'bool',score_allowed,work,depth+1),
                _ast(args[1],kind,score_allowed,work,depth+1),_ast(args[2],kind,score_allowed,work,depth+1))
    leaves={'int':('int',1),'severity':('int',0),'age':('int',0),'score':('int',0),
            'blocked':('bool',0),'text':('text',1)}
    if op in leaves:
        expected,count=leaves[op]
        if kind!=expected or len(args)!=count:raise ValueError('invalid_type_or_arity')
        if op=='score' and not score_allowed:raise ValueError('recursive_score')
        if op=='int':_int(args[0])
        if op=='text' and args[0] not in ('urgent','high','normal'):raise ValueError('invalid_priority_text')
        return tuple(node)
    if op=='ge' and kind=='bool' and len(args)==2:
        return (op,*(_ast(a,'int',score_allowed,work,depth+1) for a in args))
    if kind=='int':
        if op=='add' and len(args)>=2:
            return (op,*(_ast(a,'int',score_allowed,work,depth+1) for a in args))
        if op=='mul' and len(args)==2:
            return (op,_int(args[0]),_ast(args[1],'int',score_allowed,work,depth+1))
        if op=='min' and len(args)==2:
            return (op,*(_ast(a,'int',score_allowed,work,depth+1) for a in args))
    raise ValueError('unsupported_opcode_type_or_arity')


def _extrema(pair,lo,hi):
    values=(pair[0]*lo+pair[1],pair[0]*hi+pair[1])
    return min(values),max(values)


def _subtract(left,right):return left[0]-right[0],left[1]-right[1]


def _derive(node,cell,score,work):
    work['rule_applications']+=1
    op=node[0]
    if op=='int':return (0,node[1])
    if op=='severity':return (0,cell['severity'])
    if op=='age':return (1,0)
    if op=='score':return score
    if op=='blocked':return cell['blocked']
    if op=='text':return node[1]
    if op=='if':
        branch=2 if _derive(node[1],cell,score,work) else 3
        return _derive(node[branch],cell,score,work)
    if op=='mul':
        a,b=_derive(node[2],cell,score,work);return (node[1]*a,node[1]*b)
    if op=='add':
        values=[_derive(n,cell,score,work) for n in node[1:]]
        return sum(v[0] for v in values),sum(v[1] for v in values)
    left=_derive(node[1],cell,score,work);right=_derive(node[2],cell,score,work)
    low,high=_extrema(_subtract(left,right),cell['lo'],cell['hi'])
    if op=='ge':
        if low>=0:return True
        if high<0:return False
    if op=='min':
        if high<=0:return left
        if low>=0:return right
    raise ValueError('nonuniform_cell')


def _equal_on_cell(left,right,cell):
    return _extrema(_subtract(left,right),cell['lo'],cell['hi'])==(0,0)


def _check(program_bytes,certificate_bytes,expected_reference,report):
    if expected_reference!=REFERENCE:raise ValueError('unsupported_reference')
    p=strict_load(program_bytes);c=strict_load(certificate_bytes,CERTIFICATE_LIMIT)
    report['program_hash']=sha256(canonical_bytes(p));report['certificate_hash']=sha256(canonical_bytes(c))
    _fields(p,('schema','kind','score','priority'));_fields(c,('schema','kind','cells'))
    for value in (p,c):
        if type(value['schema']) is not int or value['schema']!=1 or value['kind']!=REFERENCE:raise ValueError('unsupported_schema_or_kind')
    work=report['work'];score_ast=_ast(p['score'],'int',False,work);priority_ast=_ast(p['priority'],'text',True,work)
    if type(c['cells']) is not list:raise ValueError('invalid_cells')
    if len(c['cells'])>512:raise ResourceLimit('cell_limit')
    groups={(s,b):[] for s in range(1,6) for b in (False,True)}
    for cell in c['cells']:
        _fields(cell,('severity','blocked','lo','hi','score_affine','priority'))
        _int(cell['severity'],1,5);_int(cell['lo'],0,87600);_int(cell['hi'],cell['lo'],87600)
        if type(cell['blocked']) is not bool:raise ValueError('boolean_required')
        if type(cell['score_affine']) is not list or len(cell['score_affine'])!=2:raise ValueError('invalid_affine_witness')
        for coefficient in cell['score_affine']:_int(coefficient)
        if cell['priority'] not in ('urgent','high','normal'):raise ValueError('invalid_priority_witness')
        groups[(cell['severity'],cell['blocked'])].append(cell)
    # Coverage is independent of witness ordering and proof-rule success.
    for cells in groups.values():
        next_age=0
        for cell in sorted(cells,key=lambda item:item['lo']):
            if cell['lo']!=next_age:raise ValueError('incomplete_or_overlapping_cover')
            next_age=cell['hi']+1
        if next_age!=87601:raise ValueError('incomplete_or_overlapping_cover')
    for cell in c['cells']:
        score=_derive(score_ast,cell,None,work)
        if cell['hi']<168:reference=(1,100*cell['severity']+50*cell['blocked'])
        elif cell['lo']>=168:reference=(0,100*cell['severity']+50*cell['blocked']+168)
        else:raise ValueError('reference_nonuniform_cell')
        if not _equal_on_cell(score,reference,cell):raise ValueError('score_relation_failed')
        if not _equal_on_cell(score,cell['score_affine'],cell):raise ValueError('affine_witness_failed')
        priority=_derive(priority_ast,cell,score,work)
        low,high=_extrema(reference,cell['lo'],cell['hi'])
        valid=(priority=='urgent' and low>=500 or priority=='high' and low>=300 and high<500
               or priority=='normal' and high<300)
        if not valid or priority!=cell['priority']:raise ValueError('priority_relation_failed')
        work['cells_checked']+=1;work['covered_rows']+=cell['hi']-cell['lo']+1
    return score_ast,priority_ast


def _verified(program_bytes,certificate_bytes,expected_reference):
    report={'status':'rejected','reasons':[],
            'program_hash':None,'certificate_hash':None,
            'semantics_hash':sha256(canonical_bytes(SEMANTICS)),
            'domain_hash':sha256(canonical_bytes(DOMAIN)),
            'reference_hash':sha256(canonical_bytes(SPEC)),'checker_hash':None,
            'proof_method':'complete_integer_interval_certificate',
            'checker_soundness':'reviewed_argument_not_machine_formalized',
            'trust':['fixed_specification_domain','strict_parser_checker','same_ast_interpreter',
                     'fixed_insertion_sort_wrapper','python_integer_unicode_runtime','protected_code_and_hashes'],
            'work':{'ast_nodes':0,'cells_checked':0,'covered_rows':0,'rule_applications':0}}
    ast=None
    try:
        report['checker_hash']=sha256(Path(__file__).read_bytes())
        ast=_check(program_bytes,certificate_bytes,expected_reference,report)
        report['status']='certified_within_scope'
    except (ResourceLimit,RecursionError,MemoryError,OSError) as exc:
        report['status']='unavailable';report['reasons']=[str(exc)[:120] or type(exc).__name__]
    except (ValueError,TypeError,UnicodeError) as exc:
        report['reasons']=[str(exc)[:120] or type(exc).__name__]
    return report,ast


def verify_ticket_certificate(program_bytes,certificate_bytes,*,expected_reference=REFERENCE):
    """Return derived evidence, never an authorization token accepted by execution."""
    return _verified(program_bytes,certificate_bytes,expected_reference)[0]


def validate_ticket_input(input_data):
    """Independent exact reference domain, including canonical byte limit."""
    try:raw=canonical_bytes(input_data)
    except (TypeError,ValueError,RecursionError,UnicodeError):raise ValueError('invalid_ticket_input') from None
    data=strict_load(raw,4096,32)
    _fields(data,('tickets',));rows=data['tickets']
    if type(rows) is not list or len(rows)>64:raise ValueError('invalid_ticket_list')
    ids=set()
    for row in rows:
        _fields(row,('id','severity','age_hours','blocked'))
        sid=row['id']
        if type(sid) is not str or not sid.strip() or len(sid)>200 or sid in ids:raise ValueError('invalid_ticket_id')
        ids.add(sid);_int(row['severity'],1,5);_int(row['age_hours'],0,87600)
        if type(row['blocked']) is not bool:raise ValueError('boolean_required')
    return data


def _eval(node,row,score=None):
    op=node[0]
    if op in ('int','text'):return node[1]
    if op=='severity':return row['severity']
    if op=='age':return row['age_hours']
    if op=='score':return score
    if op=='blocked':return row['blocked']
    if op=='if':return _eval(node[2] if _eval(node[1],row,score) else node[3],row,score)
    if op=='add':return sum(_eval(n,row,score) for n in node[1:])
    if op=='mul':return node[1]*_eval(node[2],row,score)
    left=_eval(node[1],row,score);right=_eval(node[2],row,score)
    if op=='min':return left if left<=right else right
    if op=='ge':return left>=right
    raise ValueError('invalid_internal_ast')


def execute_ticket_program(program_bytes,certificate_bytes,input_data):
    """Recheck exact immutable bytes, then interpret that same parsed AST."""
    report,ast=_verified(program_bytes,certificate_bytes,REFERENCE)
    if report['status']!='certified_within_scope':raise ValueError('ticket_program_'+report['status'])
    data=validate_ticket_input(input_data);rows=[]
    for row in data['tickets']:
        score=_eval(ast[0],row);result={'id':row['id'],'score':score,'priority':_eval(ast[1],row,score)}
        index=len(rows)
        rows.append(result)
        while index>0 and (-result['score'],result['id'])<(-rows[index-1]['score'],rows[index-1]['id']):
            rows[index]=rows[index-1];index-=1
        rows[index]=result
    return {'tickets':rows}
