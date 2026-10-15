import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'scripts'))
import export_overtake_views


class OvertakeUiExportTests(unittest.TestCase):
    @unittest.skipUnless((ROOT / 'data/openf1-pooled/2025/9963/derived/pooled_complete.json').exists(),
                         'requires the local Canadian 2025 session fixture')
    def test_piastri_antonelli_pit_pass_is_not_exported(self):
        """Canada 2025: raw 81->12 is a pit pass, not a model success."""
        session = ROOT / 'data/openf1-pooled/2025/9963'
        metadata = {'meeting_key': 1263, 'session_name': 'Race'}
        events = export_overtake_views.event_rows(session, metadata, 2025)
        self.assertFalse(any(event['overtaking_driver_number'] == 81
                             and event['overtaken_driver_number'] == 12 for event in events))


if __name__ == '__main__':
    unittest.main()
