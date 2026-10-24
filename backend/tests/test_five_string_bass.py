import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np
import guitarpro
from pydantic import ValidationError
from app.models.conversion import ConversionRequest
from app.models.score import Score, TabMeasure, TabBeat, TabNote
from app.services.score_images import prepare_images
from app.services.local_tab_reader import read_local_tab
from app.services.combined_local import read_combined_local
from app.services.image_io import imwrite
from app.services.score_exporter import export_gp5
from app.services.revision_store import RevisionStore
from tests.test_combined_tab import combined_image

FIVE = [43, 38, 33, 28, 23]

class FiveStringBassTests(unittest.TestCase):
    def test_request_supports_five_without_changing_four_default(self):
        self.assertEqual(ConversionRequest(source='existing',layout='tab').tuning,[43,38,33,28])
        self.assertEqual(ConversionRequest(source='existing',layout='tab',tuning=FIVE).tuning,FIVE)
        for tuning in ([43,38,33,28,28],[43,38,33,23,28],[43,38,33,28,23,18]):
            with self.assertRaises(ValidationError):ConversionRequest(source='existing',layout='tab',tuning=tuning)

    def test_pure_tab_detects_and_reads_lowest_fifth_string(self):
        image=np.full((360,1000,3),245,np.uint8);lines=[80,105,130,155,180]
        for y in lines:cv2.line(image,(60,y),(940,y),(175,175,175),1)
        for x in (60,500,940):cv2.line(image,(x,80),(x,180),(180,180,180),1)
        cv2.putText(image,'7',(142,190),cv2.FONT_HERSHEY_SIMPLEX,.8,(40,40,40),2)
        cv2.line(image,(150,204),(150,241),(50,50,50),2)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'tab.png';imwrite(path,image)
            manifest=prepare_images([path],Path(folder)/'rows','tab')
            self.assertEqual([r['strings'] for r in manifest['rows']],[5])
            with patch('app.services.local_tab_reader.read_text',return_value=[('7',.99),('7',.99)]):
                result=read_local_tab(path,dict(id='row.png',lines=lines),FIVE)
            self.assertIn((5,7),[(n.string,n.fret) for m in result.measures for b in m.beats for n in b.notes])

    def test_combined_five_tab_not_confused_with_upper_five_line_staff(self):
        image,row,figures=combined_image([8]*8)
        cv2.line(image,(80,330),(940,330),(215,215,215),1)
        for x in (100,900):cv2.line(image,(x,305),(x,330),(30,30,30),2)
        row['lines'].append(330)
        for f in figures:f.update(string=5,y=385)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'combined.png';imwrite(path,image)
            manifest=prepare_images([path],Path(folder)/'rows','standard-tab')
            self.assertEqual(len(manifest['rows']),1)
            self.assertEqual(manifest['rows'][0]['strings'],5)
            self.assertEqual(len(manifest['rows'][0]['notation_lines']),5)
            with patch('app.services.combined_local._glyphs',return_value=(figures,None,None)),patch('app.services.combined_local._printed_number',return_value=1):
                result=read_combined_local(path,row,FIVE)
            self.assertEqual([b.duration for b in result.measures[0].beats],[8]*8)
            self.assertTrue(all(b.notes[0].string==5 for b in result.measures[0].beats))

    def test_equal_spacing_five_line_notation_pairs_with_five_string_tab(self):
        image=np.full((500,1000,3),245,np.uint8)
        for top in (80,280):
            for offset in range(5):cv2.line(image,(60,top+offset*25),(940,top+offset*25),(175,175,175),1)
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'equal.png';imwrite(path,image)
            manifest=prepare_images([path],Path(folder)/'rows','standard-tab',expected_strings=5)
            self.assertEqual(len(manifest['rows']),1)
            row=manifest['rows'][0]
            self.assertEqual(row['strings'],5)
            self.assertEqual(len(row['notation_lines']),5)

    def test_saved_confirmed_fifth_string_and_tuning_survive_real_gp5(self):
        with tempfile.TemporaryDirectory() as folder:
            store=RevisionStore(folder)
            score=Score(tuning=FIVE,settings_confirmed=True,measures=[TabMeasure(number=1,beats=[TabBeat(duration=1,notes=[TabNote(string=5,fret=12)],unresolved=['pitch'])])])
            old=store.create(score,origin='local-read',activate=True)
            confirmed=store.confirm_batch(old['id'],score,old['id'])['revision']
            self.assertEqual(store.get(old['id']),old)
            for tuning in (FIVE,[42,37,32,27,22],[41,36,31,26,21],[43,38,33,28,21]):
                candidate=Score.model_validate(confirmed['score']);candidate.tuning=tuning
                path=Path(folder)/'five.gp5';export_gp5(candidate,path)
                track=guitarpro.parse(str(path)).tracks[0]
                self.assertEqual([s.value for s in track.strings],tuning)
                self.assertEqual(track.channel.instrument,33)
                note=track.measures[0].voices[0].beats[0].notes[0]
                self.assertEqual((note.string,note.value),(5,12))
                self.assertIsNone(track.measures[0].header.marker)
