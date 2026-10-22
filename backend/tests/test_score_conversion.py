import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import guitarpro
import httpx
import numpy as np
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.score_routes import router, run_recognition
from app.models.score import GraceNote, RecognitionConfig, RecognitionResult, Score, TabBeat, TabMeasure, TabNote
from app.services.score_exporter import export_gp5, validate_score
from app.services.score_images import prepare_images
from app.services.image_io import imwrite
from app.services.tab_recognizer import recognize_row
from app.storage import manager as storage


def example():
    return Score(settings_confirmed=True, measures=[TabMeasure(number=19, reviewed=True, confidence=1, beats=[
        TabBeat(duration=4, notes=[TabNote(string=4, fret=7)]),
        TabBeat(duration=4, notes=[TabNote(string=2, fret=9, staccato=True)]),
        TabBeat(duration=8, notes=[TabNote(string=4, fret=0, kind="dead")]),
        TabBeat(duration=8, notes=[TabNote(string=4, fret=7)]),
        TabBeat(duration=8), TabBeat(duration=8, notes=[TabNote(string=4, fret=7, slide=True)]),
    ])])


class ScoreTests(unittest.TestCase):
    def test_draft_export_preserves_review_flags_and_blocks_structural_errors(self):
        score=example();score.measures[0].reviewed=False
        self.assertFalse([i for i in validate_score(score,require_review=False) if i['severity']=='error'])
        with tempfile.TemporaryDirectory() as directory:
            path=export_gp5(score,Path(directory)/'draft.gp5',require_review=False)
            self.assertEqual(len(guitarpro.parse(str(path)).tracks[0].measures),1)
            self.assertFalse(score.measures[0].reviewed)
            with self.assertRaises(ValueError):export_gp5(score,Path(directory)/'final.gp5')
            score.measures[0].beats[0].unresolved=['pitch']
            with self.assertRaises(ValueError):export_gp5(score,path,require_review=False)
            score.measures[0].beats[0].unresolved=[];score.measures[0].beats.pop()
            with self.assertRaises(ValueError):export_gp5(score,path,require_review=False)

    def test_draft_download_api_and_final_download_remain_distinct(self):
        with tempfile.TemporaryDirectory() as directory:
            original=storage.STORAGE_ROOT;storage.STORAGE_ROOT=Path(directory)
            try:
                project=storage.create_project();app=FastAPI();app.include_router(router,prefix='/api');client=TestClient(app)
                base=f'/api/projects/{project}/score';score=example();score.measures[0].reviewed=False
                client.put(base,json=score.model_dump())
                state=client.get(base).json()
                self.assertFalse([i for i in state['draft_validation'] if i['severity']=='error'])
                self.assertEqual(client.post(base+'/export-draft').status_code,200)
                self.assertTrue(client.get(base+'/download-draft').content.startswith(b'\x18FICHIER GUITAR PRO'))
                self.assertEqual(client.get(base+'/download').status_code,422)
                self.assertFalse(client.get(base).json()['score']['measures'][0]['reviewed'])
                score.measures[0].beats[0].unresolved=['duration'];client.put(base,json=score.model_dump())
                self.assertEqual(client.get(base+'/download-draft').status_code,422)
            finally:storage.STORAGE_ROOT=original

    def test_legato_slide_binary_round_trip(self):
        score=example()
        note=score.measures[0].beats[0].notes[0]
        note.slide=True;note.legato_slide=True
        score.measures[0].beats[1].notes[0].slide_out='down'
        with tempfile.TemporaryDirectory() as directory:
            song=guitarpro.parse(str(export_gp5(score,Path(directory)/'legato.gp5')))
            self.assertEqual(song.tracks[0].measures[0].voices[0].beats[0].notes[0].effect.slides,
                             [guitarpro.models.SlideType.legatoSlideTo])
            self.assertEqual(song.tracks[0].measures[0].voices[0].beats[1].notes[0].effect.slides,
                             [guitarpro.models.SlideType.outDownwards])

    def test_excluded_row_is_reversible_and_cannot_discard_reviewed_notes(self):
        with tempfile.TemporaryDirectory() as directory:
            original=storage.STORAGE_ROOT;storage.STORAGE_ROOT=Path(directory)
            try:
                project=storage.create_project();folder=storage.output_path(project,'score');folder.mkdir()
                (folder/'manifest.json').write_text(json.dumps({'rows':[{'id':'row.png'}]}),encoding='utf-8')
                (folder/'rows').mkdir();(folder/'rows'/'row.png').write_bytes(b'original image')
                score=example();score.measures[0].source='row.png'
                app=FastAPI();app.include_router(router,prefix='/api');client=TestClient(app)
                base=f'/api/projects/{project}/score';client.put(base,json=score.model_dump())
                target=base+'/rows/row.png/exclude'
                self.assertEqual(client.put(target,json={'excluded':True}).status_code,409)
                score.measures[0].reviewed=False;client.put(base,json=score.model_dump())
                self.assertEqual(client.put(target,json={'excluded':True,'reason':'duplicate fade frame'}).status_code,200)
                self.assertEqual(client.get(base).json()['score']['measures'],[])
                self.assertTrue(client.get(base).json()['manifest']['rows'][0]['excluded'])
                self.assertEqual(client.get(base+'/rows/row.png').content,b'original image')
                self.assertEqual(client.put(target,json={'excluded':False}).status_code,200)
                self.assertFalse(client.get(base).json()['manifest']['rows'][0]['excluded'])
            finally:storage.STORAGE_ROOT=original

    def test_excluded_rows_are_not_sent_to_the_recognizer(self):
        score=example();score.measures[0].source='skip.png';score.measures[0].reviewed=False
        result=score.measures[0].model_copy(deep=True);result.source='keep.png';result.number=1
        with tempfile.TemporaryDirectory() as directory,patch('app.api.score_routes.recognize_row',return_value=RecognitionResult(measures=[result])) as mocked:
            run_recognition('test',Path(directory),RecognitionConfig(max_rows=2),
                            {'rows':[{'id':'skip.png','excluded':True},{'id':'keep.png'}]},score)
            self.assertEqual(mocked.call_count,1)
            self.assertEqual(mocked.call_args.args[1]['start_number'],1)
            self.assertEqual([(m.source,m.number) for m in score.measures],[('keep.png',1)])

    def test_changed_bar_count_does_not_deduplicate_against_unprocessed_rows(self):
        score = example()
        first = score.measures[0]
        first.number = 1
        first.reviewed = False
        first.source = 'row_0001.png'
        future = first.model_copy(deep=True)
        future.number = 2
        future.source = 'row_0002.png'
        score.measures.append(future)
        extra = first.model_copy(deep=True)
        extra.number = 2
        new_future = future.model_copy(deep=True)
        new_future.number = 3
        results = [RecognitionResult(measures=[first.model_copy(deep=True),extra]),
                   RecognitionResult(measures=[new_future])]
        with tempfile.TemporaryDirectory() as directory, patch('app.api.score_routes.recognize_row', side_effect=results):
            run_recognition('test', Path(directory), RecognitionConfig(max_rows=2),
                            {'rows':[{'id':'row_0001.png'},{'id':'row_0002.png'}]}, score)
            self.assertEqual([(m.source,m.number) for m in score.measures],
                             [('row_0001.png',1),('row_0001.png',2),('row_0002.png',3)])

    def test_rerecognition_keeps_a_partly_reviewed_row_and_continues_context(self):
        score = example()
        first = score.measures[0]
        first.number = 1
        first.source = 'row_0001.png'
        second = first.model_copy(deep=True)
        second.number = 2
        second.reviewed = False
        second.beats[0].notes[0].fret = 6  # An unsaved-to-OCR human correction.
        score.measures.append(second)
        protected = [m.model_dump() for m in score.measures]
        generated = first.model_copy(deep=True)
        generated.source = 'row_0002.png'
        generated.number = 3
        generated.reviewed = False
        with tempfile.TemporaryDirectory() as directory, patch('app.api.score_routes.recognize_row', return_value=RecognitionResult(measures=[generated])) as recognize_mock:
            run_recognition('test', Path(directory), RecognitionConfig(max_rows=2),
                            {'rows':[{'id':'row_0001.png'},{'id':'row_0002.png'}]}, score)
            self.assertEqual(recognize_mock.call_count, 1)
            context = recognize_mock.call_args.args[1]
            self.assertEqual((context['id'],context['start_number']), ('row_0002.png',3))
            self.assertEqual(context['previous_notes'][0]['fret'], 7)
            saved = Score.model_validate_json((Path(directory)/'score.json').read_text(encoding='utf-8'))
            self.assertEqual([m.model_dump() for m in saved.measures[:2]], protected)
            self.assertEqual(saved.measures[-1].number, 3)

    def test_binary_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = export_gp5(example(), Path(directory) / "sample.gp5")
            song = guitarpro.parse(str(path))
            self.assertEqual(song.tempo, 120)
            self.assertEqual([s.value for s in song.tracks[0].strings], [43, 38, 33, 28])
            beats = song.tracks[0].measures[0].voices[0].beats
            self.assertEqual(len(beats), 6)
            self.assertEqual((beats[0].notes[0].string, beats[0].notes[0].value), (4, 7))
            self.assertTrue(beats[1].notes[0].effect.staccato)
            self.assertEqual(beats[2].notes[0].type, guitarpro.models.NoteType.dead)
            self.assertEqual(beats[4].status, guitarpro.models.BeatStatus.rest)
            self.assertEqual(beats[5].notes[0].effect.slides, [guitarpro.models.SlideType.shiftSlideTo])

    def test_dots_triplets_chords_and_ties(self):
        score = example()
        score.measures[0].beats = [
            TabBeat(duration=4, dotted=True, notes=[TabNote(string=1, fret=3), TabNote(string=2, fret=2, hammer=True)]),
            TabBeat(duration=8, notes=[TabNote(string=1, fret=3, kind="tie")]),
            *[TabBeat(duration=4, triplet=True) for _ in range(3)],
        ]
        self.assertFalse([i for i in validate_score(score) if i['severity'] == 'error'])
        with tempfile.TemporaryDirectory() as directory:
            song = guitarpro.parse(str(export_gp5(score, Path(directory) / "complex.gp5")))
            beats = song.tracks[0].measures[0].voices[0].beats
            self.assertTrue(beats[0].duration.isDotted)
            self.assertEqual(len(beats[0].notes), 2)
            self.assertTrue(beats[0].notes[1].effect.hammer)
            self.assertEqual(beats[1].notes[0].type, guitarpro.models.NoteType.tie)
            self.assertEqual(beats[2].duration.tuplet.enters, 3)

    def test_grace_note_binary_round_trip_and_invalid_attachment(self):
        score = example()
        note = score.measures[0].beats[0].notes[0]
        note.grace = GraceNote(fret=6, duration=32)
        with tempfile.TemporaryDirectory() as directory:
            song = guitarpro.parse(str(export_gp5(score, Path(directory) / 'grace.gp5')))
            grace = song.tracks[0].measures[0].voices[0].beats[0].notes[0].effect.grace
            self.assertEqual((grace.fret,grace.duration,grace.isOnBeat), (6,32,False))
            self.assertEqual(len(song.tracks[0].measures[0].voices[0].beats), 6)
        note.kind = 'dead'
        self.assertTrue(any('倚音' in issue['message'] and issue['severity']=='error'
                            for issue in validate_score(score)))

    def test_invalid_score_cannot_export(self):
        score = example()
        score.settings_confirmed = False
        score.measures[0].reviewed = False
        score.measures[0].beats.pop()
        score.measures[0].beats[0].notes[0].string = 6
        messages = ' '.join(i['message'] for i in validate_score(score))
        for text in ['确认', '核对', '时值', '弦号']:
            self.assertIn(text, messages)
        with self.assertRaises(ValueError):
            export_gp5(score, Path('should-not-exist.gp5'))

    def test_duplicate_and_missing_measure_numbers(self):
        score = example()
        score.measures += [score.measures[0].model_copy(deep=True)]
        self.assertTrue(any('不连续' in i['message'] for i in validate_score(score)))
        score.measures[1].number = 21
        self.assertTrue(any('不连续' in i['message'] for i in validate_score(score)))

    def test_image_filter_and_staff_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            white = np.full((280, 1000, 3), 245, dtype=np.uint8)
            black = np.zeros_like(white)
            for y in [80, 105, 130, 155]:
                cv2.line(white, (25, y), (950, y), (170, 170, 170), 1)
            imwrite(str(root / 'staff.png'), white)
            imwrite(str(root / 'black.png'), black)
            result = prepare_images([root / 'staff.png', root / 'black.png'], root / 'rows')
            self.assertEqual(len(result['rows']), 1)
            self.assertEqual(result['rows'][0]['strings'], 4)
            self.assertEqual(len(result['rejected']), 1)

    def test_ollama_protocol_and_force_manual_review(self):
        calls = []
        def respond(request):
            body = json.loads(request.content)
            calls.append((request.url.path, body))
            if request.url.path == '/api/show':
                return httpx.Response(200, json={'capabilities': ['vision', 'completion']})
            result = {'measures': [example().measures[0].model_dump()], 'warnings': []}
            return httpx.Response(200, json={'message': {'content': json.dumps(result)}})
        with tempfile.TemporaryDirectory() as directory, httpx.Client(transport=httpx.MockTransport(respond)) as client:
            path = Path(directory) / 'row.png'
            path.write_bytes(b'image-test')
            row = {'id': 'row_0001.png', 'lines': [1, 2, 3, 4], 'bars': [0, 100]}
            result = recognize_row(path, row, RecognitionConfig(model='visual'), [43,38,33,28], client)
            self.assertFalse(result.measures[0].reviewed)
            self.assertEqual(result.measures[0].source, 'row_0001.png')
            self.assertTrue(calls[1][1]['stream'])
            self.assertIn('images', calls[1][1]['messages'][0])

    def test_api_save_export_and_invalidates_stale_file(self):
        with tempfile.TemporaryDirectory() as directory:
            original = storage.STORAGE_ROOT
            storage.STORAGE_ROOT = Path(directory)
            try:
                project = storage.create_project()
                app = FastAPI()
                app.include_router(router, prefix='/api')
                client = TestClient(app)
                url = f'/api/projects/{project}/score'
                response = client.put(url, json=example().model_dump())
                self.assertEqual(response.status_code, 200)
                self.assertEqual(client.post(url + '/export').status_code, 200)
                self.assertTrue(client.get(url + '/download').content.startswith(b'\x18FICHIER GUITAR PRO'))
                invalid = example().model_dump()
                invalid['measures'][0]['reviewed'] = False
                client.put(url, json=invalid)
                self.assertEqual(client.get(url + '/download').status_code, 422)
                self.assertEqual(client.post(url + '/pdf', files={'file': ('bad.pdf', b'not a pdf')}).status_code, 400)
                self.assertEqual(client.get(url + '/rows/not-a-row.png').status_code, 404)
                staff = np.full((280, 1000, 3), 245, dtype=np.uint8)
                for y in [80, 105, 130, 155]:
                    cv2.line(staff, (25, y), (950, y), (170, 170, 170), 1)
                imwrite(str(storage.crops_dir(project) / 'crop_000001.jpg'), staff)
                prepared = client.post(url + '/prepare')
                self.assertEqual(prepared.status_code, 200)
                self.assertEqual(len(prepared.json()['rows']), 1)
                self.assertEqual(client.get(url).json()['score']['measures'], [])
            finally:
                storage.STORAGE_ROOT = original

    def test_thinking_only_model_is_stopped(self):
        def respond(request):
            if request.url.path == '/api/show':
                return httpx.Response(200, json={'capabilities': ['vision', 'thinking']})
            return httpx.Response(200, json={'message': {'thinking': 'x' * 4100, 'content': ''}, 'done': False})
        with tempfile.TemporaryDirectory() as directory, httpx.Client(transport=httpx.MockTransport(respond)) as client:
            path = Path(directory) / 'row.png'
            path.write_bytes(b'image-test')
            row = {'id': 'row_0001.png', 'lines': [1, 2, 3, 4], 'bars': [0, 100]}
            with self.assertRaisesRegex(ValueError, 'instruct'):
                recognize_row(path, row, RecognitionConfig(model='visual'), [43,38,33,28], client)

    def test_stale_model_selection_migrates_to_instruct(self):
        requested = []
        def respond(request):
            if request.url.path == '/api/tags':
                return httpx.Response(200, json={'models': [{'name': 'qwen3-vl:8b-instruct'}]})
            body = json.loads(request.content)
            requested.append(body['model'])
            if request.url.path == '/api/show':
                return httpx.Response(200, json={'capabilities': ['vision', 'completion']})
            return httpx.Response(200, json={'message': {'content': '{"measures":[],"warnings":[]}'}, 'done': True})
        with tempfile.TemporaryDirectory() as directory, httpx.Client(transport=httpx.MockTransport(respond)) as client:
            path = Path(directory) / 'row.png'
            path.write_bytes(b'image-test')
            row = {'id': 'row_0001.png', 'lines': [1, 2, 3, 4], 'bars': [0, 100]}
            result = recognize_row(path, row, RecognitionConfig(model='qwen3-vl:8b'), [43,38,33,28], client)
            self.assertEqual(requested, ['qwen3-vl:8b-instruct', 'qwen3-vl:8b-instruct'])
            self.assertTrue(any('切换' in text for text in result.warnings))


if __name__ == '__main__':
    unittest.main()
