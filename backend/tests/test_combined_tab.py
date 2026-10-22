import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.score_routes import router
from app.models.score import RecognitionConfig, RecognitionResult, Score, TabBeat, TabMeasure, TabNote
from app.services.combined_local import read_combined_local
from app.services.combined_tab import check_vision_measure, measure_regions, recognize_combined
from app.services.image_io import imread, imwrite
from app.services.score_exporter import validate_score
from app.services.score_images import prepare_images
from app.services.tab_recognizer import recognize_row
from app.storage import manager as storage


def combined_image(durations):
    image = np.full((420, 1000, 3), 245, np.uint8)
    staff = [70, 86, 102, 118, 134]
    strings = [230, 255, 280, 305]
    for y in staff + strings:
        cv2.line(image, (80, y), (940, y), (215, 215, 215), 1)
    for x in (100, 900):
        cv2.line(image, (x, staff[0]), (x, staff[-1]), (30,30,30), 2)
        cv2.line(image, (x, strings[0]), (x, strings[-1]), (30,30,30), 2)
    xs = np.linspace(160, 840, len(durations)).round().astype(int) if durations else []
    for x in xs:
        cv2.ellipse(image, (x, 102), (10, 6), -15, 0, 360, (25,25,25), -1)
        cv2.line(image, (x-8, 102), (x-8, 163), (25,25,25), 2)
        cv2.putText(image, '7', (x-6, 314), cv2.FONT_HERSHEY_SIMPLEX, .7, (80,80,80), 1)
    if durations and all(d >= 8 for d in durations):
        cv2.line(image, (xs[0]-8, 162), (xs[-1]-8, 162), (25,25,25), 5)
        for i in range(len(xs)-1):
            if durations[i] >= 16 and durations[i+1] >= 16:
                cv2.line(image, (xs[i]-8, 149), (xs[i+1]-8, 149), (25,25,25), 5)
    figures = [dict(x=x*1.2-7, y=355, w=14, h=24, x_center=x*1.2,
                    text='7', confidence=.99, string=4, parenthesized=False) for x in xs]
    return image, dict(id='row.png', source='synthetic', source_row=1, layout='standard-tab',
                       lines=strings, notation_lines=staff, bars=[100,900], width=1000, height=420), figures


def sample_result():
    return RecognitionResult(measures=[TabMeasure(number=1, confidence=.99,
        beats=[TabBeat(duration=1, notes=[TabNote(string=4, fret=7)])])])


class CombinedTabTests(unittest.TestCase):
    def read(self, durations):
        image, row, figures = combined_image(durations)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'row.png'; imwrite(path,image)
            with patch('app.services.combined_local._glyphs',return_value=(figures,None,None)), \
                    patch('app.services.combined_local._printed_number',return_value=12):
                return read_combined_local(path,row,[43,38,33,28])

    def test_aligned_eighth_notes_remain_separate_beats(self):
        result=self.read([8]*8)
        measure=result.measures[0]
        self.assertEqual(measure.number,12)
        self.assertEqual([b.duration for b in measure.beats],[8]*8)
        self.assertTrue(all(len(b.notes)==1 and b.notes[0].string==4 for b in measure.beats))
        self.assertFalse(any(b.unresolved for b in measure.beats))

    def test_mixed_beams_preserve_ten_notes_and_exact_durations(self):
        expected=[8,8,16,16,8,8,8,16,16,8]
        result=self.read(expected)
        self.assertEqual([b.duration for b in result.measures[0].beats],expected)
        self.assertFalse(any(b.unresolved for b in result.measures[0].beats))

    def test_filled_quarters_are_not_assumed_to_be_eighths(self):
        result=self.read([4]*4)
        self.assertEqual([b.duration for b in result.measures[0].beats],[4]*4)
        self.assertFalse(any(b.unresolved for b in result.measures[0].beats))

    def test_visible_whole_rest_has_one_whole_duration(self):
        image,row,_=combined_image([])
        cv2.rectangle(image,(480,87),(503,92),(20,20,20),-1)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'row.png';imwrite(path,image)
            with patch('app.services.combined_local._glyphs',return_value=([],None,None)), \
                    patch('app.services.combined_local._printed_number',return_value=1):
                result=read_combined_local(path,row,[43,38,33,28])
        self.assertEqual([(b.duration,b.notes) for b in result.measures[0].beats],[(1,[])])

    def test_unresolved_model_rhythm_blocks_export_and_never_fills_beats(self):
        measure=TabMeasure(number=1,beats=[TabBeat(duration=4,notes=[TabNote(string=4,fret=7)])])
        check_vision_measure(measure)
        self.assertEqual(len(measure.beats),1)
        self.assertNotIn('duration',measure.beats[0].unresolved)
        self.assertTrue(any(i['severity']=='error' for i in validate_score(Score(settings_confirmed=True,measures=[measure]),require_review=False)))

    def test_empty_vision_result_cannot_silently_remove_a_complete_measure(self):
        image,row,_=combined_image([8]*8)
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'row.png';imwrite(path,image)
            result=recognize_combined(path,row,RecognitionConfig(strategy='vision',model='test'),
                                     [43,38,33,28],lambda *args,**kwargs:RecognitionResult(measures=[]))
        self.assertEqual(len(result.measures),1)
        self.assertEqual(result.measures[0].beats[0].unresolved,['pitch','duration'])
        self.assertTrue(any(i['severity']=='error' for i in validate_score(Score(settings_confirmed=True,measures=result.measures),require_review=False)))

    def test_auto_layout_pairs_strong_standard_staff_and_preserves_all_notation(self):
        image,_,_=combined_image([8]*8)
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);imwrite(root/'page.png',image)
            manifest=prepare_images([root/'page.png'],root/'rows')
            self.assertEqual(len(manifest['rows']),1)
            row=manifest['rows'][0]
            self.assertEqual(row['layout'],'standard-tab')
            self.assertEqual(len(row['lines']),4)
            self.assertEqual(len(row['notation_lines']),5)
            self.assertLess(row['notation_lines'][-1],row['lines'][0])
            self.assertGreaterEqual(row['notation_lines'][0],0)
            self.assertEqual(imread(root/'rows'/row['id']).shape[1],1000)

    def test_no_image_edge_is_invented_as_a_barline(self):
        self.assertEqual(measure_regions(dict(lines=[100,125,150,175],bars=[250,255,500])),[(252,500)])

    def test_explicit_pure_tab_still_uses_original_reader(self):
        with tempfile.TemporaryDirectory() as temporary:
            path=Path(temporary)/'row.png';path.write_bytes(b'test')
            with patch('app.services.tab_recognizer.read_local_tab',return_value=sample_result()) as old, \
                    patch('app.services.combined_local.read_combined_local',side_effect=AssertionError('wrong reader')):
                recognize_row(path,dict(layout='standard-tab'),RecognitionConfig(layout='tab'),[43,38,33,28])
                old.assert_called_once()

    def test_combined_dispatch_cache_and_force_are_separate_from_pure_tab(self):
        with tempfile.TemporaryDirectory() as temporary:
            root=Path(temporary);image=root/'row.png';image.write_bytes(b'unchanged')
            row=dict(id='row.png',layout='standard-tab',notation_lines=[10,20,30,40,50])
            with patch('app.services.combined_local.read_combined_local',return_value=sample_result()) as new, \
                    patch('app.services.tab_recognizer.read_local_tab',side_effect=AssertionError('wrong reader')), \
                    patch('app.services.recognition_cache.reader_signature',return_value='test-reader'):
                for force in (False,False,True):
                    recognize_row(image,row,RecognitionConfig(force=force),[43,38,33,28],cache_directory=root/'cache')
                self.assertEqual(new.call_count,2)

    def test_refresh_preserves_reviewed_notes_old_images_and_exclusions(self):
        with tempfile.TemporaryDirectory() as temporary, patch.object(storage,'STORAGE_ROOT',Path(temporary)):
            pid=storage.create_project();directory=storage.output_path(pid,'score');(directory/'rows').mkdir(parents=True)
            old=dict(id='old.png',source='PDF 第 1 页',source_row=1,strings=4)
            (directory/'manifest.json').write_text(json.dumps(dict(rows=[old],rejected=[])),encoding='utf-8')
            score=Score(settings_confirmed=True,measures=[TabMeasure(number=12,source='old.png',reviewed=True,
                confidence=.99,beats=[TabBeat(duration=1,notes=[TabNote(string=4,fret=7)])])])
            (directory/'score.json').write_text(score.model_dump_json(),encoding='utf-8')
            (directory/'rows/old.png').write_bytes(b'original')
            (directory/'input.pdf').write_bytes(b'%PDF-source')
            def prepare(inputs,output,layout='auto'):
                (output/'new.png').write_bytes(b'new image')
                return dict(rows=[dict(old,id='new.png',layout='standard-tab')],rejected=[])
            app=FastAPI();app.include_router(router,prefix='/api');client=TestClient(app)
            with patch('app.api.score_routes.prepare_images',side_effect=prepare):
                response=client.post(f'/api/projects/{pid}/score/refresh-images',json={'layout':'auto'})
            self.assertEqual(response.status_code,200,response.text)
            final=client.get(f'/api/projects/{pid}/score').json()
            saved=final['score']['measures'][0]
            self.assertTrue(saved['reviewed'])
            self.assertEqual(saved['beats'],score.measures[0].model_dump()['beats'])
            self.assertNotEqual(saved['source'],'old.png')
            self.assertEqual((directory/'rows/old.png').read_bytes(),b'original')
            self.assertEqual(len(list((directory/'backups').glob('*/score.json'))),1)

    def test_invalid_layout_is_a_validation_error(self):
        app=FastAPI();app.include_router(router,prefix='/api');client=TestClient(app)
        self.assertEqual(client.post('/api/projects/not-a-project/score/prepare?layout=invalid').status_code,422)


if __name__=='__main__':unittest.main()
