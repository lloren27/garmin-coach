"""Read only /health and local Ollama metadata. No application imports or jobs."""
import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

import httpx
from dotenv import dotenv_values

OUT = Path(__file__).resolve().parent
ROOT = OUT.parents[2]
DEST = OUT / 'ejecuciones' / '2026-10-04-servicios.json'
config = dotenv_values(ROOT / '.env')
report = {
    'observed_at': datetime.now(timezone.utc).isoformat(),
    'commit': subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT, text=True).strip(),
    'application_diff_from_previous_audit': subprocess.check_output(
        ['git', 'diff', '--name-only', 'b6912b9', 'HEAD', '--', 'apps', 'scripts'],
        cwd=ROOT, text=True).splitlines(),
    'files': {},
}
for rel in ('apps/sync-local/garmin_sync/ai_worker.py',
            'apps/sync-local/garmin_sync/coach_generation_pipeline.py',
            'apps/sync-local/garmin_sync/coach_generation_contracts.py',
            'apps/bot/app/main.py'):
    report['files'][rel] = hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()
defaults = {'OLLAMA_MODEL': 'garmin-coach:9b', 'OLLAMA_NUM_CTX': '32768',
            'OLLAMA_NUM_PREDICT': '900', 'OLLAMA_PLAN_NUM_PREDICT': '1400',
            'OLLAMA_TIMEOUT_SECONDS': '600'}
report['local_file_config_or_code_default'] = {k: config.get(k) or v for k, v in defaults.items()}
report['note'] = 'No atestigua entorno de un proceso ya arrancado ni commit remoto.'
with httpx.Client(timeout=10, trust_env=False, follow_redirects=False) as client:
    for path in ('/api/version', '/api/tags', '/api/ps'):
        try:
            response = client.get('http://127.0.0.1:11434' + path)
            response.raise_for_status()
            data = response.json()
            if path == '/api/version':
                report['ollama_version'] = data.get('version')
            else:
                report[path] = [{k: row.get(k) for k in ('name', 'digest', 'size', 'context_length')}
                               for row in data.get('models', [])]
        except Exception as error:
            report[path] = {'error_type': type(error).__name__}
    base = (config.get('GARMIN_COACH_API_URL') or '').rstrip('/')
    parsed = urlsplit(base)
    if parsed.scheme == 'https' and parsed.hostname and not parsed.username and not parsed.query:
        try:
            response = client.get(base + '/health')
            data = response.json() if response.status_code == 200 else {}
            report['backend_health'] = {'http_status': response.status_code,
                                        'status': data.get('status'),
                                        'remote_commit': 'not exposed by /health'}
        except Exception as error:
            report['backend_health'] = {'error_type': type(error).__name__}
    else:
        report['backend_health'] = {'status': 'not checked', 'reason': 'No configured HTTPS API URL'}
with DEST.open('x') as output:
    output.write(json.dumps(report, ensure_ascii=False, indent=2) + '\n')
print(json.dumps({'commit': report['commit'], 'backend_health': report['backend_health'],
                  'ollama_version': report.get('ollama_version'),
                  'application_diff': report['application_diff_from_previous_audit']}))
