"""Adapters can read plans and insert proposals, never write plan rows."""
import json
from .file_state import atomic_json


class FileProposalRepository:
    def __init__(self, directory, plan_file):
        self.path = directory / 'pending_changes.json'
        self.plan_file = plan_file

    def _rows(self):
        return json.loads(self.path.read_text()) if self.path.exists() else []

    def find(self, job_id):
        return next((r for r in self._rows() if r['source_job_id'] == job_id), None)

    def read_plan(self, plan_id):
        if not self.plan_file.exists():
            return None
        state = json.loads(self.plan_file.read_text())
        plan = next((p for p in state['plans'] if p['id'] == plan_id), None)
        if plan:
            plan['revision'] = plan.get('revision', 1)
            plan['sessions'] = [s for s in state['sessions'] if s['training_plan_id'] == plan_id]
        return plan

    def insert(self, document):
        # Caller holds the common state lock for check/insert/job completion.
        rows = self._rows()
        rows.append(document)
        atomic_json(self.path, rows)
        return document


class PostgresProposalRepository:
    def __init__(self, conn):
        self.conn = conn

    def find(self, job_id):
        row = self.conn.execute('select document from pending_changes where source_job_id = %s',
                                (job_id,)).fetchone()
        return row[0] if row else None

    def read_plan(self, plan_id):
        row = self.conn.execute('select to_jsonb(p) from training_plans p where id = %s for share',
                                (plan_id,)).fetchone()
        if not row:
            return None
        plan = row[0]
        plan = {**plan.pop('document', {}), **plan}
        rows = self.conn.execute('select to_jsonb(s) from planned_sessions s where training_plan_id = %s order by session_date, sequence for share',
                                 (plan_id,)).fetchall()
        plan['sessions'] = []
        for (session,) in rows:
            session = {**session.pop('document', {}), **session}
            session['date'] = session.pop('session_date')
            plan['sessions'].append(session)
        return plan

    def insert(self, document):
        from psycopg.types.json import Jsonb
        self.conn.execute('''insert into pending_changes
            (id, owner_id, training_plan_id, base_plan_revision, source_job_id, status, document)
            values (%s, %s, %s, %s, %s, %s, %s)''',
            (document['id'], document['owner_id'], document['training_plan_id'],
             document['base_plan_revision'], document['source_job_id'], document['status'], Jsonb(document)))
        return document
