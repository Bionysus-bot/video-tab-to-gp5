"""Export a clearly marked inspection copy without changing transcription data."""
from collections import defaultdict
import json

import guitarpro
from guitarpro import models as gp

from app.models.score import TabBeat, TabMeasure
from app.services.score_exporter import export_gp5, validate_score
from app.services.reading_checks import measure_checks,reading_summary


def export_diagnostic(score, destination):
    if not score.measures:
        raise ValueError('尚无识别结果')
    if max(m.number for m in score.measures) > 1000:
        raise ValueError('小节号超过1000，请先修正明显错误的编号')
    original = score.model_dump()
    draft = score.model_copy(deep=True)
    draft.title = 'DIAGNOSTIC - INCOMPLETE SCORE'
    draft.settings_confirmed = True
    draft.measures = []
    groups = defaultdict(list)
    for measure in score.measures:
        groups[measure.number].append(measure)
    report = dict(description='Inspection only. UNREADABLE bars contain placeholder rests, not transcribed music.',
                  settings_confirmed=score.settings_confirmed, placeholders=[],uncertain=[],ocr_warnings=[])
    meter = (score.measures[0].numerator,score.measures[0].denominator)
    for number in range(1,max(groups)+1):
        candidates = groups[number]
        reasons = []
        uncertain_beats = []
        checks=[]
        if len(candidates) == 1:
            measure = candidates[0].model_copy(deep=True)
            checks=measure_checks(measure)
            if reading_summary(measure)['legacy_ocr']:
                report['ocr_warnings'].append(dict(number=number,score=measure.confidence,
                    message='旧数据仅保存最低OCR分数，不能定位拍位或解释为正确率'))
            meter = (measure.numerator,measure.denominator)
            for index,beat in enumerate(measure.beats):
                if 'pitch' in beat.unresolved and beat.notes:
                    # Inspection export retains the actual machine candidate;
                    # only the copy relaxes pitch uncertainty, never duration.
                    beat.unresolved.remove('pitch')
                    uncertain_beats.append(index+1)
            draft.measures.append(measure)
            reasons = [i['message'] for i in validate_score(draft,require_review=False)
                       if i['severity']=='error' and i['measure']==number]
            draft.measures.pop()
        else:
            reasons = ['小节缺失' if not candidates else '小节编号重复，无法确定版本']
        if reasons:
            measure = TabMeasure(number=number,numerator=meter[0],denominator=meter[1],
                                 beats=[TabBeat(duration=meter[1]) for _ in range(meter[0])])
            report['placeholders'].append(dict(number=number,reasons=list(dict.fromkeys(reasons))))
        elif checks:
            report['uncertain'].append(dict(number=number,beats=uncertain_beats,confidence=measure.confidence,checks=checks))
        draft.measures.append(measure)
    if not report['placeholders']:
        draft.title='DIAGNOSTIC DRAFT - CHECK NOTES'
        report['description']='Inspection draft. No placeholder bars; CHECK markers retain uncertain readings.'
    export_gp5(draft,destination,require_review=False)
    song = guitarpro.parse(str(destination))
    for item in report['uncertain']:
        kinds='/'.join(sorted({c['kind'].upper() for c in item['checks']}))
        song.measureHeaders[item['number']-1].marker = gp.Marker(title=f"CHECK {kinds} BAR {item['number']}")
        for check in item['checks']:
            beat=song.tracks[0].measures[item['number']-1].voices[0].beats[check['beat']-1]
            label='CHECK '+check['kind'].upper()+' - MACHINE CANDIDATE'
            beat.text=(beat.text+'; ' if beat.text else '')+label
    for item in report['placeholders']:
        song.measureHeaders[item['number']-1].marker = gp.Marker(title=f"UNREADABLE BAR {item['number']} - PLACEHOLDER ONLY")
    temporary = destination.with_suffix('.marked.gp5')
    guitarpro.write(song,str(temporary),version=(5,1,0))
    parsed = guitarpro.parse(str(temporary))
    if len(parsed.measureHeaders)!=len(draft.measures) or any(
            parsed.measureHeaders[item['number']-1].marker is None for item in report['placeholders']+report['uncertain']):
        raise ValueError('诊断草稿标记回读失败')
    temporary.replace(destination)
    destination.with_suffix('.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    assert score.model_dump() == original
    return report
