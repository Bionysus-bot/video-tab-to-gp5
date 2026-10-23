"""Immutable score revisions. Legacy score files are read-only inputs."""
import hashlib
import json
import re
import threading
import time
import uuid
from pathlib import Path
from fractions import Fraction

from app.models.score import Score
from app.services.reading_checks import measure_checks

LOCK = threading.RLock()


def stamp():
    return time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime())


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def read(path, default=None):
    with LOCK:
        return json.loads(Path(path).read_text(encoding='utf-8-sig')) if Path(path).exists() else default


def write(path, value):
    path = Path(path)
    with LOCK:
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = path.with_name('.' + path.name + '.' + uuid.uuid4().hex + '.tmp')
        try:
            temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
            for attempt in range(6):
                try:
                    temporary.replace(path)
                    break
                except PermissionError:
                    if attempt == 5:
                        raise
                    time.sleep(.01 * 2 ** attempt)
        finally:
            temporary.unlink(missing_ok=True)


def checked_id(value):
    if not re.fullmatch(r'[a-f0-9]{32}', value):
        raise ValueError('无效的版本或任务标识')
    return value


def entities(score, previous=None):
    old = (previous or {}).get('entities', [])
    result = []
    occurrences = {}
    for index, measure in enumerate(score.measures):
        key = (measure.source, measure.number)
        ordinal = occurrences.get(key, 0)
        occurrences[key] = ordinal + 1
        candidates = [m for m in old if (m['source'], m['number']) == key]
        prior = candidates[ordinal] if ordinal < len(candidates) else None
        result.append(dict(id=prior['id'] if prior else uuid.uuid4().hex,
            number=measure.number, source=measure.source, index=index,
            beats=[prior['beats'][i] if prior and i < len(prior['beats']) else uuid.uuid4().hex
                   for i in range(len(measure.beats))]))
    return result


def issues_for(score, mapping):
    issues = []
    def add(kind, message, mi=None, beat=None, severity='warning'):
        entity = mapping[mi] if mi is not None else None
        key = [kind, entity['id'] if entity else None, beat, message]
        issues.append(dict(id=digest(key)[:32], kind=kind, message=message,
            measure_id=entity['id'] if entity else None, measure_index=mi,
            number=entity['number'] if entity else None, beat=beat,
            source=entity['source'] if entity else None, severity=severity, status='open'))
    if not score.settings_confirmed:
        add('settings_unconfirmed', '速度、调弦和拍号使用当前设置，请按需确认。', severity='info')
    previous = None
    for mi, measure in enumerate(score.measures):
        if (previous is not None and measure.number != previous + 1) or (mi == 0 and measure.number != 1):
            add('number_conflict', '编号存在缺口或重复；草稿会标记缺失内容。', mi)
        previous = measure.number
        for item in measure_checks(measure):
            kind = 'ocr_notice' if item['kind'] == 'ocr' else item['kind']
            add(kind, item['message'], mi, item['beat'], 'info' if kind == 'ocr_notice' else 'warning')
        total = sum((Fraction(1, b.duration) * (Fraction(3, 2) if b.dotted else 1) *
                     (Fraction(2, 3) if b.triplet else 1) for b in measure.beats), Fraction())
        if total != Fraction(measure.numerator, measure.denominator):
            add('duration', f'小节总时值 {total}，应为 {measure.numerator}/{measure.denominator}；保留已知拍位。', mi)
        last = {}
        if mi and score.measures[mi-1].beats:
            last = {n.string: n.fret for n in score.measures[mi-1].beats[-1].notes}
        for bi, beat in enumerate(measure.beats, 1):
            for note in beat.notes:
                if note.kind == 'tie' and last.get(note.string) != note.fret:
                    add('tie_or_technique', '延音与前一拍同弦同品未对应。', mi, bi)
            last = {n.string: n.fret for n in beat.notes}
        for text in dict.fromkeys(measure.issues):
            if text.startswith(('拍号暂按', '已由视觉模型复读并通过', '原视频完整画面复读')):
                continue
            kind='number_conflict' if '编号' in text else 'fragment_gap' if any(s in text for s in ('边界', '片段', '缺失', '截断')) else 'tie_or_technique'
            add(kind, text, mi)
    return issues


class RevisionStore:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.root = self.directory / 'v2'

    def state(self):
        return read(self.root / 'project-state.json', dict(active_revision=None, latest_job=None, input_id=None))

    def update(self, **fields):
        with LOCK:
            state = {**self.state(), **fields}
            write(self.root / 'project-state.json', state)
            return state

    def get(self, revision_id):
        value = read(self.root / 'revisions' / checked_id(revision_id) / 'revision.json')
        if value is None:
            raise FileNotFoundError('版本不存在')
        return value

    def list(self):
        return sorted([read(p) for p in (self.root / 'revisions').glob('*/revision.json')],
                      key=lambda v: v['created_at'], reverse=True)

    def create(self, score, *, origin, parent=None, input_id=None, protected=None, manifest=None, activate=False):
        with LOCK:
            prior = self.get(parent) if parent else None
            mapping = entities(score, prior)
            value = dict(id=uuid.uuid4().hex, schema_version=1, parent=parent,
                input_id=input_id or (prior or {}).get('input_id'), origin=origin, created_at=stamp(),
                score=score.model_dump(), entities=mapping, issues=issues_for(score, mapping),
                protected=protected if protected is not None else (prior or {}).get('protected', []),
                manifest=manifest if manifest is not None else (prior or {}).get('manifest', {'rows': []}))
            for row in value['manifest'].get('unread_rows',[]):
                value['issues'].append(dict(id=digest(['unread',row['id']])[:32],kind='fragment_gap',
                    message=row['message'],measure_id=None,measure_index=None,number=None,beat=None,
                    source=row['id'],severity='warning',status='open'))
            write(self.root / 'revisions' / value['id'] / 'revision.json', value)
            if activate:
                self.update(active_revision=value['id'])
            return value

    def import_legacy(self):
        with LOCK:
            if not self.state()['active_revision']:
                legacy = read(self.directory / 'score.json')
                if legacy and legacy.get('measures'):
                    score = Score.model_validate(legacy)
                    revision = self.create(score, origin='legacy-import',
                        manifest=read(self.directory / 'manifest.json', {'rows': []}), activate=True)
                    # Old saves have no field-level provenance: protect all measures.
                    revision['protected'] = [m['id'] for m in revision['entities']]
                    write(self.root / 'revisions' / revision['id'] / 'revision.json', revision)
            seen=set(self.state().get('imported_recoveries',[]))
            for path in (self.directory/'video-recovery').glob('*/recognized-score.json'):
                key=str(path.relative_to(self.directory))
                if key in seen:continue
                recovered=Score.model_validate(read(path))
                imported=self.create(recovered,origin='video-recovery-import',
                    manifest=read(self.directory/'manifest.json',{'rows':[]}),
                    activate=not self.state()['active_revision'])
                imported['protected']=[m['id'] for m in imported['entities']]
                write(self.root/'revisions'/imported['id']/'revision.json',imported)
                seen.add(key)
            if sorted(seen)!=self.state().get('imported_recoveries',[]):
                self.update(imported_recoveries=sorted(seen))

    def save_edit(self, revision_id, score, expected):
        with LOCK:
            if self.state()['active_revision'] != expected or expected != revision_id:
                raise ValueError('结果已更新，请保留当前编辑并重新加载版本。')
            old = self.get(revision_id)
            if len(score.measures) != len(old['score']['measures']):
                raise ValueError('此入口仅编辑已有小节，不允许增删小节。')
            protected = set(old['protected'])
            patches = []
            for i, (before, after) in enumerate(zip(old['score']['measures'], score.model_dump()['measures'])):
                if (before['number'], before['source']) != (after['number'], after['source']):
                    raise ValueError('编辑不能改变来源或编号；请使用独立的结构修复。')
                if before != after:
                    protected.add(old['entities'][i]['id'])
                    patches.append(dict(measure_id=old['entities'][i]['id'], before=before, after=after))
            revision = self.create(score, origin='manual', parent=revision_id,
                                   protected=sorted(protected), activate=True)
            write(self.root / 'revisions' / revision['id'] / 'patches.json', patches)
            return revision

    def activate(self, revision_id, expected):
        with LOCK:
            self.get(revision_id)
            if self.state()['active_revision'] != expected:
                raise ValueError('活动版本已改变，请刷新后重试。')
            self.update(active_revision=revision_id)
