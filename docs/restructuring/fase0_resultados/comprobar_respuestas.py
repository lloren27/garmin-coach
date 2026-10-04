"""Summarize captured real runs and check numeric/source traceability, not coaching quality."""
import json
import re
import statistics
from pathlib import Path

OUT = Path(__file__).resolve().parent
RUN = OUT / 'ejecuciones/2026-10-04-ollama'


def numbers(value):
    if isinstance(value, bool):
        return set()
    if isinstance(value, (float, int)):
        return {float(value)}
    if isinstance(value, dict):
        return set().union(*(numbers(v) for v in value.values())) if value else set()
    if isinstance(value, list):
        return set().union(*(numbers(v) for v in value)) if value else set()
    return set()


def check(record, case):
    answer = record.get('wire', {}).get('answer', '')
    data = case['estado_inicial']
    allowed = numbers(data)
    derived = []
    for activity in data.get('extra_context', {}).get('recent_activities', []):
        seconds = activity.get('duration_s', 0)
        distance = activity.get('km', activity.get('distance_km', 0))
        if seconds:
            hours, rest = divmod(round(seconds), 3600)
            minutes, remainder = divmod(rest, 60)
            allowed.update([hours, minutes, remainder, round(seconds/60), round(seconds/60, 1)])
            derived.append({'id': activity['id'], 'elapsed_h_m_s': [hours, minutes, remainder]})
        if seconds and distance:
            pace_min, pace_sec = divmod(round(seconds/distance), 60)
            speed = round(distance / (seconds / 3600), 1)
            allowed.update([pace_min, pace_sec, speed])
            derived[-1].update(pace_min_sec=[pace_min, pace_sec], speed_kmh=speed)
    # Dates are checked separately; don't turn an unverified date into three allowed numbers.
    dates = re.findall(r'\b\d{4}-\d{2}-\d{2}\b', answer)
    input_dates = set(re.findall(r'\b\d{4}-\d{2}-\d{2}\b', json.dumps(data)))
    input_dates.add(case['now'][:10])
    clean = re.sub(r'\b\d{4}-\d{2}-\d{2}\b', '', answer)
    found = [float(v.replace(',', '.')) for v in re.findall(r'(?<!\w)\d+(?:[.,]\d+)?', clean)]
    unsupported = [v for v in found if not any(abs(v-n) <= .01 for n in allowed)]
    dose_values = numbers(record.get('wire', {}).get('decisions', []))
    prescribed = sorted({v for v in unsupported if v in dose_values})
    attributed = (re.findall(r'^(Garmin|Zepp|Strava|Wattwise)\s*\(', answer, re.M)
                  + re.findall(r'\((Garmin|Zepp|Strava|Wattwise)\):', answer))
    sources = set(re.findall(r'"source":\s*"([a-z_]+)"', json.dumps(data)))
    return {'derived_values': derived, 'unsupported_numeric_values': sorted(set(unsupported)),
            'of_those_structured_prescription_values_requiring_review': prescribed,
            'dates_not_in_input': sorted(set(dates)-input_dates),
            'unsupported_attributions': [s for s in attributed if s.lower() not in sources],
            'limit': 'Checks numeric membership/conversions and explicit attributions only; does not validate semantic interpretation.'}


def main():
    records = []
    for path in sorted(RUN.glob('E*_ollama_*.json')):
        record = json.loads(path.read_text())
        case = json.loads((OUT / 'casos' / (record['id']+'.json')).read_text())
        records.append({'file': path.name, 'id': record['id'], 'repetition': record['repetition'],
                        'seconds': record['seconds'], 'repairs': record['repairs'],
                        'valid_output': 'wire' in record, 'validation_codes': record.get('validation_codes'),
                        'answer': record.get('wire', {}).get('answer'),
                        'automatic_checks': check(record, case) if 'wire' in record else None})
    assert len(records) == 18, f'Expected 18 completed attempts, got {len(records)}'
    summary = {'runs': len(records), 'valid_outputs': sum(r['valid_output'] for r in records),
               'repairs': sum(r['repairs'] for r in records),
               'latency_seconds': {'min': min(r['seconds'] for r in records),
                                   'median': statistics.median(r['seconds'] for r in records),
                                   'max': max(r['seconds'] for r in records)}, 'records': records}
    with (RUN/'resumen_automatico.json').open('x') as stream:
        stream.write(json.dumps(summary, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='records'}))


if __name__ == '__main__':
    main()
