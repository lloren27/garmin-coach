"""Read-only verification of the preregistered Phase 3 evaluation protocol.

This module never imports the product, loads .env, runs selectors or calls models.
"""
import copy
from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
DEFAULT = Path(__file__).parent / 'v1'
FILES = ('fixtures', 'expectations', 'selector_map', 'rubric')
ORIGINALS = {f'E{i:02}' for i in range(1, 18)} - {'E15'} | {'E15a', 'E15b'}


def materialize(fixtures: dict, variant: dict) -> dict:
    """Copy base fixture; apply existing JSON-pointer replacements only."""
    result = copy.deepcopy(fixtures['base_fixtures'][variant['base']])
    for pointer, value in variant['replace'].items():
        if not pointer.startswith('/estado_inicial/'):
            raise ValueError('Replacement must be inside estado_inicial')
        keys = [k.replace('~1', '/').replace('~0', '~') for k in pointer[1:].split('/')]
        node = result
        for key in keys[:-1]:
            node = node[int(key)] if isinstance(node, list) else node[key]
        key = int(keys[-1]) if isinstance(node, list) else keys[-1]
        node[key]  # Require existing target; replacements cannot invent fields.
        node[key] = copy.deepcopy(value)
    result.update(id=variant['id'], pregunta=variant['question'],
                  operaciones=[variant['question']])
    return result


def validate_contract(bundle: dict) -> list[str]:
    errors = []
    try:
        for name in FILES:
            if bundle[name]['protocol_version'] != 'fase3-v1':
                errors.append(f'version:{name}')
        fixtures = bundle['fixtures']
        bases = fixtures['base_fixtures']
        cases = bundle['expectations']['cases']
        variants = fixtures['variants']
        ids = list(bases) + [v['id'] for v in variants]
        if len(ids) != len(set(ids)):
            errors.append('duplicate_ids')
        if set(bases) != ORIGINALS | {'R01'} or set(ids) != set(cases):
            errors.append('case_coverage')
        for case_id, fixture in bases.items():
            now = datetime.fromisoformat(fixture['now'])
            if now.tzinfo is None or now.utcoffset() is None:
                errors.append(f'aware_now:{case_id}')
            if fixture['id'] != case_id:
                errors.append(f'fixture_id:{case_id}')
        for case_id, expectation in cases.items():
            if expectation['status'] != 'not_run':
                errors.append(f'premature_result:{case_id}')
            if not expectation['required_checks']:
                errors.append(f'empty_expectations:{case_id}')
            if set(expectation['required_codes']) & set(expectation['forbidden_codes']):
                errors.append(f'conflicting_codes:{case_id}')
        pairs = {}
        families = {f['id'] for f in bundle['selector_map']['families']}
        for variant in variants:
            materialize(fixtures, variant)
            if variant['focus'] not in families:
                errors.append(f'unknown_focus:{variant["id"]}')
            if variant['pair']:
                pairs.setdefault(variant['pair'], []).append(variant)
        if set(pairs) != set(bundle['rubric']['comparison']['eligible_pairs']) or len(pairs) != 3:
            errors.append('pair_coverage')
        for pair_id, members in pairs.items():
            if len(members) != 2 or len({v['focus'] for v in members}) != 2:
                errors.append(f'pair_members:{pair_id}')
                continue
            facts = [materialize(fixtures, v) for v in members]
            if (facts[0]['estado_inicial'] != facts[1]['estado_inicial'] or
                    facts[0]['now'] != facts[1]['now'] or
                    any(v['replace'] for v in members) or
                    len({v['base'] for v in members}) != 1):
                errors.append(f'pair_facts:{pair_id}')
        if len({v['base'] for v in variants if v['pair']}) < 2:
            errors.append('pair_base_diversity')
        for case_id in ('E01-mixto', 'E10-mixto'):
            expected = cases[case_id]
            forbidden = {'keep_plan', 'prescription', 'change_proposal', 'plan_mutation'}
            if not forbidden.issubset(expected['forbidden_actions']):
                errors.append(f'mixed_actions:{case_id}')
            if expected['components'][1]['allowed_outcome'] != 'clarification_only':
                errors.append(f'mixed_outcome:{case_id}')
        safety = cases['E10-mixto']
        if ('SESSION_SAFETY_NOT_ASSESSABLE' not in safety['required_codes'] or
                'No puedo valorar si es seguro hacerla' not in safety['required_text']):
            errors.append('mixed_safety')
        multiple = cases['MATCH-multiple']
        if (multiple['relation'] != 'ambiguous_multiple' or
                'PLAN_ACTIVITY_MAGNITUDE_MISMATCH' in multiple['required_codes'] or
                'PLAN_ACTIVITY_MAGNITUDE_MISMATCH' not in multiple['forbidden_codes']):
            errors.append('multiple_match')
        if cases['E01']['relation'] != 'implausible_single' or cases['R01']['relation'] != 'candidate':
            errors.append('reference_match_states')
        if bundle['rubric']['comparison']['tie_winner'] != 'deterministic':
            errors.append('tie_policy')
        if bundle['rubric']['execution']['status'] != 'not_run':
            errors.append('premature_evaluation')
        if cases['E14']['coverage'] != 'partial':
            errors.append('e14_scope')
    except (KeyError, TypeError, ValueError, IndexError) as exc:
        errors.append(f'schema:{type(exc).__name__}')
    return errors


def verify(directory: Path = DEFAULT) -> list[str]:
    errors, bundle = [], {}
    for name in (*FILES, 'manifest'):
        try:
            bundle[name] = json.loads((directory / f'{name}.json').read_text())
        except (OSError, ValueError):
            errors.append(f'json:{name}')
    if errors:
        return errors
    manifest = bundle['manifest']
    try:
        if manifest['protocol_version'] != 'fase3-v1' or manifest['phase'] != 'pre_generation':
            errors.append('manifest_phase')
        if set(manifest['files']) != {f'{name}.json' for name in FILES}:
            errors.append('manifest_files')
        for name in FILES:
            actual = hashlib.sha256((directory / f'{name}.json').read_bytes()).hexdigest()
            if actual != manifest['files'].get(f'{name}.json'):
                errors.append(f'hash:{name}.json')
        if set(manifest['sources']) != ORIGINALS:
            errors.append('manifest_sources')
        for case_id in sorted(ORIGINALS):
            path = ROOT / 'docs/restructuring/fase0_resultados/casos' / f'{case_id}.json'
            original = path.read_bytes()
            if hashlib.sha256(original).hexdigest() != manifest['sources'].get(case_id):
                errors.append(f'source_hash:{case_id}')
            if json.loads(original) != bundle['fixtures']['base_fixtures'][case_id]:
                errors.append(f'source_copy:{case_id}')
    except (KeyError, TypeError, ValueError, OSError):
        errors.append('manifest_schema_or_source')
    errors.extend(validate_contract(bundle))
    return errors


if __name__ == '__main__':
    directory = Path(sys.argv[1]) if len(sys.argv) == 2 else DEFAULT
    errors = verify(directory)
    print(json.dumps({'protocol': 'fase3-v1', 'errors': errors,
                      'evaluation_executed': False}, ensure_ascii=False))
    raise SystemExit(bool(errors))
