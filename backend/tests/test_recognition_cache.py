import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from app.api import score_routes as api
from app.api.score_routes import run_recognition
from app.models.score import RecognitionConfig, RecognitionResult, Score, TabBeat, TabMeasure, TabNote
from app.services.local_tab_reader import UnsupportedTabImage
from app.services.recognition_cache import cache_key, load_result, store_result
from app.services.score_exporter import validate_score
from app.services.tab_recognizer import recognize_row


class RecognitionCacheTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.directory = Path(temporary.name)
        self.image = self.directory / 'row.png'
        self.image.write_bytes(b'unchanged image')
        self.cache = self.directory / 'cache'
        self.row = {'id': 'row.png', 'lines': [20, 40, 60, 80], 'bars': [10, 200],
                    'start_number': 1, 'previous_notes': []}
        self.tuning = [43, 38, 33, 28]
        self.config = RecognitionConfig()
        signature = patch('app.services.recognition_cache.reader_signature', return_value='reader-v1')
        self.signature = signature.start()
        self.addCleanup(signature.stop)
        self.reader = Mock(side_effect=self.generated)
        local = patch('app.services.tab_recognizer.read_local_tab', self.reader)
        local.start()
        self.addCleanup(local.stop)

    def generated(self, _path, row, _tuning):
        return RecognitionResult(measures=[TabMeasure(number=row['start_number'], source=row['id'],
            beats=[TabBeat(duration=1, notes=[TabNote(string=4, fret=self.reader.call_count)])])])

    def recognize(self, *, row=None, tuning=None, force=False, hit=None):
        return recognize_row(self.image, row or self.row, self.config.model_copy(update={'force': force}),
                             tuning or self.tuning, cache_directory=self.cache, on_cache_hit=hit)

    def test_unchanged_input_reuses_persistent_result(self):
        original = self.recognize()
        hit = Mock()
        repeated = self.recognize(hit=hit)
        self.assertEqual(original, repeated)
        self.assertEqual(self.reader.call_count, 1)
        hit.assert_called_once_with()
        repeated.measures[0].beats[0].notes[0].fret = 20
        self.assertEqual(self.recognize(), original)

    def test_changed_image_context_tuning_and_reader_invalidate_cache(self):
        self.recognize()
        variants = [
            {'row': {**self.row, 'start_number': 2}},
            {'row': {**self.row, 'previous_notes': [{'string': 4, 'fret': 9, 'kind': 'normal'}]}},
            {'row': {**self.row, 'lines': [21, 41, 61, 81]}},
            {'row': {**self.row, 'bars': [10, 100, 200]}},
            {'tuning': [43, 38, 33, 26]},
        ]
        for index, change in enumerate(variants, start=2):
            with self.subTest(change=change):
                self.recognize(**change)
                self.assertEqual(self.reader.call_count, index)
        self.image.write_bytes(b'changed image')
        self.recognize()
        self.assertEqual(self.reader.call_count, 7)
        self.signature.return_value = 'reader-v2'
        self.recognize()
        self.assertEqual(self.reader.call_count, 8)

    def test_force_rereads_and_updates_cache(self):
        first = self.recognize()
        forced = self.recognize(force=True)
        self.assertNotEqual(first, forced)
        self.assertEqual(self.recognize(), forced)
        self.assertEqual(self.reader.call_count, 2)

    def test_corrupt_or_tampered_cache_is_recomputed(self):
        self.recognize()
        path = next(self.cache.glob('*.json'))
        path.write_text('{broken', encoding='utf-8')
        self.recognize()
        self.assertEqual(self.reader.call_count, 2)
        value = json.loads(path.read_text(encoding='utf-8'))
        value['result']['measures'][0]['beats'][0]['notes'][0]['fret'] = 30
        path.write_text(json.dumps(value), encoding='utf-8')
        self.recognize()
        self.assertEqual(self.reader.call_count, 3)

    def test_cache_storage_failure_does_not_fail_recognition(self):
        self.cache.write_text('not a directory', encoding='utf-8')
        self.recognize()
        self.recognize()
        self.assertEqual(self.reader.call_count, 2)

    def test_machine_cache_never_marks_human_review(self):
        result = self.recognize()
        result.measures[0].reviewed = True
        key = cache_key(self.image, self.row, self.tuning)
        store_result(self.cache, key, result)
        self.assertTrue(result.measures[0].reviewed)
        self.assertFalse(load_result(self.cache, key).measures[0].reviewed)

    def test_unknown_beats_still_block_export_after_cache_hit(self):
        unknown = self.generated(self.image, self.row, self.tuning)
        unknown.measures[0].beats[0].unresolved = ['pitch']
        self.reader.side_effect = None
        self.reader.return_value = unknown
        self.recognize()
        cached = self.recognize()
        score = Score(settings_confirmed=True, measures=cached.measures)
        self.assertTrue(any(item['severity'] == 'error' for item in validate_score(score, require_review=False)))
        self.assertEqual(cached.measures[0].beats[0].unresolved, ['pitch'])

    def test_unsupported_and_vision_paths_do_not_use_local_cache(self):
        self.reader.side_effect = UnsupportedTabImage('unsupported')
        for _ in range(2):
            with self.assertRaises(ValueError):
                self.recognize()
        self.assertFalse(self.cache.exists())
        self.assertEqual(self.reader.call_count, 2)
        with self.assertRaises(ValueError):
            recognize_row(self.image, self.row, RecognitionConfig(strategy='vision'),
                          self.tuning, cache_directory=self.cache)
        self.assertEqual(self.reader.call_count, 2)

    def test_force_does_not_overwrite_partly_reviewed_row(self):
        score = Score(settings_confirmed=True, measures=[TabMeasure(number=1, source='row.png',
            reviewed=True, beats=[TabBeat(duration=1, notes=[TabNote(string=4, fret=12)])]),
            TabMeasure(number=2, source='row.png', reviewed=False,
                       beats=[TabBeat(duration=1, notes=[TabNote(string=4, fret=13)])])])
        before = score.model_dump()
        run_recognition('test', self.directory, RecognitionConfig(force=True),
                        {'rows': [self.row]}, score)
        self.assertEqual(score.model_dump(), before)
        self.reader.assert_not_called()

    def test_progress_file_retries_a_transient_windows_lock(self):
        destination = self.directory / 'task.json'
        original = Path.replace
        calls = 0

        def replace(path, target):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise PermissionError('Windows reader holds the old file')
            return original(path, target)

        with patch.object(Path, 'replace', replace), patch.object(api.time, 'sleep'):
            api.write_json(destination, {'status': 'review'})
        self.assertEqual(api.read_json(destination), {'status': 'review'})
        self.assertEqual(calls, 3)
        self.assertFalse(destination.with_suffix('.tmp').exists())

    def test_failed_final_checkpoint_still_releases_busy_project(self):
        project = 'failed-checkpoint-test'
        api.acquire(project)
        self.addCleanup(api.release, project)
        with patch.object(api, 'write_json', side_effect=PermissionError('unwritable')):
            with self.assertRaises(PermissionError):
                run_recognition(project, self.directory, RecognitionConfig(),
                                {'rows': [self.row]}, Score())
        self.assertNotIn(project, api._busy)


if __name__ == '__main__':
    unittest.main()
