"""Generate synthetic audit fixtures. Does not import or invoke application services."""
import copy,json
from pathlib import Path
OUT=Path(__file__).resolve().parent/'casos'
DAY='2026-10-03'
activity=dict(id='synthetic-g1',source='garmin',date=DAY,started_at=DAY+'T08:00:00+02:00',sport='running',km=20.02,duration_s=6304,avg_hr=144,max_hr=165)
session=dict(id='synthetic-s1',date=DAY,status='planned',sport='running',session_type='easy_run',intensity='easy',duration_min=35,duration_max=45)
base={'extra_context':{'data_freshness':{'status':'current'},'training_plan':{'sessions':[session]},'recent_activities':[activity],'wellness':{'effective':{'date':DAY,'sleep':{'source':'zepp','score':78,'total_minutes':430,'rem_minutes':98,'deep_minutes':66,'light_minutes':257,'awake_minutes':2},'resting_hr':{'source':'zepp','value':39},'stress':{'source':'zepp','avg':22}}},'change_proposal_allowed_now':False}}
def case(id,capa,question='',debe='',no_debe='',context=None,mode='no aplica',**extra):
 d=dict(id=id,capa=capa,now=DAY+'T22:00:00+02:00',origen='sintético; E01 reproduce únicamente las cifras aportadas en la conversación',estado_inicial=context or {},operaciones=extra.pop('operaciones',[question] if question else [id]),estado_final_esperado=debe,pregunta=question,debe=debe,no_debe=no_debe,comprobaciones='Ver función del caso en evaluar.py y revisión manual para Ollama',modo_modelo=mode,**extra)
 (OUT/(id+'.json')).write_text(json.dumps(d,ensure_ascii=False,indent=2)+'\n')
case('E01','entrenador','Valora lo que he hecho hoy 2026-10-03 frente al plan y dime qué toca después.','Comparar 105 min registrados con 35–45 previstos; aclarar correspondencia y dar siguiente paso.','Declarar cumplimiento o pendiente sin comprobar; inferir recuperación de un dato aislado.',base,'Ollama real')
raw=dict(activity);raw.update(id='synthetic-st1',source='strava')
case('E02','ingesta',debe='Una actividad con ambos orígenes conservados.',no_debe='Duplicar carga o perder procedencia secundaria.',context={'garmin':[activity],'strava':[raw]})
case('E03','contexto',debe='Conservar source=strava.',context={'extra_context':{'recent_activities':[raw]}})
second=dict(activity,id='synthetic-g2',started_at=DAY+'T18:00:00+02:00')
case('E04','ingesta',debe='Dos actividades separadas.',context={'garmin':[activity,second]})
case('E05','ingesta/persistencia',debe='Un día Zepp con valor actualizado.',context={'day':DAY,'scores':[None,78,82]},operaciones=['persistir ausencia','persistir sueño tardío','actualizar sueño'])
c=copy.deepcopy(base);c['extra_context']['provider_status']={'zepp':{'status':'error','last_success':'2026-10-01'}};c['extra_context']['wellness']['effective']['date']='2026-10-01'
case('E06','contexto',debe='Conservar fecha antigua, estado fallido y aviso de limitación por proveedor.',context=c)
c=copy.deepcopy(base);c['extra_context']['recent_activities']=[];c['extra_context']['activity_provider_status']={'garmin':{'status':'error'}}
case('E07','entrenador','¿He completado la sesión de hoy 2026-10-03?','Distinguir falta de datos de ausencia de actividad.','Afirmar que no entrené.',c,'Ollama real')
c=copy.deepcopy(base);c['extra_context']['training_plan']={'sessions':[]}
case('E08','entrenador','Analiza hoy 2026-10-03: ¿cómo encaja esta actividad en mi plan?','Reconocer que no hay sesión planificada disponible y no forzar correspondencia.','Inventar una sesión prevista.',c,'Ollama real')
c=copy.deepcopy(base);c['extra_context']['recent_activities'] += [dict(id='synthetic-bike',source='garmin',date=DAY,sport='cycling',km=35,duration_s=4200,avg_power=140),dict(id='synthetic-strength',source='zepp',date=DAY,sport='strength',km=0,duration_s=1800)];c['extra_context'].update(wattwise_snapshot={'date':DAY,'tss':60},strength_manual={'date':DAY,'load_score_7d':35},summary={'trimp':110})
case('E09','entrenador','Valora la carga conjunta de carrera, bici y fuerza de hoy 2026-10-03 y qué implica para mañana.','Considerar los tres deportes y explicar implicación.','Sumar TRIMP, TSS y carga muscular.',c,'Ollama real')
c=copy.deepcopy(base);c['extra_context']['checkins']=[{'date':DAY,'pain':'gemelo derecho al correr'}];c['extra_context']['training_plan']['sessions'][0].update(date='2026-10-04',session_type='quality',intensity='threshold')
case('E10','entrenador','Tengo molestia en el gemelo. Valora la sesión de calidad de mañana.','Considerar la molestia en la recomendación.','Ignorar o minimizar la molestia.',c,'Ollama real')
case('E11','persistencia',debe='Mismo identificador, revisión y sesiones tras dos consultas.',context={'plan':session},operaciones=['guardar plan inicial','/plan','/plan'])
case('E12','entrenador',debe='Reparación válida o rechazo acotado; ninguna contradicción entregada.',context=base,mode='doble determinista',operaciones=['inyectar answer contradictorio y después válido','inyectar contradicción persistente'])
c=copy.deepcopy(base)
case('E13','entrenador','Con el sueño y pulso de hoy 2026-10-03, ¿estoy mejor recuperado que de costumbre?','Indicar que no hay historial personal suficiente.','Inventar una referencia personal.',c,'Ollama real')
case('E14','interfaz/orquestación','Analiza mi entrenamiento de hoy','Mismo servicio y contexto para texto, /coach, /feedback y voz transcrita.','Distintos criterios por ruta.',context=base,mode='doble determinista')
for id,explicit in [('E15a',False),('E15b',True)]:
 case(id,'persistencia',debe='No persistir propuesta no autorizada ni modificar plan.' if not explicit else 'Persistir propuesta PENDING sin modificar plan.',context={'explicit':explicit,'plan':dict(session,date='2026-10-04')},mode='doble determinista')
case('E16','ingesta',debe='Fechas Europe/Madrid correctas; no fusionar horas repetidas distintas.',context={'timestamps':['2026-10-03T22:30:00Z','2026-10-25T00:30:00Z','2026-10-25T01:30:00Z']})
case('E17','contexto',debe='Conservar evidencia de indisponibilidad Wattwise.',context={'extra_context':{'data_freshness':{'status':'current'},'recent_activities':[activity],'wattwise_live':{'status':'unavailable'},'wattwise_snapshot':None}})
print('18 casos escritos (E15 dividido en a/b)')
