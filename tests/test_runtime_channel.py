import importlib
import json
import tempfile
import threading
import time
import unittest
from pathlib import Path
from types import SimpleNamespace


class ChannelTests(unittest.TestCase):
    def test_matching_boot_required_and_stopping_acknowledges_closed_admission(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime_channel'),'boot channel missing')
        m=importlib.import_module('runtime_channel')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);stops=[];event=threading.Event()
            controller=SimpleNamespace(request_stop=lambda:stops.append(True),
                progress=lambda:{'phase':'idle','ticks':0,'errors':0},status=lambda:{'active_executions':0})
            channel=m.ServiceChannel(root,'boot-a',controller,event)
            m.atomic_json(root/'control.json',{'boot_id':'old','state':'running'})
            self.assertFalse(channel.admissible())
            m.atomic_json(root/'control.json',{'boot_id':'boot-a','state':'running'})
            self.assertTrue(channel.admissible())
            channel.publish()
            self.assertEqual(json.loads((root/'health.json').read_text())['boot_id'],'boot-a')
            m.atomic_json(root/'control.json',{'boot_id':'boot-a','state':'stopping'})
            channel.publish()
            health=json.loads((root/'health.json').read_text())
            self.assertFalse(channel.admissible())
            self.assertTrue(health['admission_closed'])
            self.assertTrue(event.is_set());self.assertTrue(stops)
            self.assertEqual((root/'health.json').stat().st_mode & 0o777,0o600)

    def test_missing_or_corrupt_control_fails_closed(self):
        self.assertIsNotNone(importlib.util.find_spec('runtime_channel'),'boot channel missing')
        m=importlib.import_module('runtime_channel')
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            channel=m.ServiceChannel(root,'b',None,threading.Event())
            self.assertFalse(channel.admissible())
            (root/'control.json').write_text('{truncated')
            self.assertFalse(channel.admissible())
            channel.publish()
            self.assertEqual(json.loads((root/'health.json').read_text())['state'],'blocked')
