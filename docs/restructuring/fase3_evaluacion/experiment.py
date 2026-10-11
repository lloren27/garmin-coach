"""Offline Phase 3 experiment. Importing this module performs no I/O to services."""
from dataclasses import asdict
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'apps/sync-local'))
from verify_protocol import DEFAULT, verify, materialize
from garmin_sync.coach_generation_context import build_snapshot
from garmin_sync.coach_findings import AnalysisSelection, build_catalog, validate_selection
from garmin_sync.coach_deterministic import render_selected_response

PROTOCOL_SEAL = 'cd43210d439c25d7a8bf93579ce936d83b116ffead42fe78d2698e71fa84caf0'


def prepare_cases(protocol_dir: Path = DEFAULT) -> list[dict]:
    if hashlib.sha256((protocol_dir / 'manifest.json').read_bytes()).hexdigest() != PROTOCOL_SEAL:
        raise ValueError('PROTOCOL_SEAL_INVALID')
    errors = verify(protocol_dir)
    if errors:
        raise ValueError('PROTOCOL_INVALID')
    fixtures = json.loads((protocol_dir / 'fixtures.json').read_text())
    rubric = json.loads((protocol_dir / 'rubric.json').read_text())
    expectations = json.loads((protocol_dir / 'expectations.json').read_text())['cases']
    variants = {v['id']: v for v in fixtures['variants']}
    ids = [v['id'] for v in fixtures['variants'] if v.get('pair') in rubric['comparison']['eligible_pairs']]
    ids += rubric['comparison']['guard_cases']
    cases = []
    for identifier in ids:
        row = (materialize(fixtures, variants[identifier]) if identifier in variants
               else fixtures['base_fixtures'][identifier])
        question = row['pregunta']
        snapshot = build_snapshot(question, row['estado_inicial'], now=datetime.fromisoformat(row['now']))
        catalogs = tuple(build_catalog(snapshot, i, question) for i in range(len(snapshot.intent.components)))
        cases.append(dict(id=identifier, question=question, fixture=row, snapshot=snapshot,
                          catalogs=catalogs, expectations=expectations[identifier]))
    return cases


def unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('JSON_DUPLICATE_KEY')
        result[key] = value
    return result


def parse_selections(raw: str, catalogs: tuple) -> tuple[AnalysisSelection, ...]:
    try:
        data = json.loads(raw, object_pairs_hook=unique_object)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError('SELECTION_JSON_INVALID') from exc
    if not isinstance(data, dict) or set(data) != {'selections'}:
        raise ValueError('SELECTION_FIELDS_INVALID')
    rows = data['selections']
    if not isinstance(rows, list) or len(rows) != len(catalogs):
        raise ValueError('SELECTION_COMPONENTS_INVALID')
    result = []
    for row, catalog in zip(rows, catalogs):
        if not isinstance(row, dict) or set(row) != {'schema_version', 'snapshot_id', 'component_index', 'finding_ids', 'follow_up'}:
            raise ValueError('SELECTION_FIELDS_INVALID')
        if (type(row['component_index']) is not int or not isinstance(row['finding_ids'], list)
                or any(not isinstance(i, str) for i in row['finding_ids'])
                or (row['follow_up'] is not None and not isinstance(row['follow_up'], str))):
            raise ValueError('SELECTION_TYPES_INVALID')
        selection = AnalysisSelection(**{**row, 'finding_ids': tuple(row['finding_ids'])})
        validate_selection(catalog, selection)
        result.append(selection)
    return tuple(result)


def render_candidate(catalogs: tuple, selections: tuple, *, snapshot) -> str:
    return render_selected_response(snapshot, catalogs, selections).answer


def write_json(path: Path, value):
    from experiment_ollama import plain
    # Atomic replacement of our own checkpoint; output directory creation is exclusive.
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(plain(value), ensure_ascii=False, indent=2) + '\n')
    temp.replace(path)


def run_experiment(protocol_dir: Path, output_dir: Path, base_url: str) -> dict:
    import time
    import httpx
    from experiment_ollama import inspect_model, generate_selection, make_payload, digest, plain
    from garmin_sync.coach_findings import select_findings
    output_dir.mkdir(parents=True, exist_ok=False)
    cases = prepare_cases(protocol_dir)
    baselines = []
    for case in cases:
        selections = tuple(select_findings(cat, case['question']) for cat in case['catalogs'])
        baselines.append({'case_id':case['id'], 'status':'valid', 'selections':plain(selections),
            'answer':render_candidate(case['catalogs'], selections, snapshot=case['snapshot'])})
    write_json(output_dir / 'baseline.json', baselines)
    model = inspect_model(base_url)
    payloads = [make_payload(case) for case in cases]
    code_paths = sorted((ROOT / 'apps/sync-local/garmin_sync').glob('*.py'))
    code_paths += sorted(Path(__file__).parent.glob('experiment*.py'))
    selector_path = ROOT / 'apps/sync-local/garmin_sync/coach_selector_v1.json'
    manifest = {'protocol_seal':PROTOCOL_SEAL, 'model':model, 'case_ids':[c['id'] for c in cases],
        'payload_hashes':{c['id']:digest(p) for c,p in zip(cases,payloads)},
        'input_hashes':{c['id']:digest(c['fixture']) for c in cases},
        'code_hashes':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in code_paths},
        'selector_map_hash': hashlib.sha256(selector_path.read_bytes()).hexdigest(),
        'selection_flags':{'v3':True,'enforcement':True},
        'flag_scope':'offline validated selections only; worker routing matrix not evaluated here',
        'production_flags_modified':False, 'attempts_per_question':1, 'repairs':0, 'fallbacks':0,
        'started_at':datetime.now().astimezone().isoformat(), 'status':'running'}
    write_json(output_dir / 'manifest.json', manifest)
    rows = []
    for case, baseline, payload in zip(cases, baselines, payloads):
        if inspect_model(base_url) != model:
            manifest.update(status='aborted', reason='MODEL_CONFIGURATION_DRIFT')
            break
        row = {'case_id':case['id'], 'baseline':baseline,
               'model':{'status':'started', 'answer':None, 'selections':None}}
        path = output_dir / f"case-{case['id']}.json"
        write_json(path, row)
        started = time.monotonic()
        try:
            raw = generate_selection(base_url, payload)
            row['model']['response_hash'] = hashlib.sha256(raw.encode()).hexdigest()
            selections = parse_selections(raw, case['catalogs'])
            answer = render_candidate(case['catalogs'], selections, snapshot=case['snapshot'])
            row['model'].update(status='valid', selections=plain(selections), answer=answer)
        except httpx.HTTPError:
            row['model'].update(status='no_evaluado', error='TRANSPORT_FAILURE')
        except ValueError:
            row['model'].update(status='invalid_selection', error='MODEL_SELECTION_INVALID')
        row['model']['latency_seconds'] = round(time.monotonic() - started, 4)
        # Reject outputs if the tag/configuration changed while a request was in flight.
        try:
            stable = inspect_model(base_url) == model
        except (httpx.HTTPError, ValueError):
            stable = False
        if not stable:
            row['model'].update(status='no_evaluado', answer=None, selections=None, error='MODEL_CONFIGURATION_DRIFT')
            manifest.update(status='aborted', reason='MODEL_CONFIGURATION_DRIFT')
        write_json(path, row)
        rows.append(row)
        write_json(output_dir / 'results.json', rows)
        with (output_dir / 'events.jsonl').open('a') as log:
            log.write(json.dumps({'case_id':case['id'], 'status':row['model']['status'],
                                  'latency_seconds':row['model']['latency_seconds']}) + '\n')
        print(f"{case['id']}: {row['model']['status']} ({row['model']['latency_seconds']} s)", flush=True)
        if not stable:
            break
    if manifest['status'] == 'running':
        manifest['status'] = 'generated'
    manifest['finished_at'] = datetime.now().astimezone().isoformat()
    write_json(output_dir / 'manifest.json', manifest)
    return manifest


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--url', default='http://127.0.0.1:11434')
    args = parser.parse_args()
    run_experiment(DEFAULT, args.output, args.url)
