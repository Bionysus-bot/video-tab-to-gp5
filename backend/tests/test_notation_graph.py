import unittest
import numpy as np
import tempfile
import json
import httpx
from pathlib import Path
from unittest.mock import patch

from app.models.score import TabMeasure,TabBeat,TabNote
from app.services.notation_graph import align_events
from app.services.local_review import Patches,apply_patches,review_measure
from app.services.combined_tab import check_vision_measure
from app.services.score_exporter import validate_score
from app.models.score import Score
from app.models.score import RecognitionConfig


class GraphAndReviewTests(unittest.TestCase):
    def test_seam_stem_recovery_requires_head_and_visible_beams(self):
        import cv2
        from app.services.notation_graph import attach_heads
        from app.services.combined_local import stem_duration
        image=np.full((180,240),255,np.uint8)
        for x in (100,160):cv2.ellipse(image,(x,100),(8,5),0,0,360,0,-1)
        cv2.line(image,(168,30),(168,100),0,2)
        stems=[dict(x=168,top=30,bottom=103)]
        before=attach_heads(image,stems,[50,70,90,110,130],0,240,20,[100,160],seams=[100])
        self.assertFalse(any(e.get('stem_inferred') for e in before))
        cv2.rectangle(image,(100,30),(168,34),0,-1)
        cv2.rectangle(image,(100,42),(168,46),0,-1)
        after=attach_heads(image,stems,[50,70,90,110,130],0,240,20,[100,160],seams=[100])
        inferred=next(e for e in after if e.get('stem_inferred'))
        self.assertEqual(stem_duration(image,inferred,inferred['head'][0],20),(16,[]))

    def test_partial_digit_requires_pixels_at_a_known_seam_and_stays_unknown(self):
        from app.services.notation_graph import seam_digit_fragments
        image=np.full((230,160),255,np.uint8);image[128:134,49:53]=0
        self.assertFalse(seam_digit_fragments([],image,[100,130,160,190],[],30))
        cells=seam_digit_fragments([],image,[100,130,160,190],[50],30)
        self.assertEqual(len(cells),1)
        self.assertEqual(cells[0]['string'],2)
        self.assertEqual(cells[0]['text'],'')
        self.assertEqual(cells[0]['confidence'],0)

    def test_blurred_double_beams_do_not_merge_two_long_stems(self):
        import cv2
        from app.services.combined_local import standard_stems
        image=np.full((200,220),255,np.uint8)
        for x in (70,140):cv2.line(image,(x,35),(x,120),0,3)
        cv2.rectangle(image,(70,85),(140,119),0,-1)
        stems=standard_stems(image,[40,60,80,100,120],180)
        self.assertEqual(len(stems),2)
        self.assertTrue(all(any(abs(s['x']-x)<5 for s in stems) for x in (70,140)))

    def test_narrow_flag_is_visible_before_half_space_samples(self):
        import cv2
        from app.services.combined_local import stem_duration
        image=np.full((180,200),255,np.uint8)
        cv2.line(image,(90,30),(90,110),0,2)
        cv2.rectangle(image,(95,38),(98,48),0,-1)
        self.assertEqual(stem_duration(image,dict(x=90,top=30,bottom=110,down=False),86,20),(8,[]))
        image[:,95:99]=255
        self.assertEqual(stem_duration(image,dict(x=90,top=30,bottom=110,down=False),86,20)[0],4)

    def test_head_pitch_requires_two_consistent_visible_examples(self):
        from app.services.notation_graph import corroborate_pitches
        def event(fret=None,detected=True):
            return dict(beat=TabBeat(duration=4,notes=[] if fret is None else [TabNote(string=3,fret=fret)],
                unresolved=['pitch'] if fret is None else []),head=[50,70],head_detected=detected,
                confidence=.99,tab_strings=[3])
        a,b,unknown=event(7),event(7),event()
        corroborate_pitches([a,unknown],50,20,[43,38,33,28])
        self.assertFalse(unknown['beat'].notes)
        corroborate_pitches([a,b,unknown],50,20,[43,38,33,28])
        self.assertEqual(unknown['beat'].notes[0].fret,7)
        self.assertFalse(unknown['beat'].unresolved)
        weak=event(1);weak['beat'].unresolved=['pitch'];weak['confidence']=.2
        corroborate_pitches([a,b,weak],50,20,[43,38,33,28])
        self.assertEqual(weak['beat'].notes[0].fret,7)
        certain=event(1);certain['beat'].unresolved=['pitch']
        corroborate_pitches([a,b,certain],50,20,[43,38,33,28])
        self.assertEqual(certain['beat'].notes[0].fret,1)
        for examples in ([event(7),event(8)],[event(7),event(7)]):
            unknown=event(detected=examples[0]['beat'].notes[0].fret!=examples[1]['beat'].notes[0].fret)
            corroborate_pitches(examples+[unknown],50,20,[43,38,33,28])
            self.assertFalse(unknown['beat'].notes)

    def test_two_digits_need_one_head_and_agreeing_ocr(self):
        from app.services.notation_graph import refine_fret_crops
        figures=[dict(x=20,y=20,w=6,h=22,string=2,text='',alternative='1',confidence=0,
                      x_center=23,parenthesized=False),
                 dict(x=30,y=20,w=12,h=27,string=2,text='2',alternative='2',confidence=.95,
                      x_center=36,parenthesized=False)]
        image=np.full((80,100,3),255,np.uint8)
        read=lambda crops:[('12',.99)]*len(crops)
        result=refine_fret_crops([dict(c) for c in figures],image,30,[dict(head=[31,5])],read)
        self.assertEqual([c['text'] for c in result],['12'])
        result=refine_fret_crops([dict(c) for c in figures],image,30,[dict(head=[23,5]),dict(head=[36,5])],read)
        self.assertEqual(len(result),2)

    def test_bad_new_association_keeps_the_visible_four_quarter_notes(self):
        from tests.test_combined_tab import combined_image
        from app.services.combined_local import read_combined_local
        from app.services.image_io import imwrite
        image,row,figures=combined_image([4]*4)
        graph=[dict(x=round(c['x_center']-9.6),top=122,bottom=196,head=[c['x_center'],122],
                    down=True,head_detected=True,beam_group=2) for c in figures]
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'row.png';imwrite(path,image);evidence={}
            with patch('app.services.combined_local._glyphs',return_value=(figures,None,None)), \
                 patch('app.services.combined_local._printed_number',return_value=1), \
                 patch('app.services.notation_graph.attach_heads',return_value=graph), \
                 patch('app.services.notation_graph.connect_beams'):
                result=read_combined_local(path,row,[43,38,33,28],evidence)
        self.assertEqual([b.duration for b in result.measures[0].beats],[4]*4)
        self.assertTrue(all(not e['head_detected'] for e in evidence['events'] if not e['fragment']))

    def test_three_visible_quarters_are_not_filled_to_make_four(self):
        from tests.test_combined_tab import combined_image
        from app.services.combined_local import read_combined_local
        from app.services.image_io import imwrite
        image,row,figures=combined_image([4]*3)
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'row.png';imwrite(path,image)
            with patch('app.services.combined_local._glyphs',return_value=(figures,None,None)), \
                 patch('app.services.combined_local._printed_number',return_value=1):
                result=read_combined_local(path,row,[43,38,33,28])
        self.assertEqual(len(result.measures[0].beats),3)
        self.assertTrue(any('时值不完整' in i['message'] for i in validate_score(
            Score(settings_confirmed=True,measures=result.measures),require_review=False)))

    def test_ordered_alignment_never_reuses_a_stem(self):
        events=[dict(head=[100,50],x=95),dict(head=[130,50],x=125)]
        result=align_events([101,105,131],events,20)
        self.assertEqual(len(result),2)
        self.assertEqual(len({v['x'] for v in result.values()}),2)

    def test_an_extra_head_does_not_shift_the_remaining_matches(self):
        events=[dict(head=[x,50],x=x) for x in [100,140,180]]
        result=align_events([101,179],events,20)
        self.assertEqual([result[i]['x'] for i in (0,1)],[100,180])

    def test_missing_match_stays_unassigned(self):
        self.assertEqual(align_events([300],[dict(head=[100,50])],20),{})

    def test_meter_error_does_not_mark_every_beat_unknown(self):
        m=TabMeasure(number=1,beats=[TabBeat(duration=4),TabBeat(duration=8)])
        check_vision_measure(m)
        self.assertTrue(all(not b.unresolved for b in m.beats))
        self.assertTrue(any(i['severity']=='error' for i in validate_score(Score(measures=[m]),require_review=False)))

    def test_pitch_patch_changes_only_the_uncertain_beat_and_keeps_its_duration(self):
        m=TabMeasure(number=1,reviewed=True,beats=[TabBeat(duration=2,notes=[TabNote(string=3,fret=7)],unresolved=['pitch']),
            TabBeat(duration=2,notes=[TabNote(string=3,fret=5)])])
        before=m.model_dump()
        patches=Patches.model_validate(dict(patches=[dict(beat_index=1,duration=4,notes=[dict(string=3,fret=9)],confidence=.95,evidence='visible fret 9')]))
        candidate,logs=apply_patches(m,patches,[43,38,33,28],[])
        self.assertEqual(candidate.beats[0].duration,2)
        self.assertEqual(candidate.beats[0].notes[0].fret,9)
        self.assertEqual(candidate.beats[1],m.beats[1])
        self.assertEqual(m.model_dump(),before)
        self.assertFalse(candidate.reviewed)
        self.assertTrue(logs)

    def test_patch_cannot_change_a_certain_pitch_to_force_a_meter_fit(self):
        m=TabMeasure(number=1,beats=[TabBeat(duration=2,notes=[TabNote(string=3,fret=7)])])
        p=Patches.model_validate(dict(patches=[dict(beat_index=1,duration=1,notes=[dict(string=2,fret=9)],confidence=.95,evidence='one whole note')]))
        candidate,logs=apply_patches(m,p,[43,38,33,28],[])
        self.assertEqual(candidate.beats[0].notes,m.beats[0].notes)
        self.assertEqual(candidate.beats[0].duration,1)

    def test_patch_that_worsens_meter_is_rejected(self):
        m=TabMeasure(number=1,beats=[TabBeat(duration=2,unresolved=['duration'])])
        p=Patches.model_validate(dict(patches=[dict(beat_index=1,duration=8,confidence=.95,evidence='one short note')]))
        candidate,logs=apply_patches(m,p,[43,38,33,28],[])
        self.assertEqual(candidate,m)
        self.assertFalse(logs)

    def test_invalid_string_does_not_remove_uncertainty(self):
        m=TabMeasure(number=1,beats=[TabBeat(duration=1,notes=[TabNote(string=3,fret=7)],unresolved=['pitch'])])
        p=Patches.model_validate(dict(patches=[dict(beat_index=1,notes=[dict(string=7,fret=9)],confidence=.95,evidence='visible string 7')]))
        candidate,logs=apply_patches(m,p,[43,38,33,28],[])
        self.assertEqual(candidate,m)

    def test_model_transport_receives_context_and_can_only_patch_one_allowed_beat(self):
        m=TabMeasure(number=12,beats=[TabBeat(duration=1,notes=[TabNote(string=3,fret=7)],unresolved=['pitch'])])
        def handle(request):
            payload=json.loads(request.content)
            self.assertEqual(len(payload['messages'][0]['images']),2)
            self.assertFalse(payload['think'])
            return httpx.Response(200,json=dict(message=dict(content=json.dumps(dict(patches=[dict(
                beat_index=1,notes=[dict(string=3,fret=7)],confidence=.95,evidence='fret seven on third string')])))))
        with tempfile.TemporaryDirectory() as directory,httpx.Client(transport=httpx.MockTransport(handle)) as client:
            path=Path(directory)/'image.png';path.write_bytes(b'image-data')
            candidate,logs=review_measure(path,path,m,RecognitionConfig(model='test'),[43,38,33,28],[],client)
        self.assertTrue(logs)
        self.assertFalse(candidate.beats[0].unresolved)
        self.assertEqual(m.beats[0].unresolved,['pitch'])
