export default function BassStringsSelect({ count, onChange, disabled = false }: {
    count: number; onChange: (count: number) => void; disabled?: boolean;
}) {
    return <label className="floating-field bass-choice"><span className="field-label">乐器</span>
        <select aria-label="贝斯弦数" value={count} disabled={disabled} onChange={e => onChange(Number(e.target.value))}>
            <option value={4}>四弦贝斯</option><option value={5}>五弦贝斯</option>
            {![4, 5].includes(count) && <option value={count} disabled>当前乐器（{count} 弦）</option>}
        </select></label>;
}
