import { useEffect, useState } from 'react'

type Note = { string: number; fret: number; kind?: string; slide?: boolean; legato_slide?: boolean; slide_out?: 'down' | 'up' | null; hammer?: boolean; staccato?: boolean; grace?: { fret: number; duration: number; on_beat: boolean } | null }
type Beat = { duration: number; dotted?: boolean; triplet?: boolean; unresolved?: ('pitch' | 'duration')[]; notes: Note[] }
type Measure = { number: number; numerator: number; denominator: number; confidence: number; reviewed: boolean; source: string; issues: string[]; beats: Beat[] }
type Score = { title: string; instrument: 'bass' | 'guitar'; tempo: number; tuning: number[]; settings_confirmed: boolean; measures: Measure[] }
type Row = { id: string; source: string; strings: number; excluded?: boolean; exclude_reason?: string }
type Issue = { message: string; measure: number | null; severity: string }
type Data = { score: Score; validation: Issue[]; draft_validation?: Issue[]; manifest: { rows: Row[]; rejected: { source: string; reason: string }[] }; task: { status: string; current?: number; total?: number; log: string[] } }

async function call(url: string, options?: RequestInit) {
  const response = await fetch(url, options)
  if (!response.ok) {
    const text = await response.text()
    try { throw new Error(JSON.parse(text).detail || text) } catch (e) { if (e instanceof SyntaxError) throw new Error(text); throw e }
  }
  return response.json()
}

export default function ScorePanel({ projectId }: { projectId: string }) {
  const base = `/api/projects/${projectId}/score`
  const [data, setData] = useState<Data | null>(null)
  const [draft, setDraft] = useState('')
  const [models, setModels] = useState<{ name: string; vision: boolean }[]>([])
  const [model, setModel] = useState('')
  const [provider, setProvider] = useState('ollama')
  const [strategy, setStrategy] = useState('hybrid')
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:11434')
  const [limit, setLimit] = useState(3)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState(0)
  const [dirty, setDirty] = useState(false)
  const active = busy || data?.task.status === 'recognizing' || data?.task.status === 'preparing'

  async function load(updateDraft = true) {
    const next = await call(base) as Data
    setData(next)
    if (updateDraft) { setDraft(JSON.stringify(next.score, null, 2)); setDirty(false) }
    return next
  }
  async function detect() {
    const result = await call('/api/score/models')
    setModels(result.models)
    const vision = result.models.find((m: { vision: boolean; name: string }) => m.vision && m.name.includes('instruct')) || result.models.find((m: { vision: boolean }) => m.vision)
    if (vision) setModel(vision.name)
    setNotice(result.error || (vision ? '已检测到支持图片的本地模型' : '没有检测到视觉模型，请先在 Ollama 中安装'))
  }
  useEffect(() => { load().catch(e => setError(e.message)); detect().catch(e => setError(e.message)) }, [projectId])
  useEffect(() => {
    if (data?.task.status !== 'recognizing' && data?.task.status !== 'preparing') return
    const timer = setInterval(() => { load().catch(e => setError(e.message)) }, 2000)
    return () => clearInterval(timer)
  }, [data?.task.status, projectId])

  async function perform(action: () => Promise<void>) {
    setBusy(true); setError(''); setNotice('')
    try { await action() } catch (e) { setError(e instanceof Error ? e.message : String(e)) } finally { setBusy(false) }
  }
  async function save(value?: Score) {
    const score = value || JSON.parse(draft)
    await call(base, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(score) })
    await load()
    return score
  }
  function changeSettings(update: Partial<Score>) {
    try {
      const next = { ...JSON.parse(draft), ...update }
      setDraft(JSON.stringify(next, null, 2)); setDirty(true); setError('')
    } catch { setError('请先修正下方乐谱数据的 JSON 格式') }
  }
  function editMeasure(index: number, update: (m: Measure) => void) {
    try {
      const next = JSON.parse(draft) as Score
      update(next.measures[index])
      setDraft(JSON.stringify(next, null, 2)); setDirty(true)
    } catch { setError('请先修正高级数据的格式') }
  }
  function editBeat(mi: number, bi: number, resolved: 'pitch' | 'duration' | null, update: (beat: Beat) => void) {
    editMeasure(mi, measure => {
      const beat = measure.beats[bi]
      update(beat)
      if (resolved) beat.unresolved = (beat.unresolved || []).filter(item => item !== resolved)
      measure.reviewed = false
    })
  }
  let editing: Score | null = null
  try { editing = JSON.parse(draft) } catch { /* Keep invalid draft editable. */ }
  const row = data?.manifest.rows[selected]
  return <div className="result-preview score-panel">
    <h3>转换为 Guitar Pro 谱</h3>
    <p>先整理谱面，再识别与核对，最后下载 .gp5。第一版建议先试前 3 行。</p>
    <p>已有核对标记的谱行会自动保留。需要重新识别该行时，请先取消该行所有小节的核对标记。</p>
    <div className="result-actions">
      <button className="btn" disabled={active} onClick={() => perform(async () => { await call(base + '/prepare', { method: 'POST' }); setSelected(0); await load() })}>读取当前视频截图</button>
      <label className="btn">导入 PDF<input type="file" accept="application/pdf,.pdf" disabled={active} style={{ display: 'none' }} onChange={e => {
        const file = e.target.files?.[0]; e.target.value = ''; if (!file) return
        perform(async () => { const form = new FormData(); form.append('file', file); await call(base + '/pdf', { method: 'POST', body: form }); setSelected(0); await load() })
      }} /></label>
    </div>
    {!!data?.manifest.rows.length && <>
      <p>检测到 {data.manifest.rows.length} 行谱面。请检查过滤结果和弦线识别是否正确。</p>
      <select aria-label="原始谱面行" value={selected} onChange={e => setSelected(Number(e.target.value))}>
        {data.manifest.rows.map((r, i) => <option key={r.id} value={i}>第 {i + 1} 行 · {r.source} · {r.strings} 根弦{r.excluded ? ' · 已跳过' : ''}</option>)}
      </select>
      {row && <a href={`${base}/rows/${row.id}`} target="_blank" rel="noreferrer"><img src={`${base}/rows/${row.id}`} alt={`谱面 ${row.id}`} style={{ width: '100%', background: 'white', marginTop: 8 }} /></a>}
      {row && <>
        {row.excluded && <p>此行已跳过：{row.exclude_reason}。原图保留。</p>}
        <button className="btn" disabled={active} onClick={() => perform(async () => {
          await save()
          await call(`${base}/rows/${row.id}/exclude`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ excluded: !row.excluded, reason: '手动标记为重复或无有效谱面' }) })
          await load()
        })}>{row.excluded ? '恢复此行，供下次识谱' : '跳过此行（重复或片尾）'}</button>
      </>}
    </>}
    {!!data?.manifest.rejected.length && <details><summary>待复查的过滤画面（{data.manifest.rejected.length}）</summary>{data.manifest.rejected.map((r, i) => <p key={i}>{r.source}：{r.reason}</p>)}</details>}
    <div className="score-fields">
      <label>识别方式<select disabled={active} value={strategy} onChange={e => setStrategy(e.target.value)}><option value="hybrid">本地图像识谱优先（推荐当前谱面）</option><option value="vision">只使用视觉模型</option></select></label>
      <label>识谱服务<select disabled={active} value={provider} onChange={e => { setProvider(e.target.value); setBaseUrl(e.target.value === 'ollama' ? 'http://127.0.0.1:11434' : '') }}><option value="ollama">本地 Ollama</option><option value="compatible">OpenAI 兼容接口</option></select></label>
      <label>接口地址<input disabled={active} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="兼容接口填写含 /v1 的地址" /></label>
      <label>视觉模型<input disabled={active} value={model} list="vision-models" onChange={e => setModel(e.target.value)} placeholder="选择或输入模型名" /><datalist id="vision-models">{models.filter(m => m.vision).map(m => <option key={m.name} value={m.name} />)}</datalist></label>
      <button className="btn" disabled={active} onClick={() => perform(detect)}>检测本地模型</button>
      <label>本次识别前几行<input type="number" min={1} max={200} disabled={active} value={limit} onChange={e => setLimit(Number(e.target.value))} /></label>
    </div>
    {strategy === 'hybrid' && <p>优先读取弦线、品位和符尾；不支持的谱面再尝试所选模型。编号按画面顺序暂定，拍号暂按 4/4，需对照原图核对。</p>}
    {provider === 'compatible' && <p>此模式会将谱面发送到所填地址；密钥由本机环境变量 TAB_VISION_API_KEY 提供。</p>}
    <button className="btn btn-primary" disabled={active || (strategy === 'vision' && !model) || !data?.manifest.rows.length} onClick={() => perform(async () => {
      await save()
      await call(base + '/recognize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider, strategy, base_url: baseUrl, model, max_rows: limit }) })
      await load()
    })}>{data?.task.status === 'recognizing' ? `识谱中 ${data.task.current || 0}/${data.task.total || 0}` : '开始识谱'}</button>
    {data && <>
      <div className="score-fields">
        <label>乐器<select disabled={active} value={editing?.instrument || 'bass'} onChange={e => changeSettings({ instrument: e.target.value as 'bass' | 'guitar', tuning: e.target.value === 'bass' ? [43, 38, 33, 28] : [64, 59, 55, 50, 45, 40], settings_confirmed: false })}><option value="bass">贝斯（默认四弦）</option><option value="guitar">吉他（默认六弦）</option></select></label>
        <label>速度 BPM<input disabled={active} type="number" min={20} max={300} value={editing?.tempo || 120} onChange={e => changeSettings({ tempo: Number(e.target.value), settings_confirmed: false })} /></label>
      </div>
      <p>默认调弦为标准调弦，速度 120 是占位值。特殊调弦可在下方数据中修改，按最高音弦到最低音弦填写 MIDI 音高。</p>
      <label><input disabled={active} type="checkbox" checked={editing?.settings_confirmed || false} onChange={e => changeSettings({ settings_confirmed: e.target.checked })} />我已确认乐器、速度和调弦</label>
      <h4>校对乐谱（已保存 {data.score.measures.length} 小节）</h4>
      {editing?.measures.map((m, mi) => <details key={mi} className="score-measure">
        <summary>第 {m.number} 小节 · {m.numerator}/{m.denominator} · {m.reviewed ? '已核对' : '待核对'} · 置信度 {Math.round(m.confidence * 100)}%</summary>
        <button className="btn" disabled={active} onClick={() => { const index = data.manifest.rows.findIndex(r => r.id === m.source); if (index >= 0) setSelected(index) }}>查看对应原图</button>
        <label>小节编号<input type="number" disabled={active} value={m.number} onChange={e => editMeasure(mi, x => { x.number = Number(e.target.value); x.reviewed = false })} /></label>
        <label>拍号<input type="number" disabled={active} value={m.numerator} onChange={e => editMeasure(mi, x => { x.numerator = Number(e.target.value); x.reviewed = false })} /> / <select disabled={active} value={m.denominator} onChange={e => editMeasure(mi, x => { x.denominator = Number(e.target.value); x.reviewed = false })}>{[1, 2, 4, 8, 16, 32].map(n => <option key={n}>{n}</option>)}</select></label>
        {m.issues.map((issue, i) => <p key={i}>{issue}</p>)}
        {m.beats.map((b, bi) => <div key={bi} className="score-beat">
          <span>第 {bi + 1} 拍位 </span><select aria-label="音符时值" disabled={active} value={b.duration} onChange={e => editBeat(mi, bi, 'duration', beat => { beat.duration = Number(e.target.value) })}>{[1, 2, 4, 8, 16, 32, 64].map(n => <option key={n} value={n}>{n === 1 ? '全音符' : `${n} 分音符`}</option>)}</select>
          <label><input type="checkbox" disabled={active} checked={b.dotted || false} onChange={e => editBeat(mi, bi, 'duration', beat => { beat.dotted = e.target.checked })} />附点</label>
          <label><input type="checkbox" disabled={active} checked={b.triplet || false} onChange={e => editBeat(mi, bi, 'duration', beat => { beat.triplet = e.target.checked })} />三连音</label>
          {!!b.unresolved?.length && <p role="alert">此拍位的{b.unresolved.includes('pitch') ? '音高' : ''}{b.unresolved.includes('duration') ? '时值' : ''}未识别，需补全才能导出。</p>}
          {!b.notes.length && <span>{b.unresolved?.includes('pitch') ? '音符待补全' : '休止'}</span>}
          {b.notes.map((n, ni) => <div key={ni}>
            <label>弦<input type="number" disabled={active} min={1} max={editing?.tuning.length} value={n.string} onChange={e => editBeat(mi, bi, 'pitch', beat => { beat.notes[ni].string = Number(e.target.value) })} /></label>
            <label>品<input type="number" disabled={active} min={0} max={36} value={n.fret} onChange={e => editBeat(mi, bi, 'pitch', beat => { beat.notes[ni].fret = Number(e.target.value) })} /></label>
            <select aria-label="演奏方式" disabled={active} value={n.kind || 'normal'} onChange={e => editBeat(mi, bi, 'pitch', beat => { beat.notes[ni].kind = e.target.value })}><option value="normal">普通音</option><option value="tie">延音</option><option value="dead">闷音 X</option></select>
            <label><input type="checkbox" disabled={active} checked={n.slide || false} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].slide = e.target.checked; if (!e.target.checked) beat.notes[ni].legato_slide = false })} />滑向下一音</label>
            {n.slide && <label><input type="checkbox" disabled={active} checked={n.legato_slide || false} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].legato_slide = e.target.checked })} />连奏滑音</label>}
            <label>滑出<select disabled={active} value={n.slide_out || ''} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].slide_out = (e.target.value || null) as Note['slide_out'] })}><option value="">无</option><option value="down">向下滑出</option><option value="up">向上滑出</option></select></label>
            <label><input type="checkbox" disabled={active} checked={n.hammer || false} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].hammer = e.target.checked })} />击勾弦</label>
            <label><input type="checkbox" disabled={active} checked={n.staccato || false} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].staccato = e.target.checked })} />断奏</label>
            <label><input type="checkbox" disabled={active || (n.kind || 'normal') !== 'normal'} checked={!!n.grace} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].grace = e.target.checked ? { fret: 0, duration: 32, on_beat: false } : null })} />倚音</label>
            {n.grace && <div>
              <label>倚音品位<input type="number" disabled={active} min={0} max={36} value={n.grace.fret} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].grace!.fret = Number(e.target.value) })} /></label>
              <label>倚音时长<select disabled={active} value={n.grace.duration} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].grace!.duration = Number(e.target.value) })}>{[16,32,64].map(value => <option key={value} value={value}>{value} 分音符</option>)}</select></label>
              <label><input type="checkbox" disabled={active} checked={n.grace.on_beat} onChange={e => editBeat(mi, bi, null, beat => { beat.notes[ni].grace!.on_beat = e.target.checked })} />在拍上演奏倚音</label>
            </div>}
            <button className="btn" disabled={active} onClick={() => editBeat(mi, bi, 'pitch', beat => { beat.notes.splice(ni, 1) })}>删音</button>
          </div>)}
          <button className="btn" disabled={active} onClick={() => editBeat(mi, bi, 'pitch', beat => { beat.notes.push({ string: 1, fret: 0, kind: 'normal' }) })}>加音</button>
          <button className="btn" disabled={active} onClick={() => editMeasure(mi, x => { x.beats.splice(bi, 1); x.reviewed = false })}>删拍位</button>
        </div>)}
        <button className="btn" disabled={active} onClick={() => editMeasure(mi, x => { x.beats.push({ duration: 4, notes: [] }); x.reviewed = false })}>添加拍位</button>
        <label><input type="checkbox" disabled={active} checked={m.reviewed} onChange={e => editMeasure(mi, x => { x.reviewed = e.target.checked })} />我已对照原图核对本小节及提示</label>
        <button className="btn" disabled={active} onClick={() => changeSettings({ measures: editing!.measures.filter((_, i) => i !== mi) })}>删除此小节</button>
      </details>)}
      <p>时值：4=四分音符、8=八分音符；notes=[] 表示休止。弦号 1 是图中最上方的弦。修改数据后先保存并校验。</p>
      <details><summary>高级：完整乐谱数据（可修改滑音等属性）</summary><textarea aria-label="乐谱数据" disabled={active} value={draft} spellCheck={false} onChange={e => { setDraft(e.target.value); setDirty(true) }} style={{ width: '100%', minHeight: 240, fontFamily: 'monospace', boxSizing: 'border-box' }} /></details>
      <div className="result-actions">
        <button className="btn" disabled={active} onClick={() => perform(async () => { await save(); setNotice('已保存并校验') })}>保存并校验</button>
        <button className="btn" disabled={active || dirty || !data.score.measures.length || (data.draft_validation || data.validation).some(v => v.severity === 'error')} onClick={() => perform(async () => {
          await call(base + '/export-draft', { method: 'POST' }); setNotice('已生成尚未全部核对的草稿，请在 Guitar Pro 中检查。'); window.location.assign(base + '/download-draft')
        })}>下载 GP5 草稿（供核对）</button>
        <button className="btn" disabled={active || !editing?.measures.length} onClick={() => perform(async () => {
          const score = JSON.parse(draft) as Score
          score.measures = score.measures.map(m => ({ ...m, reviewed: true }))
          await save(score); setNotice('已标记人工核对；仍须修正时值等错误才能导出')
        })}>已逐小节核对，标记全部小节</button>
        <button className="btn btn-primary" disabled={active || dirty || !data.score.measures.length || data.validation.some(v => v.severity === 'error')} onClick={() => perform(async () => {
          await call(base + '/export', { method: 'POST' }); window.location.assign(base + '/download')
        })}>下载已核对 GP5</button>
      </div>
      <p>音符和时值校验通过后，可以先下载草稿到 Guitar Pro 核对；未识别拍位和时值错误仍需修正。</p>
      {dirty && <p>有未保存的修改，请保存后导出。</p>}
      <div role="status">{[...data.validation].sort((a, b) => Number(b.severity === 'error') - Number(a.severity === 'error')).slice(0, 30).map((v, i) => <p key={i} style={{ color: v.severity === 'error' ? '#c44' : '#a76b00' }}>{v.measure ? `第 ${v.measure} 小节：` : ''}{v.message}</p>)}</div>
      <details open={data.task.status === 'failed'}><summary>识谱日志 · {data.task.status}</summary>{data.task.log.map((line, i) => <p key={i}>{line}</p>)}</details>
    </>}
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert" style={{ color: '#c44', whiteSpace: 'pre-wrap' }}>{error}</p>}
  </div>
}
