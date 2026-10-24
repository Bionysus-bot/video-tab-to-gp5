import unittest
from unittest.mock import Mock
import numpy as np
import cv2
from app.services.notation_graph import refine_fret_crops


class WorkspaceNotationTests(unittest.TestCase):
    def test_visible_tie_requires_curve_and_matching_pitch(self):
        from app.services.notation_graph import visible_tie_curve,link_row_ties
        from app.models.score import TabMeasure,TabBeat,TabNote
        image=np.full((160,260),255,np.uint8)
        xs=np.arange(49,191)
        ys=80+np.round(18*(1-((xs-120)/71)**2)).astype(int)
        cv2.polylines(image,[np.column_stack([xs,ys]).astype(np.int32)],False,0,2)
        self.assertTrue(visible_tie_curve(image,[40,60],[200,60],20))
        a=TabBeat(duration=4,notes=[TabNote(string=4,fret=7)])
        b=TabBeat(duration=4,notes=[TabNote(string=4,fret=7)])
        measures=[TabMeasure(number=15,beats=[a]),TabMeasure(number=16,beats=[b])]
        events=[dict(beat=a,head=[40,60],head_detected=True),dict(beat=b,head=[200,60],head_detected=True)]
        link_row_ties(measures,events,image,20)
        self.assertEqual(b.notes[0].kind,'tie')
        b.notes[0].kind='normal';b.notes[0].fret=8
        link_row_ties(measures,events,image,20)
        self.assertEqual(b.notes[0].kind,'normal')

    def test_straight_beam_is_not_a_tie(self):
        from app.services.notation_graph import visible_tie_curve
        image=np.full((160,260),255,np.uint8)
        cv2.line(image,(49,80),(191,80),0,2)
        self.assertFalse(visible_tie_curve(image,[40,60],[200,60],20))

    def test_wide_zero_is_rechecked_as_ten_at_single_head(self):
        cell=dict(text='0',confidence=.98,parenthesized=False,x=20,y=10,w=24,h=22,string=4,x_center=32)
        read=Mock(side_effect=[[('10',.96),('10',.93)],[]])
        result=refine_fret_crops([cell],np.full((80,100,3),255,np.uint8),30,[dict(head=[32,5])],read)
        self.assertEqual(result[0]['text'],'10')

    def test_wide_digit_with_two_heads_cannot_merge_separate_notes(self):
        cell=dict(text='0',confidence=.98,parenthesized=False,x=20,y=10,w=24,h=22,string=4,x_center=32)
        read=Mock(return_value=[])
        result=refine_fret_crops([cell],np.full((80,100,3),255,np.uint8),30,[dict(head=[25,5]),dict(head=[40,5])],read)
        self.assertEqual(result[0]['text'],'0')


if __name__=='__main__':unittest.main()
