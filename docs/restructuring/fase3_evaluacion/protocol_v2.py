"""V2 overlay and deterministic preflight; does not generate Ollama responses."""
import copy
import hashlib
import json
from pathlib import Path

from experiment import DEFAULT, PROTOCOL_SEAL, prepare_cases, build_snapshot, build_catalog
from verify_protocol import verify

V2 = Path(__file__).parent / 'v2' / 'protocol.json'
V2_SEAL = '0801e6871c71d22e442792c817b2f56645b7b73868cd7d42d3c3ec25c9382d91'


def verify_v2():
    errors = verify(DEFAULT)
    if hashlib.sha256((DEFAULT / 'manifest.json').read_bytes()).hexdigest() != PROTOCOL_SEAL:
        errors.append('parent_seal')
    if hashlib.sha256(V2.read_bytes()).hexdigest() != V2_SEAL:
        errors.append('v2_seal')
    return errors


def prepare_v2():
    if verify_v2():
        raise ValueError('V2_PROTOCOL_INVALID')
    overlay = json.loads(V2.read_text())
    cases = prepare_cases(DEFAULT)
    for case in cases:
        if case['id'] not in overlay['question_overrides']:
            continue
        question = overlay['question_overrides'][case['id']]
        fixture = copy.deepcopy(case['fixture'])
        fixture.update(pregunta=question, operaciones=[question])
        snapshot = build_snapshot(question, fixture['estado_inicial'], now=case['snapshot'].now)
        catalogs = tuple(build_catalog(snapshot, i, question) for i in range(len(snapshot.intent.components)))
        case.update(question=question, fixture=fixture, snapshot=snapshot, catalogs=catalogs)
    return cases


if __name__ == '__main__':
    from garmin_sync.coach_findings import select_findings
    from experiment import render_candidate
    cases = prepare_v2()
    for case in cases:
        selections = tuple(select_findings(cat, case['question']) for cat in case['catalogs'])
        print(json.dumps({'case_id':case['id'], 'protocol':'fase3-v2',
            'answer':render_candidate(case['catalogs'], selections, snapshot=case['snapshot'])}, ensure_ascii=False))
