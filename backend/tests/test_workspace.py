import tempfile
import threading
import unittest
from pathlib import Path
from unittest.mock import patch

import guitarpro
from fastapi import FastAPI
from fastapi.testclient import TestClient
from app.models.score import Score, TabMeasure, TabBeat, TabNote, RecognitionResult, TabFragment
from app.models.conversion import ConversionRequest
from app.services.revision_store import RevisionStore, read, write
from app.services import conversion_pipeline as pipeline, project_guard
from app.services.draft_artifact import export_partial
from app.api.conversion_routes import router
from app.storage import manager as storage


def sample():
    return Score(measures=[TabMeasure(number=1,source='row_0001.png',confidence=.2,
        beats=[TabBeat(duration=4,notes=[TabNote(string=4,fret=10)],unresolved=['pitch'])])])


class WorkspaceTests(unittest.TestCase):
    def test_batch_confirmation_skips_invalid_bars_and_preserves_prior_version(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder);score=sample()
            score.measures[0].beats[0].duration=1
            score.measures[0].issues=['边缘片段候选：待核对']
            for number in range(2,6):
                measure=score.measures[0].model_copy(deep=True);measure.number=number
                score.measures.append(measure)
            score.measures[1].beats[0].duration=4
            score.measures[2].beats[0].notes=[]
            score.measures[3].reviewed=True;score.measures[3].beats[0].unresolved=[]
            # Explicitly identified rests can be confirmed; unknown missing notes cannot.
            score.measures[4].beats[0].notes=[];score.measures[4].beats[0].unresolved=[]
            old=store.create(score,origin='local-read',activate=True)
            score.measures[0].beats[0].notes[0].fret=12
            result=store.confirm_batch(old['id'],score,old['id'])
            revision=result['revision']
            self.assertEqual([m['number'] for m in result['confirmed']],[1,5])
            self.assertEqual([m['number'] for m in result['skipped']],[2,3])
            self.assertIn('时值不完整','；'.join(result['skipped'][0]['reasons']))
            self.assertIn('缺少音符','；'.join(result['skipped'][1]['reasons']))
            self.assertEqual(len(store.list()),2)
            self.assertEqual(store.get(old['id']),old)
            self.assertEqual(revision['score']['measures'][1:4],score.model_dump()['measures'][1:4])
            path=Path(folder)/'batch.gp5'
            export_partial(Score.model_validate(revision['score']),path)
            song=guitarpro.parse(str(path))
            self.assertIsNone(song.measureHeaders[0].marker)
            self.assertFalse(song.tracks[0].measures[0].voices[0].beats[0].text)
            self.assertEqual(song.tracks[0].measures[0].voices[0].beats[0].notes[0].value,12)
            self.assertIsNotNone(song.measureHeaders[1].marker)
            self.assertIsNone(song.measureHeaders[4].marker)

    def test_batch_confirmation_api_rejects_stale_and_restructured_edits_atomically(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'STORAGE_ROOT',Path(folder)):
            pid=storage.create_project();store=RevisionStore(storage.output_path(pid,'score'))
            score=sample();old=store.create(score,origin='local-read',activate=True)
            app=FastAPI();app.include_router(router,prefix='/api');client=TestClient(app)
            url=f'/api/projects/{pid}/revisions/{old["id"]}/confirm-batch'
            score.measures[0].number=2
            body=dict(expected_revision=old['id'],score=score.model_dump())
            self.assertEqual(client.post(url,json=body).status_code,409)
            self.assertEqual(len(store.list()),1)
            score.measures[0].number=1;score.measures[0].beats[0].duration=1
            body['score']=score.model_dump()
            response=client.post(url,json=body)
            self.assertEqual(response.status_code,200,response.text)
            self.assertEqual(len(response.json()['confirmed']),1)
            self.assertEqual(client.post(url,json=body).status_code,409)
            self.assertEqual(len(store.list()),2)

    def test_batch_confirmation_retains_invalid_ties_and_all_skipped_edits(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder);score=sample()
            score.measures[0].beats[0].duration=1
            score.measures[0].beats[0].notes[0].kind='tie'
            old=store.create(score,origin='local-read',activate=True)
            result=store.confirm_batch(old['id'],score,old['id'])
            self.assertEqual(result['confirmed'],[])
            self.assertEqual(result['revision']['score'],score.model_dump())
            self.assertIn('延音','；'.join(result['skipped'][0]['reasons']))

    def test_confirmation_removes_only_selected_bar_markers_in_real_gp5(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder);score=sample()
            score.measures[0].beats[0].duration=1
            score.measures[0].issues=['边缘片段候选：待核对']
            second=score.measures[0].model_copy(deep=True);second.number=2
            score.measures.append(second)
            old=store.create(score,origin='local-read',activate=True)
            before=old['score']
            confirmed=store.confirm_measure(old['id'],old['entities'][0]['id'],score,old['id'])
            self.assertTrue(confirmed['score']['measures'][0]['reviewed'])
            self.assertFalse(confirmed['score']['measures'][1]['reviewed'])
            self.assertEqual(store.get(old['id'])['score'],before)
            self.assertFalse([i for i in confirmed['issues'] if i['measure_index']==0])
            self.assertTrue([i for i in confirmed['issues'] if i['measure_index']==1])
            path=Path(folder)/'confirmed.gp5'
            report=export_partial(Score.model_validate(confirmed['score']),path)
            song=guitarpro.parse(str(path))
            self.assertIsNone(song.measureHeaders[0].marker)
            self.assertFalse(song.tracks[0].measures[0].voices[0].beats[0].text)
            self.assertIsNotNone(song.measureHeaders[1].marker)
            self.assertIn('CHECK',song.tracks[0].measures[1].voices[0].beats[0].text)
            self.assertEqual([i['number'] for i in report['uncertain']],[2])
            self.assertEqual(song.tracks[0].measures[0].voices[0].beats[0].notes[0].value,10)

    def test_confirmation_refuses_wrong_meter_and_unknown_missing_note(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder);score=sample();old=store.create(score,origin='local-read',activate=True)
            with self.assertRaisesRegex(ValueError,'时值不完整'):
                store.confirm_measure(old['id'],old['entities'][0]['id'],score,old['id'])
            score.measures[0].beats[0].duration=1;score.measures[0].beats[0].notes=[]
            with self.assertRaisesRegex(ValueError,'缺少音符'):
                store.confirm_measure(old['id'],old['entities'][0]['id'],score,old['id'])
            self.assertEqual(store.state()['active_revision'],old['id'])

    def test_confirmation_api_saves_pending_corrections_and_rejects_stale_request(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'STORAGE_ROOT',Path(folder)):
            pid=storage.create_project();store=RevisionStore(storage.output_path(pid,'score'))
            score=sample();old=store.create(score,origin='local-read',activate=True)
            score.measures[0].beats[0].duration=1;score.measures[0].beats[0].notes[0].fret=12
            app=FastAPI();app.include_router(router,prefix='/api');client=TestClient(app)
            url=f'/api/projects/{pid}/revisions/{old["id"]}/measures/{old["entities"][0]["id"]}/confirm'
            body=dict(expected_revision=old['id'],score=score.model_dump())
            response=client.post(url,json=body);self.assertEqual(response.status_code,200,response.text)
            value=response.json()
            self.assertEqual(value['score']['measures'][0]['beats'][0]['notes'][0]['fret'],12)
            self.assertTrue(value['score']['measures'][0]['reviewed'])
            self.assertIn(value['entities'][0]['id'],value['protected'])
            self.assertEqual(client.post(url,json=body).status_code,409)

    def test_legacy_import_idempotent_and_manual_edit_conflict(self):
        with tempfile.TemporaryDirectory() as folder:
            directory=Path(folder);write(directory/'score.json',sample().model_dump())
            before=(directory/'score.json').read_bytes();store=RevisionStore(directory)
            store.import_legacy();store.import_legacy()
            self.assertEqual(len(store.list()),1)
            old=store.get(store.state()['active_revision'])
            self.assertEqual(old['protected'],[old['entities'][0]['id']])
            score=Score.model_validate(old['score']);score.measures[0].beats[0].notes[0].fret=12
            new=store.save_edit(old['id'],score,old['id'])
            self.assertEqual(new['entities'],old['entities'])
            with self.assertRaises(ValueError):store.save_edit(old['id'],score,old['id'])
            self.assertEqual((directory/'score.json').read_bytes(),before)
            self.assertEqual(store.get(old['id'])['score']['measures'][0]['beats'][0]['notes'][0]['fret'],10)

    def test_draft_preserves_known_notes_in_wrong_meter_without_source_mutation(self):
        with tempfile.TemporaryDirectory() as folder:
            score=sample();before=score.model_dump();path=Path(folder)/'draft.gp5'
            report=export_partial(score,path)
            self.assertEqual(score.model_dump(),before)
            parsed=guitarpro.parse(str(path));measure=parsed.tracks[0].measures[0]
            self.assertEqual(measure.voices[0].beats[0].notes[0].value,10)
            self.assertIn('PARTIAL',measure.header.marker.title)
            self.assertEqual(len(report['partial_bars']),1)
            self.assertEqual(report['placeholders'],[])

    def test_unknown_whole_bar_stays_explicit_placeholder(self):
        with tempfile.TemporaryDirectory() as folder:
            score=sample();score.measures[0].number=2
            report=export_partial(score,Path(folder)/'draft.gp5')
            self.assertEqual(report['placeholders'][0]['number'],1)

    def test_publishing_does_not_overwrite_concurrent_manual_revision(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder);base=store.create(sample(),origin='local-read',activate=True,input_id='input')
            edited=sample();edited.measures[0].beats[0].notes[0].fret=11
            manual=store.save_edit(base['id'],edited,base['id'])
            job=dict(base_revision=base['id'],revision=None,input_key='input')
            machine=pipeline.publish(store,job,sample(),{'rows':[]},'local-read')
            self.assertEqual(store.state()['active_revision'],manual['id'])
            self.assertNotEqual(machine['id'],manual['id'])

    def test_pipeline_uses_independent_rows_and_downloads_despite_low_score(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'STORAGE_ROOT',Path(folder)):
            pid=storage.create_project();directory=storage.output_path(pid,'score');directory.mkdir()
            manifest=dict(rows=[dict(id='row_0001.png',layout='tab',source='test',strings=4)],rejected=[])
            write(directory/'manifest.json',manifest);(directory/'rows').mkdir();(directory/'rows/row_0001.png').write_bytes(b'fixture')
            store=RevisionStore(directory)
            config=ConversionRequest(source='existing',layout='tab',recover=False)
            jobs=[]
            def capture_start(thread):jobs.append(thread)
            with patch('threading.Thread.start',capture_start),patch('app.services.recognition_cache.reader_signature',return_value='test'):
                job=pipeline.start(store,config,pid)
                with patch('app.services.recognition_cache.cache_key',return_value=None),patch.object(pipeline,'ReaderSession') as reader:
                    fragment=sample().measures[0].model_copy(deep=True);fragment.number=2
                    reader.return_value.call.return_value=RecognitionResult(measures=sample().measures,
                        fragments=[TabFragment(side='right',bounds=[100,200],measure=fragment)])
                    pipeline.run(store,pid,job,threading.Event())
            result=pipeline.get_job(store,job['id'])
            self.assertEqual(result['status'],'completed',result['message'])
            self.assertTrue(result['artifact'])
            revision=store.get(result['revision'])
            self.assertEqual(len(revision['score']['measures']),2)
            self.assertIn('duration',revision['score']['measures'][1]['beats'][0]['unresolved'])
            self.assertTrue(revision['manifest']['fragments'])
            self.assertFalse((directory/'score.json').exists())
            app=FastAPI();app.include_router(router,prefix='/api');client=TestClient(app)
            response=client.get(f'/api/projects/{pid}/artifacts/{result["artifact"]["id"]}/download')
            self.assertEqual(response.status_code,200)
            self.assertEqual(client.get(f'/api/projects/{pid}/artifacts/not-an-id/download').status_code,409)

    def test_restart_marks_interrupted_and_shared_lock_blocks_legacy(self):
        from app.api.score_routes import acquire,release
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder);identifier='a'*32
            write(pipeline.job_path(store,identifier),dict(id=identifier,status='running'))
            self.assertEqual(pipeline.get_job(store,identifier)['status'],'interrupted')
        self.assertTrue(project_guard.acquire('test-project','conversion'))
        try:
            with self.assertRaises(Exception):acquire('test-project')
        finally:release('test-project')

    def test_cancelled_process_stops_and_no_publish(self):
        event=threading.Event();event.set()
        with self.assertRaises(pipeline.Cancelled):
            pipeline.bounded('time','sleep',(10,),cancel=event,timeout=1)

    def test_reader_session_reuses_process_and_can_be_cancelled(self):
        session=pipeline.ReaderSession();event=threading.Event()
        try:
            first=session.call('os','getpid',(),cancel=event)
            second=session.call('os','getpid',(),cancel=event)
            self.assertEqual(first,second)
            event.set()
            with self.assertRaises(pipeline.Cancelled):session.call('time','sleep',(10,),cancel=event)
        finally:session.close()
        self.assertFalse(session.process.is_alive())

    def test_bad_version_id_cannot_escape_storage(self):
        with tempfile.TemporaryDirectory() as folder:
            with self.assertRaises(ValueError):RevisionStore(folder).get('../score.json')

    def test_resume_after_own_published_revision_and_no_duplicate_job(self):
        with tempfile.TemporaryDirectory() as folder,patch.object(storage,'STORAGE_ROOT',Path(folder)):
            pid=storage.create_project();store=RevisionStore(storage.output_path(pid,'score'))
            write(store.directory/'manifest.json',dict(rows=[dict(id='r.png',layout='tab')]))
            (store.directory/'rows').mkdir();(store.directory/'rows/r.png').write_bytes(b'fixture')
            config=ConversionRequest(source='existing',layout='tab')
            with patch('threading.Thread.start'):
                first=pipeline.start(store,config,pid)
                duplicate=pipeline.start(store,config,pid)
                self.assertEqual(first['id'],duplicate['id'])
                revision=store.create(sample(),origin='local-read',activate=True)
                first.update(status='cancelled',revision=revision['id'])
                write(pipeline.job_path(store,first['id']),first)
                pipeline._live.pop(first['id'],None);project_guard.release(pid)
                resumed=pipeline.start(store,config,pid,resume=first['id'])
                self.assertEqual(resumed['activation_expected'],revision['id'])
                pipeline._live.pop(resumed['id'],None);project_guard.release(pid)

    def test_new_source_does_not_activate_over_protected_legacy(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder);write(store.directory/'score.json',sample().model_dump())
            store.import_legacy();active=store.state()['active_revision']
            job=dict(base_revision=active,revision=None,input_key='new-source')
            pipeline.publish(store,job,sample(),dict(rows=[]),'local-read')
            self.assertEqual(store.state()['active_revision'],active)

    def test_old_video_recovery_is_imported_once_without_changing_active_edit(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder);write(store.directory/'score.json',sample().model_dump())
            store.import_legacy();active=store.state()['active_revision']
            write(store.directory/'video-recovery'/'test'/'recognized-score.json',sample().model_dump())
            store.import_legacy();store.import_legacy()
            self.assertEqual(len(store.list()),2)
            self.assertEqual(store.state()['active_revision'],active)

    def test_invalid_roi_and_tuning_rejected(self):
        for fields in [dict(roi=dict(x=-1,y=0,width=10,height=10)),dict(tuning=[28,33,38,43])]:
            with self.assertRaises(ValueError):ConversionRequest(source='video',layout='tab',**fields)

    def test_video_rows_use_independent_anchors_and_keep_both_sources(self):
        from app.services.score_continuity import stitch_rows
        import numpy as np
        rows=[dict(id='a.png',layout='standard-tab'),dict(id='b.png',layout='standard-tab')]
        seen=[]
        def numbers(image,row):
            seen.append(row.get('number_floor'))
            return [1,2,3],[1,2,3]
        with patch('app.services.score_continuity.imread',return_value=np.zeros((10,10,3),dtype=np.uint8)), \
             patch('app.services.score_continuity.number_sequence',side_effect=numbers), \
             patch('app.services.score_continuity.join_fragments',return_value=(None,'重复覆盖，不拼接')):
            stitch_rows(Path('.'),rows,independent_anchors=True)
        self.assertEqual(seen,[None,None])
        self.assertEqual(rows[1]['measure_numbers'],[1,2,3])


if __name__=='__main__':unittest.main()
