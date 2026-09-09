"""Trusted Git and CLI seam tests with temporary synthetic Git repositories.

These repositories are test fixtures, not new user/project worktrees. No remote
is contacted, no hooks are run, and no real input is promoted by these tests.
"""
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
ROOT=Path(__file__).resolve().parents[1]
spec=importlib.util.spec_from_file_location('decision_cli',ROOT/'tools/run_research_decision_v1.py')
cli=importlib.util.module_from_spec(spec);spec.loader.exec_module(cli)

class SourceSeamTests(unittest.TestCase):
    def fixture(self,root):
        paths=['tools/research_decision_v1/__init__.py','tools/research_decision_v1/data.py',
               'tools/run_research_decision_v1.py','tools/export_research_decision_market.py','docs/research_decision_v1_config.json']
        for name in paths:
            p=root/name;p.parent.mkdir(parents=True,exist_ok=True)
            p.write_text('{}\n' if name.endswith('.json') else '# synthetic source\n',encoding='utf-8')
        git='/usr/bin/git'
        env={**os.environ,'GIT_CONFIG_NOSYSTEM':'1','GIT_CONFIG_GLOBAL':os.devnull}
        for args in (['init','-q'],['add','--',*paths],['-c','user.name=Fixture','-c','user.email=fixture@example.org','commit','-qm','synthetic']):
            subprocess.run([git,*args],cwd=root,env=env,check=True,capture_output=True)
        return paths

    @unittest.skipUnless(os.name=='posix' and Path('/usr/bin/git').exists(),'requires OS Git for synthetic repository fixture')
    def test_fake_path_git_is_never_executed(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d)/'repo';root.mkdir();self.fixture(root)
            hostile=Path(d)/'hostile';hostile.mkdir();marker=Path(d)/'executed'
            script=hostile/'git';script.write_text('#!/bin/sh\ntouch "'+str(marker)+'"\nexit 99\n',encoding='utf-8');script.chmod(0o755)
            with patch.dict(os.environ,{'PATH':str(hostile)},clear=False):
                snapshot=cli.verified_source_snapshot(root)
            self.assertIsNotNone(snapshot);self.assertFalse(marker.exists())
            self.assertEqual(snapshot['git_executable'],'/usr/bin/git')

    @unittest.skipUnless(os.name=='posix' and Path('/usr/bin/git').exists(),'requires OS Git')
    def test_injected_git_dir_does_not_select_other_repository(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            with patch.dict(os.environ,{'GIT_DIR':'/not/a/repository','GIT_CONFIG_COUNT':'broken'},clear=False):
                self.assertIsNotNone(cli.verified_source_snapshot(root))

    def test_no_trusted_executable_fails_closed(self):
        with patch.object(cli,'trusted_git_executable',side_effect=ValueError('unavailable')):
            self.assertIsNone(cli.verified_source_snapshot(ROOT))

    def test_environment_drops_dynamic_loader_and_git_override(self):
        with patch.dict(os.environ,{'GIT_DIR':'bad','LD_PRELOAD':'bad','DYLD_INSERT_LIBRARIES':'bad'}):
            e=cli.git_read_environment()
        self.assertNotIn('LD_PRELOAD',e);self.assertNotIn('GIT_DIR',e);self.assertNotIn('DYLD_INSERT_LIBRARIES',e)
        self.assertEqual(e['GIT_CONFIG_GLOBAL'],os.devnull)

    @unittest.skipUnless(os.name=='posix' and Path('/usr/bin/git').exists(),'requires OS Git')
    def test_modified_source_still_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);self.fixture(root)
            (root/'tools/research_decision_v1/data.py').write_text('# changed\n',encoding='utf-8')
            self.assertIsNone(cli.verified_source_snapshot(root))

if __name__=='__main__':unittest.main(verbosity=2)
