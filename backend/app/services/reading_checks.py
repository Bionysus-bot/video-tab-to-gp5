"""Evidence labels, not calibrated probabilities of musical correctness."""

def measure_checks(measure):
    checks=[]
    for index,beat in enumerate(measure.beats,1):
        for kind in beat.unresolved:
            checks.append(dict(beat=index,kind=kind,message='音高未确定' if kind=='pitch' else '时值未确定'))
        if (not measure.reviewed and beat.ocr_confidence is not None and beat.ocr_confidence<.85
                and beat.pitch_evidence!='staff' and 'pitch' not in beat.unresolved and beat.notes):
            checks.append(dict(beat=index,kind='ocr',message='数字读数偏弱，尚无五线谱音高佐证'))
    return checks


def reading_summary(measure):
    return dict(number=measure.number,checks=measure_checks(measure),
        legacy_ocr=not measure.reviewed and measure.confidence<.85 and all(b.ocr_confidence is None for b in measure.beats),
        staff_supported=[i for i,b in enumerate(measure.beats,1) if b.pitch_evidence=='staff'])
