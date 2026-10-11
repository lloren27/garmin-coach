"""Blind export, immutable rating seal and preregistered decision rule."""
import hashlib
import json
from pathlib import Path
import secrets

from experiment import DEFAULT, PROTOCOL_SEAL, prepare_cases, write_json, unique_object
from experiment_ollama import plain, digest


def read(path):
    return json.loads(path.read_text(), object_pairs_hook=unique_object)


def file_hash(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run_hash(run_dir):
    return digest({name:file_hash(run_dir/name) for name in ('manifest.json','baseline.json','results.json')
                   if (run_dir/name).exists()})

def mapping_hash(mapping):
    return digest(mapping)


def export_blind(run_dir: Path, review_dir: Path, key_path: Path) -> None:
    run_dir, review_dir, key_path = (p.resolve() for p in (run_dir,review_dir,key_path))
    if key_path.is_relative_to(review_dir) or run_dir.is_relative_to(review_dir):
        raise ValueError('BLIND_PATHS_OVERLAP')
    cases = prepare_cases()
    manifest = read(run_dir/'manifest.json')
    rows = read(run_dir/'results.json')
    expected_ids = {c['id'] for c in cases}
    if (manifest['status'] != 'generated' or manifest['protocol_seal'] != PROTOCOL_SEAL
            or set(manifest['case_ids']) != expected_ids
            or {r['case_id'] for r in rows} != expected_ids or len(rows) != len(cases)):
        raise ValueError('RUN_INCOMPLETE')
    if review_dir.exists() or key_path.exists():
        raise FileExistsError('REVIEW_ALREADY_EXISTS')
    review_dir.mkdir(parents=True)
    key_path.parent.mkdir(parents=True,exist_ok=True)
    outputs, mapping = [], {}
    for row in rows:
        for source in ('baseline','model'):
            opaque = secrets.token_hex(16)
            mapping[opaque] = {'case_id':row['case_id'],'source':source}
            outputs.append({'opaque_id':opaque,'case_id':row['case_id'],
                            'answer':row[source]['answer'] if row[source]['status']=='valid' else None})
    secrets.SystemRandom().shuffle(outputs)
    rubric = read(DEFAULT/'rubric.json')
    package = {'protocol_seal':PROTOCOL_SEAL,'dimensions':rubric['dimensions'],
        'instructions':'Puntúa cada salida sin consultar claves ni archivos de ejecución. Una salida nula no aporta respuesta: puntúa 0 y expectativas false. Justifica cada puntuación. No deduzcas ni anotes el origen.',
        'cases':{c['id']:{'question':c['question'],'clock':c['fixture']['now'],
            'input':c['fixture']['estado_inicial'],
            'components':plain(c['catalogs']), 'expectations':c['expectations']} for c in cases},
        'outputs':outputs}
    write_json(review_dir/'review.json',package)
    with key_path.open('x') as f:
        json.dump({'mapping':mapping, 'mapping_hash':mapping_hash(mapping), 'run_hash':run_hash(run_dir),
            'review_hash':file_hash(review_dir/'review.json'), 'review_dir':str(review_dir)},f,indent=2)
    template=[{'opaque_id':o['opaque_id'],'F':None,'P':None,'U':None,'R':None,
        'expected_checks_pass':None,'critical_errors':[],'justification':''} for o in outputs]
    write_json(review_dir/'ratings-template.json',template)


def validate_ratings(package, ratings):
    fields={'opaque_id','F','P','U','R','expected_checks_pass','critical_errors','justification'}
    expected={o['opaque_id'] for o in package['outputs']}
    if not isinstance(ratings,list) or len(ratings)!=len(expected):
        raise ValueError('RATINGS_INCOMPLETE')
    seen=set()
    for row in ratings:
        if not isinstance(row,dict) or set(row)!=fields:
            raise ValueError('RATING_FIELDS_INVALID')
        identifier=row['opaque_id']
        if not isinstance(identifier,str) or identifier not in expected or identifier in seen:
            raise ValueError('RATING_ID_INVALID')
        seen.add(identifier)
        if any(type(row[k]) is not int or row[k] not in (0,1,2) for k in 'FPUR'):
            raise ValueError('RATING_RANGE_INVALID')
        if (type(row['expected_checks_pass']) is not bool or not isinstance(row['critical_errors'],list)
                or any(not isinstance(e,str) or not e.strip() for e in row['critical_errors'])
                or not isinstance(row['justification'],str) or not row['justification'].strip()):
            raise ValueError('RATING_JUSTIFICATION_INVALID')


def seal_ratings(review_dir: Path, ratings_path: Path) -> str:
    package=read(review_dir/'review.json'); ratings=read(ratings_path)
    validate_ratings(package,ratings)
    seal={'review_hash':file_hash(review_dir/'review.json'), 'ratings_hash':file_hash(ratings_path)}
    # Store seal beside scores so evaluate can locate it without trusting a mutable ratings path in the key.
    seal_path=ratings_path.with_suffix(ratings_path.suffix+'.seal.json')
    with seal_path.open('x') as f:
        json.dump(seal,f,indent=2)
    return seal['ratings_hash']


def evaluate_ratings(run_dir: Path, ratings_path: Path, key_path: Path) -> dict:
    seal_path=ratings_path.with_suffix(ratings_path.suffix+'.seal.json')
    if not seal_path.exists():
        raise ValueError('RATINGS_NOT_SEALED')
    seal=read(seal_path); key=read(key_path)
    review_dir=Path(key['review_dir'])
    if (seal['ratings_hash']!=file_hash(ratings_path) or seal['review_hash']!=key['review_hash']
            or key.get('mapping_hash') != mapping_hash(key['mapping'])
            or key['review_hash']!=file_hash(review_dir/'review.json') or key['run_hash']!=run_hash(run_dir)):
        raise ValueError('SEALED_INPUT_CHANGED')
    package=read(review_dir/'review.json'); ratings=read(ratings_path)
    validate_ratings(package,ratings)
    rubric=read(DEFAULT/'rubric.json')
    mapped={}
    for rating in ratings:
        entry=key['mapping'][rating['opaque_id']]
        mapped.setdefault(entry['case_id'],{})[entry['source']]=rating
    rows=read(run_dir/'results.json')
    if any(r['model']['status'] in {'no_evaluado','started'} for r in rows):
        return {'decision':'pending','model_retained':False,'reason':'infrastructure_not_evaluated'}
    failures=[]
    pairs={v['id'] for v in read(DEFAULT/'fixtures.json')['variants'] if v.get('pair') in rubric['comparison']['eligible_pairs']}
    for row in rows:
        identifier=row['case_id']; scores=mapped[identifier]; m=scores['model']; b=scores['baseline']
        passed=(row['model']['status']=='valid' and m['expected_checks_pass'] and not m['critical_errors']
                and all(m[k]>=b[k] for k in 'FPR'))
        if identifier in pairs:
            passed=passed and m['U']>b['U']
        if not passed:
            failures.append(identifier)
    return {'decision':'deterministic' if failures else 'model_wins','model_retained':not failures,
            'failed_cases':failures, 'ratings_hash':seal['ratings_hash'],
            'limitations':rubric['blind_review']['limitations'],
            'integration_authorized':False}


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action',choices=['export','seal','evaluate'])
    parser.add_argument('--run',type=Path);parser.add_argument('--review',type=Path)
    parser.add_argument('--key',type=Path);parser.add_argument('--ratings',type=Path)
    args=parser.parse_args()
    required={'export':('run','review','key'),'seal':('review','ratings'),'evaluate':('run','ratings','key')}
    if any(getattr(args,k) is None for k in required[args.action]):
        parser.error('Missing arguments: '+', '.join(required[args.action]))
    if args.action=='export': export_blind(args.run,args.review,args.key)
    elif args.action=='seal': print(seal_ratings(args.review,args.ratings))
    else: print(json.dumps(evaluate_ratings(args.run,args.ratings,args.key),ensure_ascii=False,indent=2))
