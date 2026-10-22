import tempfile
import unittest
import json
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.models.score import RecognitionConfig, RecognitionResult, TabBeat, TabMeasure
from app.services.image_io import imwrite
from app.services.model_repair import repair_combined
from tests.test_combined_tab import combined_image, sample_result
from app.api.score_routes import router
from app.storage import manager as storage


class ModelRepairTests(unittest.TestCase):
    def run_repair(self, original, answers, **kwargs):
        image, row, _ = combined_image([8] * 8)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'row.png'
            imwrite(path, image)
            model = Mock(side_effect=answers)
            result = repair_combined(path, row, RecognitionConfig(model='test'),
                                     [43,38,33,28], [original], model, **kwargs)
        return result, model

    def test_valid_reviewed_measure_is_untouched_without_model_call(self):
        original = sample_result().measures[0]
        original.reviewed = True
        result, model = self.run_repair(original, [])
        model.assert_not_called()
        self.assertEqual(result.measures[0], original)

    def test_invalid_reviewed_measure_can_be_repaired_but_never_auto_reviewed(self):
        original = TabMeasure(number=1, reviewed=True, beats=[TabBeat(duration=4, unresolved=['pitch'])])
        result, model = self.run_repair(original, [sample_result()])
        self.assertFalse(result.measures[0].reviewed)
        self.assertTrue(original.reviewed)
        self.assertEqual(result.measures[0].beats[0].duration, 1)
        self.assertEqual(model.call_args.args[1]['repair_candidate']['beats'][0]['duration'], 4)

    def test_two_invalid_answers_keep_original_including_unresolved_and_review(self):
        original = TabMeasure(number=1, reviewed=True, beats=[TabBeat(duration=4, unresolved=['pitch'])])
        bad = RecognitionResult(measures=[original])
        result, model = self.run_repair(original, [bad, bad])
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result.measures[0], original)

    def test_retry_receives_validation_errors_and_can_recover(self):
        original = TabMeasure(number=1, beats=[TabBeat(duration=4, unresolved=['pitch'])])
        result, model = self.run_repair(original, [RecognitionResult(measures=[]), sample_result()])
        self.assertEqual(model.call_count, 2)
        self.assertEqual(result.measures[0].beats[0].duration, 1)

    def test_number_change_is_not_accepted_even_if_notes_fit(self):
        original = TabMeasure(number=1, beats=[TabBeat(duration=4, unresolved=['pitch'])])
        bad = sample_result()
        bad.measures[0].number = 99
        result, model = self.run_repair(original, [bad, bad])
        self.assertEqual(result.measures[0], original)

    def test_repair_request_backs_up_reviewed_data_before_worker_starts(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(storage, 'STORAGE_ROOT', Path(temporary)):
            pid = storage.create_project()
            directory = storage.output_path(pid, 'score')
            directory.mkdir(exist_ok=True)
            original = sample_result().model_dump()['measures'][0]
            original['reviewed'] = True
            saved = dict(measures=[original])
            (directory/'score.json').write_text(json.dumps(saved), encoding='utf-8')
            (directory/'manifest.json').write_text(json.dumps(dict(rows=[dict(id='row.png')])), encoding='utf-8')
            app = FastAPI(); app.include_router(router, prefix='/api')
            from app.api.score_routes import release
            try:
                with patch('app.api.score_routes.threading.Thread') as worker:
                    response = TestClient(app).post(f'/api/projects/{pid}/score/recognize',
                                                   json=dict(strategy='repair', model='test'))
                    self.assertEqual(response.status_code, 200, response.text)
                    backups = list((directory/'backups').glob('model-repair-*/score.json'))
                    self.assertEqual(len(backups), 1)
                    self.assertEqual(json.loads(backups[0].read_text(encoding='utf-8'))['measures'][0], original)
                    worker.return_value.start.assert_called_once()
                    self.assertEqual(json.loads((directory/'score.json').read_text(encoding='utf-8')), saved)
            finally:
                release(pid)


if __name__ == '__main__':
    unittest.main()
