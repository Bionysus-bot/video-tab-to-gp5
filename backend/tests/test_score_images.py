import tempfile
import unittest
from pathlib import Path

import cv2
import numpy as np

from app.services.image_io import imwrite
from app.services.score_images import prepare_images, staff_groups


def draw_staff(image, top, count=4, fragmented=()):
    for index in range(count):
        y = top + index * 25
        segments = [(25, 950)] if index not in fragmented else [(25, 80), (250, 305), (500, 555)]
        for left, right in segments:
            cv2.line(image, (left, y), (right, y), (170, 170, 170), 1)


class StaffDetectionTests(unittest.TestCase):
    def test_recovers_one_fragmented_string_in_four_to_six_string_rows(self):
        # About 16% of the width remains on the obscured string, below the old
        # 20% cutoff. The other strings still provide clear geometric evidence.
        for count in (4, 5, 6):
            with self.subTest(strings=count):
                image = np.full((300, 1000, 3), 245, dtype=np.uint8)
                draw_staff(image, 70, count, fragmented=(2,))
                groups = staff_groups(image)
                self.assertEqual(len(groups), 1)
                self.assertEqual(groups[0], [70 + index * 25 for index in range(count)])

    def test_does_not_invent_an_invisible_string(self):
        image = np.full((280, 1000, 3), 245, dtype=np.uint8)
        for y in (80, 105, 155):
            cv2.line(image, (25, y), (950, y), (170, 170, 170), 1)
        self.assertEqual(staff_groups(image), [])

    def test_rejects_a_group_with_two_weak_strings(self):
        image = np.full((280, 1000, 3), 245, dtype=np.uint8)
        draw_staff(image, 80, fragmented=(1, 2))
        self.assertEqual(staff_groups(image), [])

    def test_preserves_strong_group_beside_a_weak_extra_line(self):
        image = np.full((300, 1000, 3), 245, dtype=np.uint8)
        draw_staff(image, 80, count=5, fragmented=(4,))
        self.assertEqual(staff_groups(image), [[80, 105, 130, 155]])

    def test_recovers_middle_row_in_order_and_records_source_position(self):
        image = np.full((700, 1000, 3), 245, dtype=np.uint8)
        for top in (80, 300, 520):
            draw_staff(image, top, fragmented=(2,) if top == 300 else ())
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            imwrite(root / 'three-rows.png', image)
            manifest = prepare_images([root / 'three-rows.png'], root / 'rows')
            self.assertEqual(len(manifest['rows']), 3)
            self.assertEqual([row['source_row'] for row in manifest['rows']], [1, 2, 3])
            self.assertEqual([row['strings'] for row in manifest['rows']], [4, 4, 4])
            self.assertTrue(all((root / 'rows' / row['id']).is_file() for row in manifest['rows']))
            self.assertEqual(manifest['rejected'], [])


if __name__ == '__main__':
    unittest.main()
