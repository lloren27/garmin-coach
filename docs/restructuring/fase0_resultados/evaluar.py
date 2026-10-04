"""Phase 0 baseline. Only synthetic fixtures, no production jobs or application secrets."""
import sys,os,json,time,copy,io,hashlib,asyncio,socket
from pathlib import Path
from datetime import datetime
from contextlib import redirect_stdout,ExitStack
from unittest.mock import patch,AsyncMock
import re
from zoneinfo import ZoneInfo
from aislamiento import install
OUT=Path(__file__).resolve().parent; ROOT=OUT.parents[2]
LIVE='--ollama' in sys.argv
ONLY=next((a.split('=',1)[1] for a in sys.argv if a.startswith('--case=')),None)
RUN=next((a.split('=',1)[1] for a in sys.argv if a.startswith('--run=')),None)
if not RUN or not re.fullmatch(r'[a-zA-Z0-9_-]+', RUN):
    raise SystemExit('Specify a unique --run=YYYY-MM-DD-label; previous results are never overwritten.')
RESULTS=OUT/'ejecuciones'/RUN
RESULTS.mkdir(parents=True,exist_ok=True)
TMP,BLOCKED=install(OUT,live=LIVE)
sys.path[:0]=[str(ROOT/'apps/bot'),str(ROOT/'apps/sync-local')]
# Reuse installed bot-only dependencies without installing or changing either venv.
sys.path.extend(str(p) for p in (ROOT/'apps/bot/.venv/lib').glob('python*/site-packages'))
from garmin_sync.coach_generation_context import build_snapshot
from garmin_sync.coach_generation_pipeline import generate_validated
from garmin_sync.coach_validation import CoachValidationError
from garmin_sync.activity_merge import merge_activities
NOW=datetime.fromisoformat('2026-10-03T22:00:00+02:00')
class FrozenDatetime(datetime):
    @classmethod
    def now(cls,tz=None):return NOW.astimezone(tz) if tz else NOW.replace(tzinfo=None)

def write(name,data):
    with (RESULTS/name).open('x') as f:
        f.write(json.dumps(data,ensure_ascii=False,indent=2,default=str)+'\n')
def pub(c):return build_snapshot(c.get('pregunta','hoy'),c['estado_inicial'],now=NOW).public_context()
def result(ok,obs,limit=None):return {'resultado':'cumple' if ok else 'incumple','observado':obs,'limitacion':limit}
def source_records(value):
    """Explicit source/identifier pairs, never mere provider-name substrings."""
    found=set()
    if isinstance(value,dict):
        if value.get('source') and (value.get('id') or value.get('source_activity_id')):
            found.add((value['source'],str(value.get('id') or value['source_activity_id'])))
        for child in value.values():found.update(source_records(child))
    elif isinstance(value,list):
        for child in value:found.update(source_records(child))
    return found
def store_setup():
    from app import main,store,pending_changes,coach
    store.DATABASE_URL=None
    for k,v in list(vars(store).items()):
        if isinstance(v,Path) and (k.endswith('_FILE') or k=='DATA_DIR'):
            setattr(store,k,TMP/'data'/v.name if k!='DATA_DIR' else TMP/'data')
    for m in (store,pending_changes,coach):
        if hasattr(m,'datetime'):m.datetime=FrozenDatetime
    return main,store

def test_isolation():
    checks={}
    for label,fn in [('write_product',lambda:(ROOT/'audit-forbidden.tmp').write_text('x')),('read_env',lambda:(ROOT/'.env').read_text()),('network',lambda:socket.create_connection(('127.0.0.1',9),timeout=.1))]:
        try:fn();checks[label]=False
        except PermissionError:checks[label]=True
    assert all(checks.values()),checks
    write('aislamiento.json',{'checks':checks,'temporary_root':str(TMP),'live_socket_allowlist':['127.0.0.1:11434'] if LIVE else [],'note':'Guardia Python para este evaluador; no es una frontera contra código nativo malicioso.'})

def deterministic(c):
    id=c['id']; initial=c['estado_inicial']
    if id=='E02':
        rows=merge_activities(initial['garmin'],[],initial['strava'])
        expected=source_records(initial)
        return result(len(rows)==1 and expected.issubset(source_records(rows)),rows,'Deduplicación sí; se exige además conservar pares explícitos de origen e identificador.')
    if id=='E03':
        snap=pub(c);return result(snap['available_evidence'][0]['source']=='strava',snap)
    if id=='E04':
        rows=merge_activities(initial['garmin'],[]);return result(len(rows)==2,rows)
    if id=='E05':
        _,store=store_setup(); day=initial['day'];out=[]
        for score in initial['scores']:
            val={} if score is None else {'sleep':{'source':'zepp','score':score,'total_minutes':430}}
            store.upsert_wellness_days({'wellness':{'schema_version':2,'zepp':{day:val},'history':{day:{'effective':{'date':day,**val}}}}})
            out.append(store.load_wellness_history())
        rows=out[-1]
        r=result(len(rows)==1 and rows[day]['sources']['zepp']['sleep']['score']==82,out,'Almacén de ficheros; PostgreSQL y reconsulta del proveedor no ejecutados. Ver pruebas_ampliadas.py para la reconsulta.')
        r['subcomprobacion']=r['resultado']
        if r['resultado']=='cumple':r['resultado']='no evaluable'
        return r
    if id in ('E06','E17'):
        snap=pub(c)
        if id=='E06':
            expected=initial['extra_context']['provider_status']['zepp']
            actual=snap.get('provider_status',{}).get('zepp.wellness',{})
            ok=actual.get('status')==expected.get('status') and actual.get('state')=='provider_error'
        else:
            expected=initial['extra_context']['wattwise_live']['status']
            actual=snap.get('provider_status',{}).get('wattwise',{})
            ok=actual.get('status')==expected and actual.get('state')=='provider_error'
        return result(ok,{'snapshot':snap,'expected_status':expected,'actual_status':actual},'Se exige el estado explícito, no una mención del nombre del proveedor; no se evalúa aquí lenguaje natural.')
    if id=='E11':
        main,store=store_setup();plan={'start_date':'2026-10-03','end_date':'2026-10-03','sessions':[initial['plan']]}
        before=store.save_training_plan(plan,'audit');states=[before]
        with patch.object(main,'load_sync',return_value={'payload':{}}),patch.object(main,'load_profile',return_value={}),patch.object(main,'load_checkins',return_value=[]),patch.object(main,'build_week_plan',return_value=plan):
            for _ in range(2):main.route_message('/plan','audit','audit');states.append(store.load_active_training_plan('audit'))
        states=copy.deepcopy(states)
        signatures=[{k:p.get(k) for k in ('id','revision','sessions')} for p in states]
        return result(all(s==signatures[0] for s in signatures),signatures,'Generador sustituido por plan fijo; se ejecutan enrutador y persistencia reales en ficheros.')
    if id=='E12':
        variants=[]
        for persistent in (False,True):
            calls=[]
            def fake(messages,**kwargs):
                ctx=json.loads(messages[1]['content'])['context'];raw={'schema_version':'1','context_snapshot_id':ctx['context_snapshot_id'],'response_type':'single_session','decisions':[{'action':'rest','intensity':'rest','date':'2026-10-03','evidence_refs':['activity:synthetic-g1']}],'conclusions':[],'evidence_refs':[]}
                if persistent or not calls:raw['answer']='Haz una sesión intensa de carrera hoy.'
                calls.append(raw);return {'message':{'content':json.dumps(raw)},'done_reason':'stop'}
            try:
                wire=generate_validated('hoy',initial,generate=fake,now=NOW)
                outcome={'answer':wire.answer,'calls':len(calls),'rejected':False}
            except CoachValidationError as e:outcome={'rejected':True,'codes':[str(i.code) for i in e.issues],'calls':len(calls)}
            variants.append(outcome)
        return {'resultado':'no evaluable','observado':variants,'motivo':'Contrato actual prohíbe answer; prueba rechazo estructural, no detección semántica. No se invoca worker/fallback exterior.','subcomprobacion':'Reparación acotada y rechazo del campo extra verificables.'}
    if id=='E14':
        main,store=store_setup();paths={}
        async def voice():
            class Request:
                async def json(self):return {'message':{'from':{'id':'audit'},'chat':{'id':'audit'},'voice':{'file_id':'synthetic-voice'}}}
            await main.telegram_webhook(Request())
        with patch.object(main,'load_sync',return_value={'payload':{}}),patch.object(main,'load_profile',return_value={}),patch.object(main,'load_checkins',return_value=[]),patch.object(main,'load_wattwise',return_value={}),patch.object(main,'create_ai_job',return_value={'id':'synthetic-job'}) as queue,patch.object(main,'send_telegram_message',new_callable=AsyncMock),patch.object(main,'format_feedback',return_value='direct feedback'):
            for label,text in [('texto',c['pregunta']),('coach','/coach '+c['pregunta']),('alias','/feedback')]:
                queue.reset_mock();main.route_message(text,'audit','audit');paths[label]={'queued':queue.called,'kwargs':queue.call_args.kwargs if queue.called else None}
            queue.reset_mock();asyncio.run(voice());paths['voz']={'queued':queue.called,'kwargs':queue.call_args.kwargs if queue.called else None}
        r=result(all(v['queued'] for v in paths.values()),paths,'Se prueba despacho; transcripción y equivalencia de contexto posterior no evaluadas: /feedback ya diverge antes.')
        if r['resultado']=='cumple':r['resultado']='no evaluable'
        return r
    if id in ('E15a','E15b'):
        _,store=store_setup(); explicit=initial['explicit'];session=initial['plan'];day=session['date']
        plan=store.save_training_plan({'start_date':day,'end_date':day,'sessions':[session]},'audit')
        job=store.create_ai_job('audit','/ajustar mañana' if explicit else '¿Cómo estoy recuperando?')
        store.prepare_proposal_context(job,{'training_plan'})
        raw={'response_type':'analysis','answer':'Propongo reducir duración; el plan sigue vigente.','change_proposal':{'reason':'Solicitud de ajuste','confidence':.8,'evidence':[],'changes':[{'operation':'ADJUST_DURATION','session_id':plan['sessions'][0]['id'],'proposed_values':{'duration_min':30,'duration_max':40},'reason':'Reducir carga'}]}}
        before=store.TRAINING_PLAN_STATE_FILE.read_bytes();pfile=store.DATA_DIR/'pending_changes.json';proposals_before=pfile.read_bytes() if pfile.exists() else None
        try:
            completed=store.complete_ai_job(job['id'],structured_output=raw,output_source='ollama',answer=raw['answer']);obs={'pending_status':completed.get('pending_change',{}).get('status')}
        except ValueError as e:obs={'rejected':type(e).__name__,'reason':str(e)}
        obs['plan_unchanged']=before==store.TRAINING_PLAN_STATE_FILE.read_bytes()
        obs['proposals_unchanged']=proposals_before==(pfile.read_bytes() if pfile.exists() else None)
        if not explicit:
            # Test normal informational completion separately from a malicious proposal.
            informational={k:v for k,v in raw.items() if k!='change_proposal'}
            saved=store.complete_ai_job(job['id'],structured_output=informational,output_source='ollama',answer=raw['answer'])
            obs['informational_completed']=saved['status']=='completed' and saved.get('answer')==raw['answer']
            obs['plan_unchanged_after_information']=before==store.TRAINING_PLAN_STATE_FILE.read_bytes()
            obs['no_proposal_after_information']=proposals_before==(pfile.read_bytes() if pfile.exists() else None)
        ok=obs['plan_unchanged'] and (obs.get('pending_status')=='PENDING' if explicit else obs.get('reason')=='Change proposal not authorized' and obs['proposals_unchanged'] and obs['informational_completed'] and obs['plan_unchanged_after_information'] and obs['no_proposal_after_information'])
        return result(ok,obs,'Persistencia de ficheros; PostgreSQL no evaluado.')
    if id=='E16':
        from garmin_sync.strava_activity_provider import _normalize_record
        rows=[_normalize_record({'id':str(i+1),'start_date':stamp,'elapsed_time':1200,'distance':4000,'sport_type':'Run'},ZoneInfo('Europe/Madrid')) for i,stamp in enumerate(initial['timestamps'])]
        merged=merge_activities([],[],rows)
        r=result([r['date'] for r in rows]==['2026-10-04','2026-10-25','2026-10-25'] and len(merged)==3,{'normalized':rows,'merged_count':len(merged)},'Normalizador Strava y deduplicación; sueño Zepp no evaluado por este caso. Ver pruebas_ampliadas.py.')
        r['subcomprobacion']=r['resultado']
        if r['resultado']=='cumple':r['resultado']='no evaluable'
        return r
    raise ValueError('No deterministic implementation for '+id)

def live_case(c,rep):
    import httpx
    from garmin_sync import ai_worker as worker
    # Call the real generator to avoid drifting from its options and plan budget.
    worker.OLLAMA_URL='http://127.0.0.1:11434'
    worker.OLLAMA_MODEL='garmin-coach:9b'
    budget=worker.OLLAMA_PLAN_NUM_PREDICT if worker._is_plan_question(c['pregunta']) else worker.OLLAMA_NUM_PREDICT
    calls=[];events=io.StringIO()
    def generate(messages,**kwargs):
        def local_post(url,**request):
            assert url=='http://127.0.0.1:11434/api/chat'
            call={'request':request['json']};calls.append(call)
            with httpx.Client(timeout=request['timeout'],trust_env=False) as client:
                r=client.post(url,json=request['json'])
            r.raise_for_status();call['response']=r.json()
            return r
        with patch.object(worker.httpx,'post',side_effect=local_post):
            return worker.ollama_generate(messages,**kwargs)
    started=time.monotonic()
    try:
        with redirect_stdout(events):wire=generate_validated(c['pregunta'],c['estado_inicial'],generate=generate,now=NOW,num_predict=budget,timeout_seconds=worker.OLLAMA_TIMEOUT_SECONDS)
        record={'wire':wire.model_dump(mode='json'),'resultado':'pendiente de revisión manual'}
    except Exception as e:
        # Only a validated contract failure is a product result. Transport,
        # evaluator and isolation errors remain no evaluable.
        product_error=isinstance(e,CoachValidationError)
        record={'resultado':'incumple' if product_error else 'no evaluable','error_type':type(e).__name__,'validation_codes':[str(i.code) for i in e.issues] if product_error else [],'motivo':'No se produjo salida válida en el pipeline; fallback exterior del worker no ejecutado.'}
    record.update(id=c['id'],repetition=rep,fixture_sha256=hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest(),seconds=round(time.monotonic()-started,3),calls=calls,repairs=max(0,len(calls)-1),fallbacks=None,events=events.getvalue(),fixed_now=NOW.isoformat(),num_predict=budget,timeout_seconds=worker.OLLAMA_TIMEOUT_SECONDS)
    write(f"{c['id']}_ollama_{rep}.json",record)
    print(json.dumps({'id':c['id'],'rep':rep,'seconds':record['seconds'],'result':record['resultado']}),flush=True)

def main():
    test_isolation()
    for path in sorted((OUT/'casos').glob('E*.json')):
        c=json.loads(path.read_text())
        if ONLY and c['id']!=ONLY:continue
        if LIVE:
            if c['modo_modelo']=='Ollama real':
                for rep in range(1,4):live_case(c,rep)
        elif c['modo_modelo']!='Ollama real':
            started=time.monotonic();events=io.StringIO()
            try:
                with redirect_stdout(events):r=deterministic(c)
            except Exception as e:
                import traceback
                r={'resultado':'no evaluable','error_evaluador':type(e).__name__,'traceback':traceback.format_exc()}
            r.update(id=c['id'],seconds=round(time.monotonic()-started,3),events=events.getvalue(),fixture_sha256=hashlib.sha256(json.dumps(c,sort_keys=True).encode()).hexdigest())
            write(c['id']+'_determinista.json',r);print(c['id'],r['resultado'],flush=True)
    if not LIVE:
        from garmin_sync import ai_worker
        ai_worker.datetime=FrozenDatetime
        c=json.loads((OUT/'casos/E01.json').read_text());e=c['estado_inicial']['extra_context']
        upstream={'sync':{'received_at':NOW.isoformat(),'payload':{'generated_at':NOW.isoformat(),'summary':{'activities':e['recent_activities']},'wellness':e['wellness']}},'training_plan':e['training_plan']}
        compact=ai_worker.compact_context(upstream);snapshot=build_snapshot(c['pregunta'],compact,now=NOW)
        write('E01_traza_sintetica.json',{'entrada_al_worker':upstream,'compact':compact,'snapshot':snapshot.public_context(),'note':'No es reproducción de un trabajo histórico: entrada sintética y funciones actuales.'})
    write('guardia_'+('ollama' if LIVE else 'determinista')+'.json',{'blocked_events':BLOCKED,'expected_self_checks':3,'temporary_root':str(TMP)})
if __name__=='__main__':main()
