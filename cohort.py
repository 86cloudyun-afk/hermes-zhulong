"""Provider-free actual-time observations; no work is launched by this module.

Clock injection is for lifecycle tests only. CLI observations always use the host
clock. Journal hashes assume a trusted owner/filesystem, not a privileged attacker.
"""
from __future__ import annotations
import argparse
from contextlib import contextmanager,closing
import fcntl
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import uuid


def canonical(value):
    return json.dumps(value,sort_keys=True,separators=(',', ':'),ensure_ascii=False,allow_nan=False)


def digest(value): return hashlib.sha256(canonical(value).encode()).hexdigest()


def strict_read(path):
    def pairs(items):
        result={}
        for key,value in items:
            if key in result: raise ValueError('duplicate_json_key')
            result[key]=value
        return result
    raw=Path(path).read_bytes()
    if len(raw)>16*1024*1024: raise ValueError('json_too_large')
    try:return json.loads(raw,object_pairs_hook=pairs,parse_constant=lambda _: (_ for _ in ()).throw(ValueError('nonfinite_json')))
    except (UnicodeError,RecursionError) as exc:raise ValueError('invalid_json') from exc


def durable_json(path,value,*,exclusive=False):
    return durable_bytes(path,(canonical(value)+'\n').encode(),exclusive=exclusive)


def durable_bytes(path,raw,*,exclusive=False):
    path=Path(path)
    target=path if exclusive else path.with_name('.'+path.name+'.'+uuid.uuid4().hex)
    with target.open('xb') as stream:
        os.chmod(target,0o600);stream.write(raw);stream.flush();os.fsync(stream.fileno())
    if not exclusive:os.replace(target,path)
    fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)


def host_clock():
    return {'utc':time.time(),'monotonic':time.monotonic(),
            'boot_id':Path('/proc/sys/kernel/random/boot_id').read_text().strip()}


def stamp(value):
    if not isinstance(value,dict) or set(value)!={'utc','monotonic','boot_id'}:raise ValueError('invalid_clock')
    if any(type(value[k]) not in (int,float) or not math.isfinite(value[k]) or value[k]<0 for k in ('utc','monotonic')):raise ValueError('invalid_clock')
    if not isinstance(value['boot_id'],str) or not re.fullmatch(r'[A-Za-z0-9_-]{1,100}',value['boot_id']):raise ValueError('invalid_boot')
    return dict(value)


class Journal:
    """Single-file append-only events plus external identity and durable head anchor.

    SQLite transactions and a file lock serialize state checks and appends. A
    crash after DB commit but before head update is a verifiable prefix extension.
    Replacing the DB or truncating a previously anchored tail fails closed.
    """
    @classmethod
    def create(cls,root,kind,protocol):
        root=Path(root).absolute();root.mkdir(mode=0o700,parents=True,exist_ok=False)
        if root.resolve()!=root:raise ValueError('journal_path_alias')
        db=root/'journal.db'
        with closing(sqlite3.connect(db)) as c, c:
            c.execute('CREATE TABLE events(seq INTEGER PRIMARY KEY,kind TEXT NOT NULL,key TEXT NOT NULL,payload TEXT NOT NULL,previous TEXT NOT NULL,hash TEXT NOT NULL,UNIQUE(kind,key))')
            for action in ('UPDATE','DELETE'):
                c.execute(f"CREATE TRIGGER frozen_{action} BEFORE {action} ON events BEGIN SELECT RAISE(ABORT,'frozen_journal'); END")
            c.execute("CREATE TRIGGER frozen_collision BEFORE INSERT ON events WHEN EXISTS(SELECT 1 FROM events WHERE seq=NEW.seq OR (kind=NEW.kind AND key=NEW.key)) BEGIN SELECT RAISE(ABORT,'frozen_journal_collision'); END")
        os.chmod(db,0o600);s=db.stat()
        durable_json(root/'anchor.json',dict(schema=1,kind=kind,journal_id=uuid.uuid4().hex,root=str(root),device=s.st_dev,inode=s.st_ino,protocol_hash=digest(protocol)),exclusive=True)
        durable_json(root/'head.json',{'seq':0,'hash':'0'*64},exclusive=True)
        obj=cls(root,kind)
        with obj.transaction() as c:obj.add(c,'protocol','frozen',protocol)
        return obj

    def __init__(self,root,kind):
        self.root=Path(root).absolute();self.kind=kind
        try:self.anchor=strict_read(self.root/'anchor.json')
        except (OSError,ValueError) as exc:raise ValueError('journal_identity_missing') from exc
        self._identity()

    def _identity(self):
        try:
            s=(self.root/'journal.db').stat();a=strict_read(self.root/'anchor.json')
            if (self.root.resolve()!=self.root or a!=self.anchor or a['kind']!=self.kind or a['root']!=str(self.root)
                    or (s.st_dev,s.st_ino)!=(a['device'],a['inode'])):raise ValueError('journal_identity_changed')
        except (OSError,KeyError) as exc:raise ValueError('journal_identity_changed') from exc

    def rows(self,c,kind=None):
        query='SELECT * FROM events'+(' WHERE kind=?' if kind else '')+' ORDER BY seq'
        return [dict(r,payload=json.loads(r['payload'])) for r in c.execute(query,(kind,) if kind else ())]

    def _verify(self,c):
        previous='0'*64;seq=0;head=strict_read(self.root/'head.json');heads={0:previous}
        for row in self.rows(c):
            seq+=1
            value={k:row[k] for k in ('seq','kind','key','payload','previous')}
            if row['seq']!=seq or row['previous']!=previous or row['hash']!=digest(value):raise ValueError('journal_hashchain_changed')
            previous=row['hash'];heads[seq]=previous
        if heads.get(head.get('seq'))!=head.get('hash'):raise ValueError('journal_tail_lost')
        protocol=self.rows(c,'protocol')
        if seq and (len(protocol)!=1 or digest(protocol[0]['payload'])!=self.anchor['protocol_hash']):raise ValueError('journal_protocol_changed')
        return {'seq':seq,'hash':previous}

    @contextmanager
    def transaction(self,*,timeout=5):
        if type(timeout) not in (int,float) or not math.isfinite(timeout) or timeout<=0:raise TimeoutError('journal_lock_deadline')
        deadline=time.monotonic()+timeout
        self._identity()
        with (self.root/'journal.lock').open('a') as lock:
            while True:
                try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB);break
                except BlockingIOError:
                    remaining=deadline-time.monotonic()
                    if remaining<=0:raise TimeoutError('journal_lock_deadline')
                    time.sleep(min(.01,remaining))
            remaining=deadline-time.monotonic()
            if remaining<=0:raise TimeoutError('journal_lock_deadline')
            self._identity();c=sqlite3.connect(self.root/'journal.db',timeout=remaining);c.row_factory=sqlite3.Row
            c.set_progress_handler(lambda:int(time.monotonic()>=deadline),1000)
            try:
                c.execute('PRAGMA synchronous=FULL');c.execute('BEGIN IMMEDIATE');self._verify(c)
                yield c
                head=self._verify(c);c.commit();durable_json(self.root/'head.json',head)
            except BaseException:c.rollback();raise
            finally:c.close()

    def add(self,c,kind,key,payload):
        row=c.execute('SELECT seq,hash FROM events ORDER BY seq DESC LIMIT 1').fetchone()
        value=dict(seq=row['seq']+1 if row else 1,kind=kind,key=key,payload=payload,previous=row['hash'] if row else '0'*64)
        value['hash']=digest(value)
        c.execute('INSERT INTO events VALUES(?,?,?,?,?,?)',(value['seq'],kind,key,canonical(payload),value['previous'],value['hash']))
        return value


def observation_protocol(units,*,checkpoints=None,late_tolerance=300,max_gap=120):
    return dict(schema=1,mode='observation_only',units=units,checkpoints=checkpoints or [0,21600,86400,172800,259200],
                late_tolerance=late_tolerance,clock_tolerance=2,max_gap=max_gap,max_paid_calls=0,
                stop_rule='last_frozen_window_upper_bound')


def validate_protocol(p):
    if not isinstance(p,dict) or set(p)!=set(observation_protocol([])):raise ValueError('invalid_cohort_fields')
    canonical(p)
    if type(p['schema']) is not int or p['schema']!=1 or p['mode']!='observation_only' or type(p['max_paid_calls']) is not int or p['max_paid_calls']!=0 or p['stop_rule']!='last_frozen_window_upper_bound':raise ValueError('observation_only_required')
    units=p['units'];points=p['checkpoints']
    if not isinstance(units,list) or not 1<=len(units)<=128 or any(not isinstance(u,str) or not re.fullmatch('[a-zA-Z0-9_-]{1,64}',u) for u in units) or len(set(units))!=len(units):raise ValueError('invalid_cohort_units')
    if not isinstance(points,list) or not 1<=len(points)<=32 or any(type(t) is not int or not 0<=t<=259200 for t in points) or points!=sorted(set(points)) or points[0]!=0:raise ValueError('invalid_cohort_windows')
    for field,limit in (('late_tolerance',3600),('clock_tolerance',60),('max_gap',86400)):
        if type(p[field]) not in (int,float) or not math.isfinite(p[field]) or not 0<p[field]<=limit:raise ValueError('invalid_'+field)
    if any(b-a<=p['late_tolerance'] for a,b in zip(points,points[1:])):raise ValueError('overlapping_cohort_windows')
    return json.loads(canonical(p))


class CohortLedger:
    @classmethod
    def register(cls,root,protocol,*,clock=host_clock):
        p=validate_protocol(protocol);p['origin']=stamp(clock())
        journal=Journal.create(root,'cohort',p)
        with journal.transaction() as c:
            for unit in p['units']:
                for target in p['checkpoints']:
                    cell={'unit':unit,'target_seconds':target,'opens_utc':p['origin']['utc']+target,
                          'closes_utc':p['origin']['utc']+target+p['late_tolerance']}
                    journal.add(c,'allocation',digest(cell),cell)
        return cls(root,clock=clock)

    def __init__(self,root,*,clock=host_clock):
        self.journal=Journal(root,'cohort');self.root=self.journal.root;self.clock=clock
        with self.journal.transaction() as c:self.protocol=self.journal.rows(c,'protocol')[0]['payload']
        validate_protocol({k:v for k,v in self.protocol.items() if k!='origin'});stamp(self.protocol['origin'])

    def _continuity(self,c,now):
        p=self.protocol;prior=p['origin'];good=True;reasons=set()
        samples=[r['payload']['clock'] for r in self.journal.rows(c) if 'clock' in r['payload']]+[now]
        for sample in samples:
            if sample['boot_id']!=prior['boot_id']:reasons.add('boot_changed')
            elif sample['monotonic']<prior['monotonic']:reasons.add('monotonic_rollback')
            elif abs((sample['utc']-prior['utc'])-(sample['monotonic']-prior['monotonic']))>p['clock_tolerance']:reasons.add('clock_discontinuity')
            if sample['utc']<prior['utc']:reasons.add('utc_rollback')
            if sample['utc']-prior['utc']>p['max_gap']:reasons.add('observation_gap')
            prior=sample
        return not reasons,sorted(reasons)

    def _state(self,c,now):
        receipts={r['key']:r['payload'] for r in self.journal.rows(c,'measurement')}
        claims={r['payload']['cell']:r['payload'] for r in self.journal.rows(c,'claim')}
        continuous,reasons=self._continuity(c,now);origin=self.protocol['origin']
        elapsed=None
        if now['boot_id']==origin['boot_id'] and now['monotonic']>=origin['monotonic'] and abs(now['utc']-origin['utc']-(now['monotonic']-origin['monotonic']))<=self.protocol['clock_tolerance']:
            elapsed=now['monotonic']-origin['monotonic']
        rows=[];counts={k:0 for k in ('not_due','unrun','missed','observed','late','unknown')}
        for row in self.journal.rows(c,'allocation'):
            cell=row['payload'];receipt=receipts.get(row['key'])
            state=receipt['state'] if receipt else ('not_due' if now['utc']<cell['opens_utc'] else 'missed' if now['utc']>cell['closes_utc'] else 'unrun')
            if not receipt and row['key'] in claims:state='unknown'
            rows.append(dict(id=row['key'],**cell,state=state,receipt=receipt));counts[state]+=1
        return dict(schema=1,protocol_hash=self.journal.anchor['protocol_hash'],units=len(self.protocol['units']),
                    allocated_measurements=len(rows),paid_allocations=0,states=counts,measurements=rows,
                    observed_clock=now,actual_elapsed_seconds=elapsed,clock_continuity=continuous,clock_reasons=reasons,
                    continuous_liveness_supported=False,causal_gain_supported=False,
                    claim='Actual observation-only follow-up; no continuous service, useful-work or causal-benefit assertion')

    def report(self):
        now=stamp(self.clock())
        with self.journal.transaction() as c:return self._state(c,now)

    def _save_report(self,report):
        directory=self.root/'reports';directory.mkdir(mode=0o700,exist_ok=True)
        path=directory/(digest(report)+'.json')
        if not path.exists():durable_json(path,report,exclusive=True)
        durable_json(self.root/'report.json',report)
        return report

    def claim(self,cell,owner,*,lease=30):
        if not isinstance(owner,str) or not re.fullmatch('[A-Za-z0-9_-]{1,100}',owner) or type(lease) not in (int,float) or not 0<lease<=120:raise ValueError('invalid_observer_claim')
        now=stamp(self.clock())
        with self.journal.transaction() as c:
            claims=[r['payload'] for r in self.journal.rows(c,'claim') if r['payload']['cell']==cell]
            if claims:
                latest=claims[-1]
                raise ValueError('claim_reconciliation_required' if now['boot_id']!=latest['clock']['boot_id'] or now['monotonic']>=latest['expires_monotonic'] else 'cell_claimed')
            row=next((r for r in self._state(c,now)['measurements'] if r['id']==cell),None)
            if row is None or row['state']!='unrun':raise ValueError('cell_not_due')
            value=dict(cell=cell,owner=owner,generation=1,clock=now,expires_monotonic=now['monotonic']+lease)
            self.journal.add(c,'claim',cell,value);return value

    def finish(self,claim,evidence=None):
        # This observer measures its own actual clock only. A caller cannot supply
        # success, elapsed time, liveness or any provider execution evidence.
        if evidence is not None:raise ValueError('caller_observation_verdict_forbidden')
        now=stamp(self.clock())
        with self.journal.transaction() as c:
            stored=[r['payload'] for r in self.journal.rows(c,'claim') if r['key']==claim.get('cell')]
            if stored!=[claim]:raise ValueError('observer_claim_changed')
            if now['boot_id']!=claim['clock']['boot_id'] or not claim['clock']['monotonic']<=now['monotonic']<claim['expires_monotonic']:raise ValueError('claim_reconciliation_required')
            report=self._state(c,now);row=next(r for r in report['measurements'] if r['id']==claim['cell'])
            state='observed' if row['opens_utc']<=now['utc']<=row['closes_utc'] else 'late' if now['utc']>row['closes_utc'] else 'unknown'
            if report['actual_elapsed_seconds'] is None:state='unknown'
            value=dict(clock=now,state=state,owner=claim['owner'],generation=claim['generation'],clock_continuity=report['clock_continuity'],clock_reasons=report['clock_reasons'],actual_elapsed_seconds=report['actual_elapsed_seconds'],service_liveness='unobserved')
            self.journal.add(c,'measurement',claim['cell'],value)
        return value

    def observe(self,*,owner='manual'):
        for row in self.report()['measurements']:
            if row['state']=='unrun':self.finish(self.claim(row['id'],owner))
        return self._save_report(self.report())

    def reconcile(self):
        now=stamp(self.clock())
        with self.journal.transaction() as c:
            measured={r['key'] for r in self.journal.rows(c,'measurement')}
            for row in self.journal.rows(c,'claim'):
                claim=row['payload']
                if row['key'] not in measured and (now['boot_id']!=claim['clock']['boot_id'] or now['monotonic']>=claim['expires_monotonic']):
                    self.journal.add(c,'measurement',row['key'],dict(state='unknown',clock=now,owner=claim['owner'],generation=claim['generation'],reason='expired_observation_claim_no_replay',service_liveness='unobserved'))
        return self._save_report(self.report())

    def watch(self,*,owner='watch',wait=time.sleep,poll_seconds=30):
        if type(poll_seconds) not in (int,float) or not 0<poll_seconds<=60:raise ValueError('invalid_watch_poll')
        # A kernel lock prevents duplicate live watchers; durable generations
        # identify death/restart. The lock is released automatically on death.
        with (self.root/'watch.lock').open('a') as lock:
            try:fcntl.flock(lock,fcntl.LOCK_EX|fcntl.LOCK_NB)
            except BlockingIOError:raise ValueError('watcher_already_owned') from None
            self.reconcile();now=stamp(self.clock());p=self.protocol
            with self.journal.transaction() as c:
                generation=len(self.journal.rows(c,'watch_start'))+1
                self.journal.add(c,'watch_start',str(generation),dict(owner=owner,generation=generation,clock=now))
            upper=p['origin']['utc']+p['checkpoints'][-1]+p['late_tolerance']
            mono_upper=p['origin']['monotonic']+p['checkpoints'][-1]+p['late_tolerance']
            while True:
                now=stamp(self.clock())
                with self.journal.transaction() as c:
                    self.journal.add(c,'watch_tick',uuid.uuid4().hex,dict(clock=now,generation=generation))
                report=self.observe(owner=owner)
                if (now['boot_id']!=p['origin']['boot_id'] or report['actual_elapsed_seconds'] is None or now['utc']>=upper or now['monotonic']>=mono_upper):break
                due=[r['opens_utc'] for r in report['measurements'] if r['state']=='not_due']
                delay=min(poll_seconds,upper-now['utc'],mono_upper-now['monotonic'],max(.001,min(due)-now['utc']) if due else poll_seconds)
                wait(delay)
            with self.journal.transaction() as c:self.journal.add(c,'watch_stop',str(generation),dict(clock=stamp(self.clock()),generation=generation))
            return self._save_report(self.report())


def main():
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('command',choices=('register','observe','report','reconcile','watch'));parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--unit',action='append');parser.add_argument('--late-tolerance',type=int,default=300);parser.add_argument('--owner',default='observer')
    args=parser.parse_args()
    if args.command=='register':ledger=CohortLedger.register(args.root,observation_protocol(args.unit or ['paired-pilot-followup'],late_tolerance=args.late_tolerance));result=ledger._save_report(ledger.report())
    else:
        ledger=CohortLedger(args.root)
        result=ledger.observe(owner=args.owner) if args.command=='observe' else ledger.watch(owner=args.owner) if args.command=='watch' else ledger.reconcile() if args.command=='reconcile' else ledger.report()
    print(canonical(result))


if __name__=='__main__':main()
