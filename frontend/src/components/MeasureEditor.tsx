import type { Measure } from '../services/workspace';
export default function MeasureEditor({ measure, onChange, stringCount = 4 }: {
    measure: Measure;
    stringCount?: number;
    onChange: (value: Measure) => void;
}) {
    const change = (bi: number, update: (m: Measure) => void) => { const next = structuredClone(measure); update(next); next.reviewed = false; onChange(next); void bi; };
    return <section className="measure-editor" aria-label={`第 ${measure.number} 小节编辑器`}>
    <div className="editor-heading"><h3>拍位与音符</h3><span>{measure.beats.length} 个拍位</span></div>
    <div className="beat-table"><table><thead><tr><th>拍位</th><th>时值</th><th>品位 / 弦</th><th>演奏</th><th>疑点</th></tr></thead><tbody>
      {measure.beats.map((beat, bi) => <tr key={bi}><td className="beat-number">{bi + 1}</td><td>
        <select aria-label={`第${bi + 1}拍时值`} value={beat.duration} onChange={e => change(bi, m => { m.beats[bi].duration = Number(e.target.value); m.beats[bi].unresolved = beat.unresolved.filter(v => v !== 'duration'); })}>{[1, 2, 4, 8, 16, 32, 64].map(v => <option key={v} value={v}>{v === 1 ? '全音符' : `${v} 分`}</option>)}</select>
        <div className="inline-options"><label><input type="checkbox" checked={beat.dotted} onChange={e => change(bi, m => { m.beats[bi].dotted = e.target.checked; })}/>附点</label><label><input type="checkbox" checked={beat.triplet} onChange={e => change(bi, m => { m.beats[bi].triplet = e.target.checked; })}/>三连</label></div>
      </td><td>{beat.notes.length ? beat.notes.map((note, ni) => <div className="note-fields" key={ni}>
        <input aria-label={`第${bi + 1}拍第${ni + 1}音品位`} type="number" min={0} max={36} value={note.fret} onChange={e => change(bi, m => { m.beats[bi].notes[ni].fret = Number(e.target.value); m.beats[bi].unresolved = beat.unresolved.filter(v => v !== 'pitch'); m.beats[bi].ocr_confidence = null; m.beats[bi].pitch_evidence = null; })}/>
        <select aria-label={`第${bi + 1}拍第${ni + 1}音弦号`} value={note.string} onChange={e => change(bi, m => { m.beats[bi].notes[ni].string = Number(e.target.value); })}>{Array.from({ length: stringCount }, (_, i) => i + 1).map(v => <option key={v} value={v}>{v} 弦</option>)}</select>
      </div>) : <span className="muted">{beat.unresolved.includes('pitch') ? <>音符缺失 <button className="text-button" onClick={()=>change(bi,m=>{m.beats[bi].unresolved=m.beats[bi].unresolved.filter(v=>v!=='pitch')})}>确认为休止</button></> : '休止'}</span>}</td><td>{beat.notes.map((note, ni) => <div key={ni} className="note-fields"><select aria-label={`第${bi + 1}拍第${ni + 1}音演奏法`} value={note.kind} onChange={e => change(bi, m => { m.beats[bi].notes[ni].kind = e.target.value as typeof note.kind; })}><option value="normal">普通音</option><option value="tie">延音</option><option value="dead">闷音</option></select><label><input type="checkbox" checked={!!note.slide} onChange={e => change(bi, m => { m.beats[bi].notes[ni].slide = e.target.checked; })}/>滑音</label></div>)}</td>
      <td><span className={beat.unresolved.length ? 'warning-text' : 'muted'}>{beat.unresolved.map(v => v === 'pitch' ? '音高' : '时值').join('、') || '—'}</span></td></tr>)}
    </tbody></table></div>
    <details className="advanced-json"><summary>高级编辑</summary><p className="muted">应用后需保存。</p><JsonEditor value={measure} onChange={onChange}/></details>
  </section>;
}
import { useEffect, useState } from 'react';
function JsonEditor({ value, onChange }: {
    value: Measure;
    onChange: (v: Measure) => void;
}) {
    const [text, setText] = useState(JSON.stringify(value, null, 2));
    const [error, setError] = useState('');
    useEffect(() => { setText(JSON.stringify(value, null, 2)); setError(''); }, [value]);
    return <><textarea aria-label="完整小节 JSON" value={text} onChange={e => setText(e.target.value)}/><button className="button secondary" onClick={() => { try {
        const next = JSON.parse(text);
        if (!Array.isArray(next.beats) || next.number !== value.number || next.source !== value.source)
            throw new Error('请保留小节编号、来源和拍位结构');
        onChange(next);
        setError('');
    }
    catch (e) {
        setError(String(e));
    } }}>应用数据</button>{error && <p role="alert">{error}</p>}</>;
}
