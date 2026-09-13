import tempfile
import unittest
from pathlib import Path

from backend.services_nav_diagnostics import LocalizationDiagnostics


class DiagnosticsTests(unittest.TestCase):
    def test_retry_uses_latest_result_and_keeps_history(self):
        d = LocalizationDiagnostics()
        d.consume('GET Initial guess from /initialpose: 0 0 0')
        d.consume('Global ICP Converged Fail! FitnessScore: 2.8')
        self.assertEqual(d.snapshot()['phase'], 'match_failed')
        self.assertIn('2.8', d.snapshot()['message'])
        d.consume('INIT start...')
        self.assertEqual(d.snapshot()['phase'], 'matching')
        d.consume('Global ICP Converged Succeed! FitnessScore: 0.1')
        self.assertEqual(d.snapshot(ready=True)['phase'], 'ready')
        self.assertTrue(any(e['phase'] == 'match_failed' for e in d.events))

    def test_alias_fallback_cannot_be_overwritten_by_ready(self):
        d = LocalizationDiagnostics()
        d.consume('Global ICP result rejected as an alias match. correction_xyz=3 4 0.8 rotation=1.2 rad; keep the supplied initial pose.')
        d.consume('SCAN body pose TF ready: map -> base_footprint')
        d.consume('Published static graph with 500 markers')
        result = d.snapshot(ready=True)
        self.assertEqual(result['phase'], 'fallback')
        self.assertEqual(result['level'], 'error')
        self.assertIn('5.000 m', result['message'])
        self.assertIn('68.8°', result['message'])
        self.assertIn('不代表地图匹配成功', result['message'])

    def test_new_attempt_excludes_old_success_and_reads_partial_lines_once(self):
        with tempfile.TemporaryDirectory() as root:
            path = Path(root) / 'nav.log'
            path.write_text('Global ICP Converged Succeed!\n')
            d = LocalizationDiagnostics()
            d.begin(path, 'scene-1')
            d.read(path)
            self.assertEqual(d.snapshot(ready=True)['match'], None)
            with path.open('a') as f:
                f.write('Global ICP Converged Fail! FitnessScore: 2')
            d.read(path)
            self.assertEqual(d.phase, 'receiving')
            with path.open('a') as f:
                f.write('\n')
            d.read(path)
            count = len(d.events)
            d.read(path)
            self.assertEqual(len(d.events), count)
            self.assertEqual(d.phase, 'match_failed')
            path.write_text('[Navigation][run:new] launch\n')
            d.read(path)
            self.assertIsNone(d.match)
            self.assertEqual(d.phase, 'starting')

    def test_tf_failure_and_process_failure_are_not_matching_failures(self):
        d = LocalizationDiagnostics()
        d.consume('Global ICP Converged Succeed! FitnessScore: 0.1')
        self.assertIn('TF 未就绪', d.snapshot(health_error='TF 未就绪')['message'])
        d.consume('[global_planner-1] process has died [pid 1, exit code -9, cmd secret]')
        result = d.snapshot(health_error='global_planner 未就绪')
        self.assertEqual(result['phase'], 'process_error')
        self.assertNotIn('secret', result['message'])


if __name__ == '__main__':
    unittest.main()
