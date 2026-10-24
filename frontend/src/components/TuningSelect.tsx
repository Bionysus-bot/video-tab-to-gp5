// Stored from highest string to lowest; musicians read the preview low to high.
export const STANDARD_TUNING = [43, 38, 33, 28];
const presets = [
    { id: 'standard', name: '标准调弦', notes: 'E · A · D · G', values: STANDARD_TUNING },
    { id: 'half-down', name: '全降半音', notes: 'E♭ · A♭ · D♭ · G♭', values: [42, 37, 32, 27] },
    { id: 'whole-down', name: '全降全音', notes: 'D · G · C · F', values: [41, 36, 31, 26] },
    { id: 'drop-d', name: 'Drop D', notes: 'D · A · D · G', values: [43, 38, 33, 26] },
    { id: 'drop-c', name: 'Drop C', notes: 'C · G · C · F', values: [41, 36, 31, 24] },
];
export default function TuningSelect({ value, onChange, disabled = false }: {
    value: number[]; onChange: (value: number[]) => void; disabled?: boolean;
}) {
    const preset = presets.find(p => p.values.length === value.length && p.values.every((v, i) => v === value[i]));
    const noteNames = ['C', 'D♭', 'D', 'E♭', 'E', 'F', 'G♭', 'G', 'A♭', 'A', 'B♭', 'B'];
    const notes = preset?.notes || [...value].reverse().map(v => noteNames[((v % 12) + 12) % 12]).join(' · ');
    return <div className="tuning-choice"><label className="floating-field"><span className="field-label">调弦方案</span>
        <select aria-label="调弦方案" value={preset?.id || 'custom'} disabled={disabled} onChange={e => {
            const chosen = presets.find(p => p.id === e.target.value);
            if (chosen) onChange([...chosen.values]);
        }}>
            {!preset && <option value="custom" disabled>当前调弦（自定义）</option>}
            {presets.map(p => <option key={p.id} value={p.id}>{p.name}</option>)}
        </select></label><p className="tuning-notes"><span>低弦 → 高弦</span><strong>{notes}</strong></p></div>;
}
