import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import numpy as np
from app.models.score import Score,TabMeasure,TabBeat,TabNote,RecognitionResult
from app.services.image_io import imwrite
from app.services.video_score_recovery import recover_measures


class VideoRecoveryTests(unittest.TestCase):
    def test_worker_publishes_a_separate_download_and_keeps_saved_score(self):
        from fastapi import FastAPI
        from fastapi.testclient import TestClient
        from app.api.score_routes import router,run_video_recovery,write_json,_busy
        from app.storage import manager as storage
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'STORAGE_ROOT',Path(folder)):
            pid=storage.create_project();directory=storage.output_path(pid,'score');directory.mkdir()
            score=Score(settings_confirmed=True,measures=[TabMeasure(number=1,reviewed=True,
                confidence=.99,beats=[TabBeat(duration=1,notes=[TabNote(string=3,fret=7)])])])
            write_json(directory/'score.json',score.model_dump());before=(directory/'score.json').read_bytes()
            run='a'*32;_busy.add(pid)
            with patch('app.services.video_score_recovery.index_frame_views',return_value=[]), \
                 patch('app.services.video_score_recovery.stitch_frame_views',return_value=[]), \
                 patch('app.services.video_score_recovery.recover_measures',return_value=(score.model_copy(deep=True),[])):
                run_video_recovery(pid,directory,score,[],dict(x=0,y=0,width=100,height=100),run)
            self.assertEqual((directory/'score.json').read_bytes(),before)
            self.assertNotIn(pid,_busy)
            self.assertTrue((directory/'video-recovery'/run/'source-score.json').is_file())
            app=FastAPI();app.include_router(router,prefix='/api')
            with TestClient(app) as client:
                response=client.get(f'/api/projects/{pid}/score/video-recovery/{run}/download')
                self.assertEqual(response.status_code,200)
                self.assertIn('recovered-draft.gp5',response.headers['content-disposition'])
                self.assertEqual(client.get(f'/api/projects/{pid}/score/video-recovery/{run}/images/nonexistent.png').status_code,404)

    def exercise(self,unrelated=False):
        def measure(n,fret=7,broken=False):
            return TabMeasure(number=n,source='pdf.png',reviewed=True,confidence=.99,
                beats=[TabBeat(duration=4 if broken else 1,notes=[TabNote(string=3,fret=fret)],
                    unresolved=['duration'] if broken else [])])
        original=Score(settings_confirmed=True,measures=[measure(1),measure(2),measure(3,broken=True)])
        before=original.model_dump()
        visible=RecognitionResult(measures=[measure(1,5 if unrelated else 7),measure(2,5 if unrelated else 7),measure(3)])
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);image=directory/'view.png';imwrite(image,np.full((100,400,3),255,np.uint8))
            row=dict(id='view.png',measure_numbers=[1,2,3],number_anchors=[1,2,3],
                     measure_bounds=[[10,100],[100,200],[200,300]],lines=[50,60,70,80],width=400)
            views=[dict(path=str(image),frame='frame_0000000030.jpg',row=row)]
            with patch('app.services.video_score_recovery.read_combined_local',return_value=visible):
                result,evidence=recover_measures(original,[1,3],views,directory/'result')
            self.assertEqual(original.model_dump(),before)
            self.assertEqual(result.measures[:2],original.measures[:2])
            self.assertEqual(json.loads((directory/'result/evidence.json').read_text(encoding='utf-8')),evidence)
        return result,evidence

    def test_only_invalid_target_changes_in_the_copy_with_source_evidence(self):
        result,evidence=self.exercise()
        self.assertEqual(result.measures[2].beats[0].duration,1)
        self.assertFalse(result.measures[2].reviewed)
        self.assertEqual(result.measures[2].source,'pdf.png')
        self.assertEqual([e['number'] for e in evidence],[3])

    def test_matching_bar_numbers_from_an_unrelated_video_are_rejected(self):
        result,evidence=self.exercise(unrelated=True)
        self.assertEqual(result.measures[2].beats[0].duration,4)
        self.assertFalse(evidence)
