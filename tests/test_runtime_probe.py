import importlib
import unittest


class ProbeTests(unittest.TestCase):
    def test_pinned_bundled_plugins_are_not_mistaken_for_user_plugins(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.runtime_probe'))
        m=importlib.import_module('scripts.runtime_probe')
        self.assertTrue(callable(getattr(m,'check_plugins',None)))
        plugins=[{'name':'basic','enabled':True,'error':None,'source':'bundled'},
            {'name':'zhulong','enabled':True,'error':None,'source':'user'}]
        m.check_plugins(plugins)
        with self.assertRaises(ValueError):m.check_plugins(plugins+[{'name':'extra','enabled':True,'source':'user','error':None}])

    def test_final_schema_names_fail_closed(self):
        self.assertIsNotNone(importlib.util.find_spec('scripts.runtime_probe'),'native boundary probe missing')
        m=importlib.import_module('scripts.runtime_probe')
        good=[{'function':{'name':n}} for n in ('terminal','process_manage')]
        self.assertEqual(m.check_names(good),['process_manage','terminal'])
        for bad in (good+[{'function':{'name':'write_file'}}],good[:1],[]):
            with self.assertRaises(ValueError):m.check_names(bad)
