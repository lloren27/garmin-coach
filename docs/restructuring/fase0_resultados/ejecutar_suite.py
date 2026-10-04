"""Existing suites under the same audit guard; no production configuration."""
import sys,os,json,io,unittest,tempfile,time,re
from pathlib import Path
from aislamiento import install
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
kind=sys.argv[1];assert kind in ('bot','worker')
run=next((a.split('=',1)[1] for a in sys.argv if a.startswith('--run=')),None)
if not run or not re.fullmatch(r'[a-zA-Z0-9_-]+',run):raise SystemExit('Specify a unique --run=label')
dest=OUT/'ejecuciones'/run;dest.mkdir(parents=True,exist_ok=True)
port=next((int(a.split('=',1)[1]) for a in sys.argv if a.startswith('--audit-db-port=')),None)
root,blocked=install(OUT,database_port=port)
if port is not None:
    # Only the new, disposable localhost database. No production URL accepted.
    os.environ['P03_TEST_DATABASE_URL']=f'postgresql://postgres@127.0.0.1:{port}/garmin_audit'
tempfile.tempdir=str(root)
sys.path[:0]=[str(ROOT/'apps/bot'),str(ROOT/'apps/sync-local')]
sys.path.extend(str(p) for p in (ROOT/'apps/bot/.venv/lib').glob('python*/site-packages'))
folder=ROOT/('apps/bot/tests' if kind=='bot' else 'apps/sync-local/tests')
sys.path.insert(0,str(folder))
stream=io.StringIO();start=time.monotonic()
suite=unittest.defaultTestLoader.discover(str(folder))
result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
with (dest/('suite_'+kind+'.txt')).open('x') as f:f.write(stream.getvalue())
summary={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'seconds':round(time.monotonic()-start,3),'blocked_events':blocked,'success':result.wasSuccessful(),'scope':'Existing regression tests, not new phase-0 acceptance cases.'}
summary['isolated_postgres']=port is not None
with (dest/('suite_'+kind+'.json')).open('x') as f:f.write(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary));sys.exit(0 if result.wasSuccessful() else 1)
