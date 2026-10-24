"""Export known beats even in incomplete bars, explicitly marking provisional timing."""
from fractions import Fraction
import json
import guitarpro
from guitarpro import models as gp
from app.models.score import Score
from app.services.diagnostic_export import export_diagnostic
from app.services.score_exporter import export_gp5


def export_partial(score, destination):
    report = export_diagnostic(score, destination)
    song = guitarpro.parse(str(destination))
    report['partial_bars'] = []
    retained = []
    for placeholder in report['placeholders']:
        number = placeholder['number']
        measures = [m for m in score.measures if m.number == number]
        if len(measures) != 1 or not measures[0].beats or not any(b.notes for b in measures[0].beats):
            retained.append(placeholder)
            continue
        measure = measures[0].model_copy(deep=True)
        total = sum((Fraction(1,b.duration)*(Fraction(3,2) if b.dotted else 1)*
                     (Fraction(2,3) if b.triplet else 1) for b in measure.beats), Fraction())
        if total.denominator not in (1,2,4,8,16,32) or not 1 <= total.numerator <= 32:
            retained.append(placeholder)
            continue
        # A temporary valid meter encodes actual candidate beats, never invents a rest.
        measure.numerator, measure.denominator = total.numerator, total.denominator
        for beat in measure.beats:
            beat.unresolved = []
            for note in beat.notes:
                if note.kind == 'tie':
                    note.kind = 'normal'
        sample = Score(title='Candidate', instrument=score.instrument, tempo=score.tempo,
                       tuning=score.tuning, settings_confirmed=True, measures=[measure])
        temporary = destination.with_name(f'.partial-{number}.gp5')
        try:
            export_gp5(sample, temporary, require_review=False)
            parsed = guitarpro.parse(str(temporary))
            target = song.tracks[0].measures[number-1]
            voice = target.voices[0]
            voice.beats.clear()
            for index,beat in enumerate(parsed.tracks[0].measures[0].voices[0].beats):
                beat.voice = voice
                beat.start += target.start - parsed.tracks[0].measures[0].start
                missing = not measures[0].beats[index].notes and measures[0].beats[index].unresolved
                beat.text = 'MISSING NOTE - PLACEHOLDER ONLY' if missing else 'CHECK - CANDIDATE TIMING / PITCH'
                voice.beats.append(beat)
            target.header.marker = gp.Marker(title=f'PARTIAL BAR {number} - CHECK TIMING')
            report['partial_bars'].append(placeholder)
        except ValueError:
            retained.append(placeholder)
        finally:
            temporary.unlink(missing_ok=True)
    report['placeholders'] = retained
    marked = destination.with_suffix('.verified.gp5')
    guitarpro.write(song, str(marked), version=(5,1,0))
    parsed = guitarpro.parse(str(marked))
    if len(parsed.measureHeaders) != len(song.measureHeaders):
        raise ValueError('草稿回读验证失败')
    marked.replace(destination)
    destination.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    return report
