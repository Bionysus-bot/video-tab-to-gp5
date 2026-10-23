import tempfile
import unittest
from pathlib import Path

import guitarpro

from app.models.score import Score,TabMeasure,TabBeat,TabNote
from app.services.diagnostic_export import export_diagnostic
from app.services.score_exporter import validate_score


class DiagnosticExportTests(unittest.TestCase):
    def test_low_legacy_score_is_retained_as_information_not_a_whole_bar_error(self):
        score=Score(measures=[TabMeasure(number=1,confidence=.1,beats=[TabBeat(duration=1,notes=[TabNote(string=3,fret=7)])])])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'draft.gp5';report=export_diagnostic(score,path)
            self.assertFalse(report['uncertain'])
            self.assertEqual(report['ocr_warnings'][0]['number'],1)
            self.assertIsNone(guitarpro.parse(str(path)).measureHeaders[0].marker)

    def test_only_the_weak_unconfirmed_digit_gets_an_ocr_marker(self):
        score=Score(measures=[TabMeasure(number=1,confidence=0,beats=[
            TabBeat(duration=2,notes=[TabNote(string=3,fret=7)],ocr_confidence=.2,pitch_evidence='staff'),
            TabBeat(duration=2,notes=[TabNote(string=3,fret=5)],ocr_confidence=.6,pitch_evidence='ocr')])])
        with tempfile.TemporaryDirectory() as folder:
            path=Path(folder)/'draft.gp5';export_diagnostic(score,path);song=guitarpro.parse(str(path))
            beats=song.tracks[0].measures[0].voices[0].beats
            self.assertFalse(beats[0].text)
            self.assertIn('CHECK OCR',beats[1].text)
            self.assertNotIn('LOW CONFIDENCE',song.measureHeaders[0].marker.title)

    def test_missing_and_unreadable_bars_are_marked_and_valid_music_preserved(self):
        score=Score(settings_confirmed=True,measures=[
            TabMeasure(number=1,beats=[TabBeat(duration=1,notes=[TabNote(string=3,fret=7)])]),
            TabMeasure(number=3,beats=[TabBeat(duration=8,unresolved=['pitch'])])])
        before=score.model_dump()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'diagnostic.gp5'
            report=export_diagnostic(score,path)
            song=guitarpro.parse(str(path))
            self.assertEqual([i['number'] for i in report['placeholders']],[2,3])
            self.assertEqual(len(song.measureHeaders),3)
            self.assertEqual(song.tracks[0].measures[0].voices[0].beats[0].notes[0].value,7)
            self.assertTrue(all('UNREADABLE' in song.measureHeaders[i].marker.title for i in (1,2)))
        self.assertEqual(score.model_dump(),before)
        self.assertTrue(any(i['severity']=='error' for i in validate_score(score,require_review=False)))

    def test_duplicate_numbers_do_not_silently_select_one_version(self):
        measure=TabMeasure(number=1,beats=[TabBeat(duration=1)])
        with tempfile.TemporaryDirectory() as directory:
            report=export_diagnostic(Score(measures=[measure,measure]),Path(directory)/'draft.gp5')
            self.assertEqual([i['number'] for i in report['placeholders']],[1])

    def test_invalid_empty_score_is_rejected(self):
        with self.assertRaises(ValueError):export_diagnostic(Score(),Path('unused.gp5'))

    def test_uncertain_pitch_candidate_is_playable_and_marked_without_changing_source(self):
        score=Score(settings_confirmed=True,measures=[TabMeasure(number=1,confidence=.3,
            beats=[TabBeat(duration=1,notes=[TabNote(string=3,fret=7)],unresolved=['pitch'])])])
        before=score.model_dump()
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'draft.gp5';report=export_diagnostic(score,path)
            parsed=guitarpro.parse(str(path))
            self.assertEqual(report['placeholders'],[])
            self.assertEqual(parsed.title,'DIAGNOSTIC DRAFT - CHECK NOTES')
            self.assertEqual(report['uncertain'][0]['beats'],[1])
            self.assertIn('CHECK',parsed.measureHeaders[0].marker.title)
            beat=parsed.tracks[0].measures[0].voices[0].beats[0]
            self.assertEqual(beat.notes[0].value,7)
            self.assertIn('CHECK PITCH',beat.text)
        self.assertEqual(score.model_dump(),before)

    def test_uncertain_duration_is_not_silently_cleared(self):
        score=Score(measures=[TabMeasure(number=1,beats=[TabBeat(duration=1,
            notes=[TabNote(string=3,fret=7)],unresolved=['duration'])])])
        with tempfile.TemporaryDirectory() as directory:
            report=export_diagnostic(score,Path(directory)/'draft.gp5')
            self.assertEqual(report['placeholders'][0]['number'],1)
