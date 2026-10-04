"""Existing suites under the same audit guard; no production configuration."""
import sys,os,json,io,unittest,tempfile,time
from pathlib import Path
from aislamiento import install
OUT=Path(__file__).resolve().parent;ROOT=OUT.parents[2]
kind=sys.argv[1];assert kind in ('bot','worker')
root,blocked=install(OUT)
tempfile.tempdir=str(root)
sys.path[:0]=[str(ROOT/'apps/bot'),str(ROOT/'apps/sync-local')]
sys.path.extend(str(p) for p in (ROOT/'apps/bot/.venv/lib').glob('python*/site-packages'))
folder=ROOT/('apps/bot/tests' if kind=='bot' else 'apps/sync-local/tests')
sys.path.insert(0,str(folder))
stream=io.StringIO();start=time.monotonic()
suite=unittest.defaultTestLoader.discover(str(folder))
result=unittest.TextTestRunner(stream=stream,verbosity=1).run(suite)
(OUT/'ejecuciones'/('suite_'+kind+'.txt')).write_text(stream.getvalue())
summary={'tests':result.testsRun,'failures':len(result.failures),'errors':len(result.errors),'skipped':len(result.skipped),'seconds':round(time.monotonic()-start,3),'blocked_events':blocked,'success':result.wasSuccessful(),'scope':'Existing regression tests, not new phase-0 acceptance cases.'}
(OUT/'ejecuciones'/('suite_'+kind+'.json')).write_text(json.dumps(summary,indent=2)+'\n')
print(json.dumps(summary));sys.exit(0 if result.wasSuccessful() else 1)
