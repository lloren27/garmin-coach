"""Read-only local metadata, sanitized summaries only; never imports product I/O."""
from pathlib import Path
import json, hashlib, subprocess, plistlib, re, os
from datetime import datetime, timezone
from collections import Counter
import httpx
from dotenv import dotenv_values

OUT=Path(__file__).resolve().parent
ROOT=OUT.parents[2]
def save(name,value):
    (OUT/name).write_text(json.dumps(value,ensure_ascii=False,indent=2)+'\n')
def git(*args):
    return subprocess.check_output(['git',*args],cwd=ROOT,text=True).strip()
env=dotenv_values(ROOT/'.env')
allowed=['OLLAMA_MODEL','OLLAMA_NUM_CTX','OLLAMA_NUM_PREDICT','OLLAMA_PLAN_NUM_PREDICT','OLLAMA_TIMEOUT_SECONDS','GARMIN_COACH_AI_MAX_JOBS','GARMIN_COACH_ANSWER_MAX_CHARS','GARMIN_COACH_STALE_SYNC_MINUTES','ZEPP_SYNC_LOOKBACK_DAYS','ZEPP_ACTIVITY_SYNC_LOOKBACK_DAYS','STRAVA_ACTIVITY_SYNC_LOOKBACK_DAYS','WATTWISE_BRIDGE_AFTER_SYNC','WATTWISE_AI_CONTEXT','WATTWISE_AI_LOOKBACK_DAYS']
ref={'observed_at':datetime.now(timezone.utc).isoformat(),'commit':git('rev-parse','HEAD'),'branch':git('branch','--show-current'),'working_tree':git('status','--short'),'fixed_now':'2026-10-03T22:00:00+02:00','timezone':'Europe/Madrid','config_dotenv_allowlist':{k:env[k] for k in allowed if k in env},'config_note':'Valores del fichero local; el entorno heredado de procesos activos puede diferir. Nunca se guardan secretos.','railway':{'version':'no observable','reason':'Sin CLI Railway; /health no expone versión; loaders de datos ejecutan ensure_schema. No se llaman.'},'local_runtime':'LaunchAgents apuntan al checkout; procesos ya arrancados no atestiguados','hashes':{}}
for p in list((ROOT/'apps').rglob('*.py')):
    if '.venv' in p.parts: continue
    if p.name in ['ai_contracts.py','coach_generation_pipeline.py','coach_generation_contracts.py','coach_generation_context.py','coach_generation_renderer.py','sync.py','ai_worker.py']:
        ref['hashes'][str(p.relative_to(ROOT))]=hashlib.sha256(p.read_bytes()).hexdigest()
ref['database_connection_configured']=bool(env.get('DATABASE_URL'))
ref['python']=subprocess.check_output([str(ROOT/'apps/sync-local/.venv/bin/python'),'--version'],text=True).strip()
ref['launch_agents']=[]
for p in Path.home().joinpath('Library/LaunchAgents').glob('*garmin*'):
    d=plistlib.loads(p.read_bytes())
    ref['launch_agents'].append({k:d.get(k) for k in ['Label','ProgramArguments','WorkingDirectory','StartInterval','StartCalendarInterval','RunAtLoad']})
try:
    with httpx.Client(timeout=5,trust_env=False) as c:
        r=c.get('http://127.0.0.1:11434/api/tags');r.raise_for_status()
        ref['ollama_models']=[{k:m.get(k) for k in ['name','digest','size','modified_at','details']} for m in r.json().get('models',[])]
        r=c.get('http://127.0.0.1:11434/api/version');r.raise_for_status();ref['ollama_version']=r.json()
except Exception as e: ref['ollama_unavailable']=type(e).__name__
logs=[]
for p in Path.home().joinpath('Library/Logs').glob('garmin-coach*.log'):
    # Bound to last 2MB. No raw log lines or exception messages are exported.
    with p.open('rb') as f:
        f.seek(max(0,p.stat().st_size-2_000_000)); raw=f.read().decode(errors='replace')
    days=re.findall(r'\[(20\d\d-\d\d-\d\d) ',raw)
    events=Counter(re.findall(r'"type"\s*:\s*"(coach_[a-z_]+)"',raw))
    codes=Counter(re.findall(r'"code"\s*:\s*"([A-Z_]+)"',raw))
    logs.append({'file':p.name,'size':p.stat().st_size,'mtime':datetime.fromtimestamp(p.stat().st_mtime,timezone.utc).isoformat(),'sample_last_bytes':min(p.stat().st_size,2_000_000),'first_timestamp_day':min(days) if days else None,'last_timestamp_day':max(days) if days else None,'timestamp_counts_per_day':dict(Counter(days)),'validation_event_counts':dict(events),'validation_codes':dict(codes),'traceback_count':raw.count('Traceback (most recent call last)'), 'sync_finished_count':raw.count('Garmin Coach sync finished')})
save('referencia.json',ref);save('ejecuciones/operacion_local.json',logs)
print(json.dumps({'commit':ref['commit'],'ollama_available':'ollama_models' in ref,'database_connection_configured':ref['database_connection_configured'],'log_files':len(logs)}))
