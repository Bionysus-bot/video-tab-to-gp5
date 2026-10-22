import copy
import unittest
from unittest.mock import patch

import cv2
import numpy as np

from app.models.score import TabBeat
from app.services.combined_local import number_sequence, standard_rests
from app.services.score_continuity import join_fragments


def staff_image():
    image = np.full((320,1000,3),245,np.uint8)
    row = dict(id='left.png',layout='standard-tab',lines=[180,205,230,255],
               notation_lines=[40,56,72,88,104],bars=[100,700],measure_numbers=[1],width=1000,height=320)
    for y in row['lines']+row['notation_lines']:
        cv2.line(image,(0,y),(999,y),(215,215,215),1)
    return image,row


class ContinuityTests(unittest.TestCase):
    def test_same_numbered_fragments_join_without_mutating_originals(self):
        image,left = staff_image(); following,right = staff_image()
        right.update(id='right.png',bars=[300,900],measure_numbers=[3])
        original = image.copy(); before = copy.deepcopy(left)
        (joined,meta),reason = join_fragments(image,left,following,right)
        self.assertFalse(reason)
        self.assertEqual(meta['measure_numbers'],[1,2])
        self.assertEqual(meta['measure_bounds'],[(100,700),(700,1300)])
        np.testing.assert_array_equal(joined[:,:1000],original)
        self.assertEqual(left,before)

    def test_different_measure_numbers_cannot_be_stitched(self):
        image,left = staff_image(); following,right = staff_image()
        right.update(bars=[300,900],measure_numbers=[4])
        joined,reason = join_fragments(image,left,following,right)
        self.assertIsNone(joined)
        self.assertIn('编号',reason)

    def test_incompatible_standard_staff_is_not_warped_into_alignment(self):
        image,left = staff_image(); following,right = staff_image()
        right.update(bars=[300,900],measure_numbers=[3],notation_lines=[20,36,52,68,84])
        self.assertIsNone(join_fragments(image,left,following,right)[0])

    def test_multiple_number_anchors_outvote_a_missing_digit(self):
        image,row = staff_image();image=np.pad(image,((0,0),(0,1000),(0,0)),constant_values=245)
        row['bars']=[100,300,500,700,900,1100,1300,1500,1700]
        with patch('app.services.combined_local._printed_number',side_effect=[2,None,24,None,None,None,None,29]):
            numbers,anchors = number_sequence(image,row)
        self.assertEqual(numbers,list(range(22,30)))
        self.assertEqual(anchors[0],2)

    def test_single_unexpected_number_is_not_used_as_a_row_anchor(self):
        image,row = staff_image()
        with patch('app.services.combined_local._printed_number',return_value=2):
            self.assertEqual(number_sequence(image,row)[0],[])

    def test_half_rest_does_not_get_stretched_to_whole_duration(self):
        gray = np.full((160,600),245,np.float32)
        staff=[40,56,72,88,104]
        cv2.rectangle(gray,(250,64),(267,71),30,-1)
        rests=standard_rests(gray,staff,100,500,16,[])
        self.assertEqual([b.duration for _,b in rests],[2])

    def test_note_locations_exclude_rest_candidates(self):
        gray = np.full((160,600),245,np.float32)
        cv2.rectangle(gray,(250,64),(267,71),30,-1)
        self.assertEqual(standard_rests(gray,[40,56,72,88,104],100,500,16,[258]),[])


if __name__=='__main__':unittest.main()
