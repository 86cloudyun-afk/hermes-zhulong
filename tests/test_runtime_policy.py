import copy
import importlib
import json
import os
import tempfile
import unittest
from pathlib import Path


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime_policy'),'protected runtime policy missing')
        self.m=importlib.import_module('runtime_policy')
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.base=Path(self.temp.name);self.work=self.base/'work';self.work.mkdir()
        self.manifest={'version':1,'deployment_id':'test-runtime','root':str(self.base/'service'),
            'work':str(self.work),'host':str(self.base/'host'),'host_revision':'a'*40,
            'plugin_root':str(self.base/'plugin'),'image':'python@sha256:'+'b'*64,
            'command':['/bin/true'],'port':8642,'max_launches':3,'startup_seconds':30,
            'shutdown_seconds':10,'progress_seconds':120,'hashes':{}}
        self.policy={'workspace_roots':[str(self.work)],'sources':[{'path':str(self.work/'facts.json'),
            'contracts':{'result':{'type':'file_contains','path':str(self.work/'result'),'text':'done'}}}]}

    def test_protected_paths_and_host_code_cannot_overlap_work(self):
        self.m.validate_manifest(self.manifest)
        for key in ('root','host','plugin_root'):
            wrong=copy.deepcopy(self.manifest);wrong[key]=str(self.work/key)
            with self.assertRaises(ValueError):self.m.validate_manifest(wrong)
        wrong=copy.deepcopy(self.manifest);wrong['image']='python:latest'
        with self.assertRaises(ValueError):self.m.validate_manifest(wrong)

    def test_host_argv_verification_and_source_output_overlap_denied(self):
        self.m.validate_worker_policy(self.manifest,self.policy)
        for change in ('argv','facts'):
            wrong=copy.deepcopy(self.policy)
            contract=wrong['sources'][0]['contracts']['result']
            if change=='argv':contract.update(type='argv',argv=['python','test.py'])
            else:contract['path']=wrong['sources'][0]['path']
            with self.assertRaises(ValueError):self.m.validate_worker_policy(self.manifest,wrong)

    def test_forced_environment_overrides_local_backend_without_forwarding_secrets(self):
        config=self.m.native_config(self.manifest,self.policy)
        env=self.m.child_environment(self.manifest,'boot',{'TERMINAL_ENV':'local','TERMINAL_DOCKER_FORWARD_ENV':'["DEEPSEEK_API_KEY"]',
             'DEEPSEEK_API_KEY':'private-key','DOCKER_HOST':'tcp://elsewhere','ZHULONG_NO_AUTOSWEEP':'1'},api_key='local-api-key')
        self.assertEqual(env['TERMINAL_ENV'],'docker')
        self.assertEqual(env['DOCKER_HOST'],'unix:///var/run/docker.sock')
        self.assertEqual(json.loads(env['TERMINAL_DOCKER_FORWARD_ENV']),[])
        self.assertEqual(env['ZHULONG_NO_AUTOSWEEP'],'')
        self.assertEqual(config['platform_toolsets']['api_server'],['terminal','no_mcp'])
        self.assertEqual(config['known_plugin_toolsets']['api_server'],['zhulong'])
        self.assertEqual(config.get('tools',{}).get('tool_search',{}).get('enabled'),'off')
        self.assertFalse(config['terminal']['docker_network'])
        self.assertFalse(config['terminal']['docker_mount_cwd_to_workspace'])
        self.assertFalse(config['gateway'].get('multiplex_profiles',True))
        self.assertFalse(config['platforms'].get('telegram',{}).get('enabled',True))
        self.assertNotIn('private-key',json.dumps(config))

    def test_actual_worker_inspection_denies_mount_network_user_and_limits_drift(self):
        expected={'Config':{'User':f'{os.getuid()}:{os.getgid()}','Env':['HOME=/home'],
            'Labels':{'zhulong.runtime':'test-runtime'}},
            'HostConfig':{'ReadonlyRootfs':True,'NetworkMode':'none','Privileged':False,
                'PidMode':'','IpcMode':'private','Memory':536870912,'NanoCpus':1000000000,'PidsLimit':128,
                'SecurityOpt':['no-new-privileges'],'CapDrop':['ALL'],
                'CapAdd':['CAP_CHOWN','CAP_DAC_OVERRIDE','CAP_FOWNER'],
                'Tmpfs':{'/tmp':'rw,nosuid,size=512m'}},
            'Mounts':[{'Type':'bind','Source':str(self.work),'Destination':str(self.work),'RW':True},
                {'Type':'bind','Source':str(self.work/'facts.json'),'Destination':str(self.work/'facts.json'),'RW':False}]}
        self.m.inspect_worker(self.manifest,self.policy,expected)
        cases=[('network',lambda x:x['HostConfig'].update(NetworkMode='host')),
            ('user',lambda x:x['Config'].update(User='0')),
            ('mount',lambda x:x['Mounts'].append({'Type':'bind','Source':'/var/run/docker.sock','Destination':'/sock','RW':False})),
            ('memory',lambda x:x['HostConfig'].update(Memory=0)),
            ('secret',lambda x:x['Config']['Env'].append('DEEPSEEK_API_KEY=private'))]
        for name,change in cases:
            wrong=copy.deepcopy(expected);change(wrong)
            with self.subTest(name=name),self.assertRaises(ValueError):self.m.inspect_worker(self.manifest,self.policy,wrong)
        cache=Path(self.manifest['root'])/'profile/cache/documents';cache.mkdir(parents=True)
        expected['Mounts'].append({'Type':'bind','Source':str(cache),'Destination':'/root/.hermes/cache/documents','RW':False})
        self.m.inspect_worker(self.manifest,self.policy,expected)
        expected['Mounts'][-1]['RW']=True
        with self.assertRaises(ValueError):self.m.inspect_worker(self.manifest,self.policy,expected)
