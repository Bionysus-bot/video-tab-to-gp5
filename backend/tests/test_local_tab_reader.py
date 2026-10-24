import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from app.models.score import Score
from app.services.image_io import imread, imwrite
from app.services.local_tab_reader import read_local_tab, slide_has_curve, staff_geometry
from app.services.score_exporter import validate_score


def staff():
    image = np.full((290, 1000, 3), 245, dtype=np.uint8)
    lines = [80, 105, 130, 155]
    for y in lines:
        cv2.line(image, (60, y), (940, y), (175, 175, 175), 1)
    for x in [60, 500, 940]:
        cv2.line(image, (x, 80), (x, 155), (180, 180, 180), 1)
    # Page borders span the entire image, but must not become barlines.
    cv2.line(image, (15, 0), (15, 289), (0, 0, 0), 2)
    cv2.line(image, (980, 0), (980, 289), (0, 0, 0), 2)
    return image, lines


class LocalReaderTests(unittest.TestCase):
    def test_legato_curve_result_can_be_saved_as_json(self):
        import json
        gray = np.full((70, 250), 255, dtype=np.uint8)
        curve = np.array([[40, 28], [85, 36], [150, 36], [200, 28]], dtype=np.int32)
        cv2.polylines(gray, [curve], False, 0, 1)
        value = slide_has_curve(gray, 20, 40, 200, 20)
        self.assertIs(type(value), bool)
        self.assertTrue(value)
        self.assertEqual(json.loads(json.dumps({'legato_slide': value})), {'legato_slide': True})

    def test_page_borders_and_rest_strokes_are_not_barlines(self):
        image, lines = staff()
        cv2.line(image, (300, 105), (295, 135), (30, 30, 30), 2)
        result = staff_geometry(image, lines)
        self.assertAlmostEqual(result['left'], 60, delta=4)
        self.assertAlmostEqual(result['right'], 940, delta=4)
        self.assertEqual(len(result['bars']), 3)
        self.assertAlmostEqual(result['bars'][1], 500, delta=4)

    def test_whole_measure_rests_are_not_eighth_rests(self):
        image, lines = staff()
        for x in [260, 720]:
            cv2.rectangle(image, (x-10, 98), (x+10, 106), (20, 20, 20), -1)
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'rests.png'
            imwrite(path, image)
            result = read_local_tab(path, dict(id='row.png', lines=lines, start_number=3), [43,38,33,28])
        self.assertEqual([m.number for m in result.measures], [3,4])
        self.assertEqual([m.beats[0].duration for m in result.measures], [1,1])
        self.assertTrue(all(not m.beats[0].notes for m in result.measures))

    def test_unknown_fret_is_not_silently_replaced_with_a_rest(self):
        image, lines = staff()
        cv2.rectangle(image, (144, 144), (156, 166), (30,30,30), -1)
        cv2.line(image, (150, 179), (150, 216), (50,50,50), 2)
        with tempfile.TemporaryDirectory() as directory, patch('app.services.local_tab_reader.read_text', return_value=[('',0),('',0)]):
            path = Path(directory) / 'unknown.png'
            imwrite(path, image)
            result = read_local_tab(path, dict(id='row.png', lines=lines), [43,38,33,28])
        self.assertIn('pitch', result.measures[0].beats[0].unresolved)
        score = Score(settings_confirmed=True, measures=result.measures)
        for measure in score.measures:
            measure.reviewed = True
        self.assertTrue(any('未识别' in issue['message'] for issue in validate_score(score)))

    def test_faint_seven_is_not_replaced_with_thresholded_one(self):
        image, lines = staff()
        cv2.putText(image, '7', (142, 165), cv2.FONT_HERSHEY_SIMPLEX, .8, (40,40,40), 2)
        cv2.line(image, (150, 179), (150, 216), (50,50,50), 2)
        with tempfile.TemporaryDirectory() as directory, patch('app.services.local_tab_reader.read_text', return_value=[('7',.6),('1',.95)]):
            path = Path(directory) / 'seven.png'
            imwrite(path, image)
            result = read_local_tab(path, dict(id='row.png', lines=lines), [43,38,33,28])
        note = result.measures[0].beats[0].notes[0]
        self.assertEqual((note.string, note.fret), (4,7))


if __name__ == '__main__':
    unittest.main()
