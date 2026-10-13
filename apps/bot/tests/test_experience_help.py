import subprocess
import sys
import unittest
from unittest.mock import patch
from app import main
from app import experience

class HelpTests(unittest.TestCase):
    def test_alias_help_tracks_switch_mode(self):
        off = experience.format_help(detailed=True)
        on = experience.format_help(detailed=True, alias_routing_enabled=True)
        self.assertIn('/hoy — Vista deportiva local del día', off)
        self.assertIn('/hoy — Análisis del entrenamiento de hoy (coach V3)', on)
        self.assertIn('/feedback — Análisis del último día de entrenamiento (coach V3)', on)

    def test_static_menus_do_not_read_or_write(self):
        with patch.object(main, 'load_sync', side_effect=AssertionError('read')), patch.object(main, 'load_profile', side_effect=AssertionError('read')), patch.object(main, 'create_ai_job', side_effect=AssertionError('queue')):
            for cmd in ('/help', '/start', '/HELP@Bot', '/help comandos', '/registro', '/registro fuerza', '/registro molestias', '/registro perfil', '/registro pruebas', '/registro desconocido'):
                self.assertTrue(main.route_message(cmd, 'u', 'c'))
            brief = main.route_message('/help')
            for cmd in ('/coach', '/plan', '/sync', '/estado', '/registro', '/help'):
                self.assertIn(cmd, brief)
            self.assertNotIn('/fatiga', brief)
            self.assertIn('Uso:', main.route_message('/help nope'))
            self.assertIn('/fuerza add', main.route_message('/registro fuerza'))

    def test_help_inventory_is_routable(self):
        # Real router, mocked I/O; commands may request writes but never perform them here.
        names = [n for n in vars(main) if n.startswith(('load_', 'save_', 'create_', 'find_', 'mark_', 'update_', 'discard_'))]
        for name in names:
            self.enterContext(patch.object(main, name, return_value=None))
        self.enterContext(patch.object(main, 'load_checkins', return_value=[]))
        self.enterContext(patch.object(main, 'load_sync_history', return_value=[]))
        self.enterContext(patch.object(main, 'load_lab_tests', return_value=[]))
        self.enterContext(patch.object(main, 'load_strength_state', return_value={}))
        self.enterContext(patch.object(main, 'save_sync_request', return_value={}))
        self.enterContext(patch.object(main, 'create_ai_job', return_value={}))
        self.enterContext(patch.object(main, 'load_operational_documents', return_value=(None,None)))
        unknown = main.route_message('/comando_inexistente', 'u', 'c')
        for command, description in experience.HELP_COMMANDS:
            with self.subTest(command=command):
                self.assertTrue(description)
                self.assertNotEqual(main.route_message(command, 'u', 'c'), unknown)
        self.assertIn('/plan nuevo', main.route_message('/plan', 'u', 'c'))

    def test_no_import_cycle(self):
        subprocess.run([sys.executable, '-c', 'import app.experience; import app.coach; import app.main'], check=True)
