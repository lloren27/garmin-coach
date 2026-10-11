"""Single-attempt local Ollama transport; never imports the worker or loads .env."""
from collections.abc import Mapping
from dataclasses import fields, is_dataclass
from datetime import date
from decimal import Decimal
from enum import Enum
import hashlib
import json
import httpx

MODEL = 'garmin-coach:9b'
OPTIONS = {'temperature': 0, 'num_predict': 900, 'num_ctx': 32768, 'top_p': 0.9, 'top_k': 20}
TIMEOUT = 600
client = httpx.Client
SYSTEM = '''Selecciona y ordena hallazgos pertinentes a la pregunta exclusivamente del catálogo dado.
Devuelve JSON con selections, una selección por componente en el mismo orden. No escribas prosa nueva.
Cada selección contiene schema_version="1", snapshot_id, component_index, finding_ids y follow_up.
Máximo 3 hallazgos focales por componente; añade required_ids y dependencies aunque excedan ese cupo.
No inventes IDs, hechos, fechas ni permisos. No traslades referencias entre componentes.
No omitas todos los hallazgos si existe uno relevante. Usa exactamente el snapshot_id suministrado.
El seguimiento se determina por los códigos elegidos, por prioridad:
1. SYMPTOM_REPORTED o SESSION_SAFETY_NOT_ASSESSABLE: CLARIFY_SYMPTOM_CONTEXT.
2. PLAN_MATCH_UNCONFIRMED, PLAN_MATCH_AMBIGUOUS o PLAN_ACTIVITY_MAGNITUDE_MISMATCH: CONFIRM_PLAN_MATCH.
3. Selección vacía, DATA_COVERAGE_INCOMPLETE, PLAN_MATCH_INSUFFICIENT_DATA o NO_PLAN_FOR_SCOPE: PROVIDE_MISSING_CONTEXT.
4. WELLNESS_BASELINE_UNAVAILABLE o WELLNESS_TREND_NOT_ASSESSABLE: REVIEW_HISTORY_WINDOW.
5. En otro caso: null. No generes prescripciones, propuestas ni decisiones sobre el plan.'''
SCHEMA = {'type':'object', 'additionalProperties':False, 'required':['selections'], 'properties':{
    'selections': {'type':'array', 'items': {'type':'object', 'additionalProperties':False,
        'required':['schema_version','snapshot_id','component_index','finding_ids','follow_up'],
        'properties': {'schema_version':{'type':'string','enum':['1']},
            'snapshot_id':{'type':'string'}, 'component_index':{'type':'integer'},
            'finding_ids':{'type':'array','items':{'type':'string'}},
            'follow_up':{'type':['string','null'], 'enum':[None,'CLARIFY_SYMPTOM_CONTEXT',
                'CONFIRM_PLAN_MATCH','PROVIDE_MISSING_CONTEXT','REVIEW_HISTORY_WINDOW']}}}}}}


def plain(value):
    if is_dataclass(value):
        return {f.name: plain(getattr(value, f.name)) for f in fields(value)}
    if isinstance(value, Mapping):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    return value


def encoded(value):
    return json.dumps(plain(value), ensure_ascii=False, sort_keys=True, separators=(',', ':'))


def digest(value):
    return hashlib.sha256(encoded(value).encode()).hexdigest()


def make_payload(case):
    context = {'question':case['question'], 'components': [
        {'facts':plain(cat.facts), 'findings':plain(cat.findings), 'required_ids':list(cat.required_ids)}
        for cat in case['catalogs']]}
    return {'model': MODEL, 'stream':False, 'think':False, 'options': dict(OPTIONS), 'format':SCHEMA,
            'messages':[{'role':'system','content':SYSTEM}, {'role':'user','content':encoded(context)}]}


def inspect_model(base_url: str, model: str = MODEL) -> dict:
    with client(timeout=10, trust_env=False) as session:
        response = session.get(base_url.rstrip('/') + '/api/tags'); response.raise_for_status()
        matches = [r for r in response.json()['models'] if r.get('name') == model or r.get('model') == model]
        if len(matches) != 1 or not matches[0].get('digest'):
            raise ValueError('MODEL_NOT_AVAILABLE')
        response = session.post(base_url.rstrip('/') + '/api/show', json={'model':model}); response.raise_for_status()
        details = response.json()
    return {'model':model, 'digest':matches[0]['digest'],
            'configuration_hash':digest(details), 'options':OPTIONS, 'timeout_seconds':TIMEOUT,
            'think':False, 'stream':False}


def generate_selection(base_url: str, payload: dict) -> str:
    with client(timeout=TIMEOUT, trust_env=False) as session:
        response = session.post(base_url.rstrip('/') + '/api/chat', json=payload)
        response.raise_for_status()
        try:
            content = response.json()['message']['content']
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ValueError('MODEL_ENVELOPE_INVALID') from exc
        if not isinstance(content, str):
            raise ValueError('MODEL_CONTENT_INVALID')
        return content
