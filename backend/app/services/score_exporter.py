from fractions import Fraction
from pathlib import Path

import guitarpro
from guitarpro import models as gp

from app.models.score import Score


def validate_score(score: Score, *, require_review: bool = True) -> list[dict]:
    issues = []

    def add(message, measure=None, severity="error"):
        issues.append(dict(message=message, measure=measure, severity=severity))

    if not score.settings_confirmed:
        add("请确认速度、乐器和调弦；默认值不是从图片中识别的。")
    try:
        score.title.encode("cp1252")
    except UnicodeEncodeError:
        add("GP5 的标题请使用英文或西欧字符；中文标题可在 Guitar Pro 内另行修改。")
    if not score.measures:
        add("尚无音符小节，不能导出空白谱。")
    if any(not 0 <= n <= 127 for n in score.tuning):
        add("调弦 MIDI 音高必须在 0–127 之间。")
    if score.tuning != sorted(score.tuning, reverse=True) or len(set(score.tuning)) != len(score.tuning):
        add("调弦需从最高音弦到最低音弦排列，且不能重复。")
    previous_number = None
    last_notes = {}
    for measure in score.measures:
        n = measure.number
        if previous_number is not None and n != previous_number + 1:
            add("小节编号不连续或重复，请检查遗漏与重叠。", n)
        previous_number = n
        if require_review and not measure.reviewed:
            add("此小节尚未人工核对。", n)
        if not measure.beats:
            add("小节没有节拍，整小节休止也需要填写时值。", n)
        total = Fraction(0)
        for beat in measure.beats:
            if beat.unresolved:
                add("存在未识别的音高或时值，请补全该拍位后再导出。", n)
            total += Fraction(1, beat.duration) * (Fraction(3, 2) if beat.dotted else 1) * (Fraction(2, 3) if beat.triplet else 1)
            seen = set()
            current = {}
            for note in beat.notes:
                if note.string > len(score.tuning):
                    add("音符弦号超过配置的弦数。", n)
                if note.string in seen:
                    add("同一拍内同一弦上出现多个音符。", n)
                seen.add(note.string)
                if note.kind == "tie" and last_notes.get(note.string) != note.fret:
                    add("延音音符找不到前一拍同弦同品的音符。", n)
                if note.grace and note.kind != "normal":
                    add("倚音只能附在普通音上，请检查延音或闷音的标记。", n)
                if note.legato_slide and not note.slide:
                    add("连奏滑音需要同时启用滑音。", n)
                if note.kind != "dead":
                    current[note.string] = note.fret
            last_notes = current
        expected = Fraction(measure.numerator, measure.denominator)
        if total != expected:
            add(f"时值不完整：合计 {total} 全音符，应为 {expected}（{measure.numerator}/{measure.denominator}）。弱起可使用实际拍号。", n)
        if measure.confidence < 0.85:
            add("识别置信度偏低，请对照原图。", n, "warning")
        for text in measure.issues:
            add(text, n, "warning")
    return issues


def export_gp5(score: Score, destination: Path, *, require_review: bool = True) -> Path:
    errors = [i for i in validate_score(score,require_review=require_review) if i["severity"] == "error"]
    if errors:
        raise ValueError("；".join(i["message"] for i in errors[:5]))
    song = gp.Song(title=score.title, tempo=score.tempo)
    song.measureHeaders.clear()
    song.tracks.clear()
    track = gp.Track(song, name="Bass" if score.instrument == "bass" else "Guitar")
    track.strings = [gp.GuitarString(i + 1, value) for i, value in enumerate(score.tuning)]
    track.channel.instrument = 33 if score.instrument == "bass" else 24
    track.fretCount = 36
    track.measures.clear()
    song.tracks.append(track)
    start = gp.Duration.quarterTime
    for index, source in enumerate(score.measures):
        header = gp.MeasureHeader(number=index + 1, start=start)
        header.timeSignature = gp.TimeSignature(source.numerator, gp.Duration(value=source.denominator))
        song.measureHeaders.append(header)
        measure = gp.Measure(track, header)
        track.measures.append(measure)
        voice = measure.voices[0]
        beat_start = start
        for item in source.beats:
            duration = gp.Duration(value=item.duration, isDotted=item.dotted)
            if item.triplet:
                duration.tuplet = gp.Tuplet(3, 2)
            beat = gp.Beat(voice, duration=duration, start=beat_start,
                           status=gp.BeatStatus.normal if item.notes else gp.BeatStatus.rest)
            voice.beats.append(beat)
            for item_note in item.notes:
                note = gp.Note(beat, string=item_note.string, value=item_note.fret,
                               type=getattr(gp.NoteType, item_note.kind))
                if item_note.slide:
                    note.effect.slides = [gp.SlideType.legatoSlideTo if item_note.legato_slide else gp.SlideType.shiftSlideTo]
                if item_note.slide_out:
                    note.effect.slides.append(gp.SlideType.outDownwards if item_note.slide_out=='down' else gp.SlideType.outUpwards)
                note.effect.hammer = item_note.hammer
                note.effect.staccato = item_note.staccato
                if item_note.grace:
                    note.effect.grace = gp.GraceEffect(fret=item_note.grace.fret,
                                                       duration=item_note.grace.duration,
                                                       isOnBeat=item_note.grace.on_beat)
                beat.notes.append(note)
            beat_start += duration.time
        start += header.length
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_suffix(".tmp.gp5")
    guitarpro.write(song, str(temporary), version=(5, 1, 0))
    # Read the real binary back before exposing it as a downloadable result.
    parsed = guitarpro.parse(str(temporary))
    if len(parsed.tracks[0].measures) != len(score.measures):
        raise ValueError("GP5 回读验证失败")
    temporary.replace(destination)
    return destination
