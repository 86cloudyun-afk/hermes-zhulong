import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]


class Context:
    llm=None
    def __init__(self):self.hooks={};self.tools={};self.commands={};self.cleanup=[]
    def register_hook(self,event,callback):self.hooks[event]=callback
    def register_tool(self,**kwargs):self.tools[kwargs['name']]=kwargs
    def register_command(self,**kwargs):self.commands[kwargs['name']]=kwargs
    def on_unload(self,callback):self.cleanup.append(callback)


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.home=Path(self.temp.name)
        self.env=patch.dict(os.environ,{'HERMES_HOME':str(self.home),'ZHULONG_NO_AUTOSWEEP':'1'});self.env.start();self.addCleanup(self.env.stop)
        spec=importlib.util.spec_from_file_location('zhulong_plugin_tests',ROOT/'__init__.py',submodule_search_locations=[str(ROOT)])
        self.plugin=importlib.util.module_from_spec(spec);sys.modules[spec.name]=self.plugin;spec.loader.exec_module(self.plugin)
        self.ctx=Context()
        def unload():
            for callback in reversed(self.ctx.cleanup):callback()
        self.addCleanup(unload)

    def test_disabled_plugin_keeps_hooks_and_has_four_tools(self):
        self.plugin.register(self.ctx)
        self.assertEqual(len(self.ctx.hooks),11);self.assertEqual(len(self.ctx.tools),4);self.assertEqual(len(self.ctx.commands),1)
        status=json.loads(self.ctx.tools['zhulong_autonomy']['handler']({'action':'status'}))
        self.assertFalse(status['enabled'])
        self.assertTrue(self.ctx.cleanup,'plugin lifecycle cleanup missing')

    def test_invalid_autonomy_keeps_observers_and_reports_block(self):
        (self.home/'zhulong').mkdir();(self.home/'zhulong'/'config.json').write_text(json.dumps({'scheduler':False,'autonomy':{'enabled':True,'daily_runs':True}}))
        self.plugin.register(self.ctx)
        self.assertEqual(len(self.ctx.hooks),11);self.assertEqual(len(self.ctx.tools),4)
        status=json.loads(self.ctx.tools['zhulong_autonomy']['handler']({'action':'status'}))
        self.assertFalse(status['ok']);self.assertIn('blocked_reason',status)

    def test_public_tools_cannot_set_success_or_acceptance(self):
        self.plugin.register(self.ctx)
        self.assertIn('zhulong_autonomy',self.ctx.tools)
        tool=self.ctx.tools['zhulong_autonomy']
        self.assertEqual(tool['schema']['parameters']['properties']['action']['enum'],['status','goals','tick','experience','skills'])
        self.assertFalse(json.loads(tool['handler']({'action':'succeeded'}))['ok'])
        before=(self.home/'zhulong'/'self_model.json').read_bytes()
        model_tool=self.ctx.tools['zhulong_model'];model_tool['handler']({});model_tool['handler']({})
        self.assertEqual((self.home/'zhulong'/'self_model.json').read_bytes(),before)
        self.assertIn('autonomy',self.ctx.commands['zhulong']['handler']('help'))

    def test_installer_copies_all_runtime_modules(self):
        result=subprocess.run(['bash',str(ROOT/'scripts'/'install.sh')],env=os.environ.copy(),capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        destination=self.home/'plugins'/'zhulong'
        for name in ('autonomy','autonomy_store','autonomy_checks','hermes_runs','self_model','experience','experience_store','skill_store','skill_learning','skill_evaluator'):
            self.assertTrue((destination/(name+'.py')).is_file(),name)
        self.assertEqual((destination/'plugin.yaml').read_bytes(),(ROOT/'plugin.yaml').read_bytes())

    def test_optional_storage_failure_keeps_legacy_interfaces_and_cleanup(self):
        for obstruction in ('autonomy.db','self_model.json'):
            with self.subTest(obstruction=obstruction):
                blocked=self.home/'zhulong'/obstruction;blocked.mkdir(parents=True)
                ctx=Context()
                try:
                    with patch.object(self.plugin.logger,'warning'):self.plugin.register(ctx)
                    self.assertEqual(len(ctx.hooks),11);self.assertEqual(len(ctx.tools),4)
                    self.assertEqual(len(ctx.commands),1);self.assertTrue(ctx.cleanup)
                    result=json.loads(ctx.tools['zhulong_calibration']['handler']({'action':'report'}))
                    self.assertTrue(result['ok'])
                    status=json.loads(ctx.tools['zhulong_autonomy']['handler']({'action':'status'}))
                    self.assertFalse(status['ok']);self.assertEqual(status['blocked_reason'],'autonomy_storage_unavailable')
                finally:
                    for callback in reversed(ctx.cleanup):callback()
                    blocked.rmdir()


if __name__=='__main__':unittest.main()
