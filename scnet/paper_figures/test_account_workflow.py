"""Account assignment and scheduler visibility regression checks."""
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import patch
from types import SimpleNamespace
from scnet.paper_figures.distribute_prepare_jobs import assign_units
from scnet.paper_figures import control_account_jobs as controller


def record(job=''):
    return dict(classification='active' if job else 'not_submitted',attempt=int(bool(job)),job_id=job,state='',exit='',elapsed='',maxrss='',reason='')


class AccountTests(unittest.TestCase):
    def test_existing_jobs_stay_and_pairs_share_account(self):
        names=['loss_ssp126_wind_R01C01','events_ssp126_wind_R01C01','loss_ssp585_solar_R01C02','events_ssp585_solar_R01C02','loss_summary']
        state={n:record() for n in names};state[names[0]]=record('123')
        owner=assign_units([dict(unit=n) for n in names],state,[dict(username='a'),dict(username='b')],'a')
        self.assertEqual(owner[names[0]],'a');self.assertEqual(owner['loss_summary'],'a')
        self.assertEqual(owner[names[2]],owner[names[3]])
        self.assertEqual(state[names[0]]['job_id'],'123')

    def test_submit_cap_with_delayed_squeue_visibility_and_blocked_dependency(self):
        with TemporaryDirectory() as directory:
            base=Path(directory);status=base/'status';own=base/'accounts/a';own.mkdir(parents=True);(status/'accounts/a').mkdir(parents=True)
            units=[dict(unit='loss_ssp126_wind_R'+str(i),account='a',dependencies=[],script=str(base/('job'+str(i)+'.sh')),marker=str(base/('out'+str(i))/'complete.json'),log_pattern='unused') for i in range(25)]
            units.insert(0,dict(unit='panels_loss',account='a',dependencies=[units[-1]['unit']],script='blocked.sh',marker='blocked/complete.json',log_pattern='unused'))
            state={u['unit']:dict(record(),account='a') for u in units};(own/'state.json').write_text(json.dumps(state))
            manifest=dict(job_dir=str(base),coordinator='a',accounts=[dict(username='a',max_active=20,submit_lock=str(base/'submit.lock'))],prerequisite='catalog/complete.json',units=units)
            file=base/'jobs.json';file.write_text(json.dumps(manifest));submitted=[]
            def command(args):
                if args==['id','-un']:return 'a\n'
                if args==['hostname']:return 'login\n'
                if args[0]=='squeue':return ''
                raise AssertionError(args)
            def submit(args,**kwargs):
                self.assertNotEqual(args[-1],'blocked.sh');submitted.append(args[-1]);return SimpleNamespace(returncode=0,stdout=str(100+len(submitted))+'\n',stderr='')
            with patch.object(controller,'STATUS',status),patch.object(controller,'command',side_effect=command),patch.object(controller,'require_complete'),patch.object(controller.subprocess,'run',side_effect=submit),patch('sys.argv',['control',str(file),'--submit']):controller.main()
            result=json.loads((own/'state.json').read_text());self.assertEqual(len(submitted),20)
            self.assertFalse(result['panels_loss']['job_id']);self.assertEqual(sum(bool(r['job_id']) for r in result.values()),20)
            self.assertTrue((status/'progress.md').exists())

if __name__=='__main__':unittest.main()
