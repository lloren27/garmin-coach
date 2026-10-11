import json
from pathlib import Path
import tempfile
import unittest

import experiment as ex
import experiment_review as review


class ReviewTests(unittest.TestCase):
    def setup_run(self, root):
        self.run = root / 'run'; self.run.mkdir()
        self.blind = root / 'blind'; self.key = root / 'private' / 'key.json'
        self.cases = ex.prepare_cases()
        self.rows = [{'case_id':c['id'], 'baseline':{'status':'valid','answer':'Texto A'},
                     'model':{'status':'valid','answer':'Texto B','latency_seconds':2.0}} for c in self.cases]
        ex.write_json(self.run / 'manifest.json', {'status':'generated','protocol_seal':ex.PROTOCOL_SEAL,
            'case_ids':[c['id'] for c in self.cases]})
        ex.write_json(self.run / 'results.json', self.rows)
        review.export_blind(self.run, self.blind, self.key)
        mapping = json.loads(self.key.read_text())['mapping']
        self.ratings = [{'opaque_id':i, 'F':2,'P':2,'U':2 if m['source']=='model' else 1,'R':2,
            'expected_checks_pass':True,'critical_errors':[], 'justification':'Cumple hechos, foco y límites.'}
            for i,m in mapping.items()]
        self.ratings_path = root / 'ratings.json'
        ex.write_json(self.ratings_path, self.ratings)

    def test_blind_package_and_sealed_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_run(Path(tmp))
            package = json.loads((self.blind / 'review.json').read_text())
            self.assertEqual(len(package['outputs']), 30)
            self.assertTrue(all(set(r) == {'opaque_id','case_id','answer'} for r in package['outputs']))
            self.assertNotIn('latency_seconds', (self.blind / 'review.json').read_text())
            self.assertEqual(len({r['opaque_id'] for r in package['outputs']}), 30)
            with self.assertRaises(ValueError):
                review.evaluate_ratings(self.run, self.ratings_path, self.key)
            review.seal_ratings(self.blind, self.ratings_path)
            result = review.evaluate_ratings(self.run, self.ratings_path, self.key)
            self.assertEqual(result['decision'], 'model_wins')

    def test_tie_and_guard_failure_keep_deterministic(self):
        for failure in ('tie','guard'):
            with self.subTest(failure=failure), tempfile.TemporaryDirectory() as tmp:
                self.setup_run(Path(tmp))
                mapping = json.loads(self.key.read_text())['mapping']
                rating = next(r for r in self.ratings if mapping[r['opaque_id']] ==
                              {'case_id':'E01-pace' if failure=='tie' else 'E10-mixto','source':'model'})
                if failure == 'tie': rating['U'] = 1
                else: rating['expected_checks_pass'] = False
                ex.write_json(self.ratings_path, self.ratings)
                review.seal_ratings(self.blind, self.ratings_path)
                self.assertEqual(review.evaluate_ratings(self.run,self.ratings_path,self.key)['decision'], 'deterministic')

    def test_missing_duplicate_out_of_range_and_blank_ratings_rejected(self):
        for mutation in ('missing','duplicate','range','blank'):
            with self.subTest(mutation=mutation), tempfile.TemporaryDirectory() as tmp:
                self.setup_run(Path(tmp))
                if mutation=='missing': self.ratings.pop()
                if mutation=='duplicate': self.ratings[-1] = self.ratings[0]
                if mutation=='range': self.ratings[0]['F'] = 3
                if mutation=='blank': self.ratings[0]['justification'] = ' '
                ex.write_json(self.ratings_path,self.ratings)
                with self.assertRaises(ValueError): review.seal_ratings(self.blind,self.ratings_path)

    def test_changed_scores_or_run_after_seal_rejected(self):
        for target in ('scores','run'):
            with self.subTest(target=target), tempfile.TemporaryDirectory() as tmp:
                self.setup_run(Path(tmp))
                review.seal_ratings(self.blind,self.ratings_path)
                p = self.ratings_path if target=='scores' else self.run/'results.json'
                p.write_text(p.read_text()+' ')
                with self.assertRaises(ValueError): review.evaluate_ratings(self.run,self.ratings_path,self.key)

    def test_key_cannot_be_in_blind_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            self.setup_run(Path(tmp))
            with self.assertRaises(ValueError): review.export_blind(self.run,Path(tmp)/'other',Path(tmp)/'other'/'key.json')

    def test_transport_never_becomes_model_win(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp); self.setup_run(root)
            self.rows[0]['model'].update(status='no_evaluado',answer=None)
            ex.write_json(self.run/'results.json',self.rows)
            second=root/'second'; key=root/'private2'/'key.json'
            review.export_blind(self.run,second,key)
            mapping=json.loads(key.read_text())['mapping']
            ratings=[{**self.ratings[0],'opaque_id':i,'U':2 if m['source']=='model' else 1} for i,m in mapping.items()]
            path=root/'newratings.json';ex.write_json(path,ratings)
            review.seal_ratings(second,path)
            self.assertEqual(review.evaluate_ratings(self.run,path,key)['decision'],'pending')

if __name__ == '__main__': unittest.main()
