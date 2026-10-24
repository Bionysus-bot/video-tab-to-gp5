import { useEffect, useState } from 'react'

type Note = { string: number; fret: number; kind?: string; slide?: boolean; legato_slide?: boolean; slide_out?: 'down' | 'up' | null; hammer?: boolean; staccato?: boolean; grace?: { fret: number; duration: number; on_beat: boolean } | null }
type Beat = { ocr_confidence?: number | null; pitch_evidence?: 'ocr' | 'staff' | null; rhythm_evidence?: 'notation' | 'fallback' | null; duration: number; dotted?: boolean; triplet?: boolean; unresolved?: ('pitch' | 'duration')[]; notes: Note[] }
type Measure = { number: number; numerator: number; denominator: number; confidence: number; reviewed: boolean; source: string; issues: string[]; beats: Beat[] }
type Score = { title: string; instrument: 'bass' | 'guitar'; tempo: number; tuning: number[]; settings_confirmed: boolean; measures: Measure[] }
type Row = { id: string; source: string; source_row?: number; layout?: 'tab' | 'standard-tab'; strings: number; excluded?: boolean; exclude_reason?: string }
type Issue = { message: string; measure: number | null; severity: string }
type Data = { score: Score; validation: Issue[]; draft_validation?: Issue[]; video_recovery?: { recovered: number; placeholders: number; url: string; evidence: {number: number;url: string}[] }; manifest: { rows: Row[]; rejected: { source: string; reason: string }[] }; task: { status: string; current?: number; total?: number; log: string[] } }

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
  const [layout, setLayout] = useState('auto')
  const [baseUrl, setBaseUrl] = useState('http://127.0.0.1:11434')
  const [limit, setLimit] = useState(3)
  const [force, setForce] = useState(false)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState('')
  const [notice, setNotice] = useState('')
  const [selected, setSelected] = useState(0)
  const [dirty, setDirty] = useState(false)
  const [showReview, setShowReview] = useState(false)
  const [reviewMeasure, setReviewMeasure] = useState(0)
  const [analysis, setAnalysis] = useState<{row: string; stamp: number; fragments?: {side: string;candidate: Measure;complete: boolean}[]; events: {measure: number;beat_index: number;duration: number;confidence: number;pitch_evidence?: string;unresolved: string[]}[]} | null>(null)
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
      if (resolved === 'pitch') { beat.ocr_confidence = null; beat.pitch_evidence = null }
      if (resolved) beat.unresolved = (beat.unresolved || []).filter(item => item !== resolved)
      measure.reviewed = false
    })
  }
  let editing: Score | null = null
  try { editing = JSON.parse(draft) } catch { /* Keep invalid draft editable. */ }
  const row = data?.manifest.rows[selected]
  const totalRows = data?.manifest.rows.length ?? 0
  const skippedRows = data?.manifest.rows.filter(row => row.excluded).length ?? 0
  return <div className="result-preview score-panel">
    <h3>Guitar Pro 转谱</h3>
    <div className="score-fields"><label>谱面类型<select disabled={active} value={layout} onChange={e => setLayout(e.target.value)}>
      <option value="auto">自动判断</option><option value="tab">纯 TAB（保留原识别方式）</option><option value="standard-tab">五线谱＋TAB（上方读取节奏）</option>
    </select></label></div>
    <div className="result-actions">
      <button className="btn" disabled={active} onClick={() => perform(async () => { await call(base + '/prepare?layout=' + layout, { method: 'POST' }); setSelected(0); await load() })}>读取当前视频截图</button>
      <label className="btn">导入 PDF<input type="file" accept="application/pdf,.pdf" disabled={active} style={{ display: 'none' }} onChange={e => {
        const file = e.target.files?.[0]; e.target.value = ''; if (!file) return
        perform(async () => { const form = new FormData(); form.append('file', file); await call(base + '/pdf?layout=' + layout, { method: 'POST', body: form }); setSelected(0); await load() })
      }} /></label>
      <button className="btn" disabled={active || !data?.manifest.rows.length} onClick={() => perform(async () => {
        await save()
        await call(base + '/refresh-images', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ layout }) })
        await load(); setNotice('图片已更新，原有小节及核对标记已保留。错误的已核对内容需先取消核对再重识别。')
      })}>更新谱行图片（保留校对）</button>
    </div>
    {!!data?.manifest.rows.length && <details className="score-fold"><summary>谱面预览与整理 · {totalRows - skippedRows} 行</summary>
      <p>可识别 {totalRows - skippedRows} 行谱面{skippedRows > 0 ? `（共检测 ${totalRows} 行，已跳过 ${skippedRows} 行）` : ''}。请检查过滤结果和弦线识别是否正确。</p>
      <select aria-label="原始谱面行" value={selected} onChange={e => setSelected(Number(e.target.value))}>
        {data.manifest.rows.map((r, i) => <option key={r.id} value={i}>第 {i + 1} 行 · {r.source}{r.source_row ? ` · 页内第 ${r.source_row} 行` : ''} · {r.layout === 'standard-tab' ? '五线谱＋TAB' : '纯 TAB'} · {r.strings} 根弦{r.excluded ? ' · 已跳过' : ''}</option>)}
      </select>
      {row && <a href={`${base}/rows/${row.id}`} target="_blank" rel="noreferrer"><img src={`${base}/rows/${row.id}`} alt={`谱面 ${row.id}`} style={{ width: '100%', background: 'white', marginTop: 8 }} /></a>}
      {row && <>
        {row.layout === 'standard-tab' && <button className="btn" disabled={active} onClick={() => perform(async () => {
          const result=await call(`${base}/rows/${row.id}/analysis`)
          setAnalysis({...result,row:row.id,stamp:Date.now()})
        })}>查看识别位置叠加图</button>}
        {analysis?.row === row.id && <div>
          <p>这是重新分析的候选结果，尚未覆盖保存的乐谱。绿框：已关联；橙框：低置信；红框：具体未确定音符；蓝圈：检测到的音符头；紫圈：旧规则回退位置；橙色边框：未确认完整的边缘片段。</p>
          <a href={`${base}/rows/${row.id}/analysis-image?v=${analysis.stamp}`} target="_blank" rel="noreferrer"><img src={`${base}/rows/${row.id}/analysis-image?v=${analysis.stamp}`} alt="音符与节奏对应位置" style={{width:'100%'}} /></a>
          <details><summary>查看具体拍位与边缘片段</summary>
            {analysis.events.filter(e => e.unresolved.length || (e.confidence<.85 && !e.pitch_evidence)).map(e=><p key={`${e.measure}-${e.beat_index}`}>第{e.measure}小节，第{e.beat_index}拍位：{e.duration}分音符；{e.unresolved.map(k => k === 'pitch' ? '音高未确定' : '时值未确定').join('、') || '数字读数偏弱'}</p>)}
            {analysis.fragments?.map(f=><p key={f.side}>{f.side==='right'?'行末':'行首'}片段：候选第{f.candidate.number}小节，读出{f.candidate.beats.length}个拍位，{f.complete?'匹配和拍数检查通过，保留边界提示':'尚未确认完整'}。</p>)}
          </details>
        </div>}
        {editing?.measures.some(m => m.source === row.id && m.reviewed) && <button className="btn" disabled={active} onClick={() => perform(async () => {
          const next = JSON.parse(draft) as Score
          next.measures.filter(m => m.source === row.id).forEach(m => { m.reviewed = false })
          await save(next); setNotice('已取消此行核对标记，音符数据保留；下次识谱可更新此行。')
        })}>取消此行核对，允许重识别</button>}
        {row.excluded && <p>此行已跳过：{row.exclude_reason}。原图保留。</p>}
        <button className="btn" disabled={active} onClick={() => perform(async () => {
          await save()
          await call(`${base}/rows/${row.id}/exclude`, { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ excluded: !row.excluded, reason: '手动标记为重复或无有效谱面' }) })
          await load()
        })}>{row.excluded ? '恢复此行，供下次识谱' : '跳过此行（重复或片尾）'}</button>
      </>}
    </details>}
    {!!data?.manifest.rejected.length && <details><summary>待复查的过滤画面（{data.manifest.rejected.length}）</summary>{data.manifest.rejected.map((r, i) => <p key={i}>{r.source}：{r.reason}</p>)}</details>}
    <details className="score-fold"><summary>识谱设置</summary>
    <div className="score-fields">
      <label>识别方式<select disabled={active} value={strategy} onChange={e => setStrategy(e.target.value)}><option value="hybrid">本地图像识谱优先（推荐当前谱面）</option><option value="vision">只使用视觉模型</option></select></label>
      <label>识谱服务<select disabled={active} value={provider} onChange={e => { setProvider(e.target.value); setBaseUrl(e.target.value === 'ollama' ? 'http://127.0.0.1:11434' : '') }}><option value="ollama">本地 Ollama</option><option value="compatible">OpenAI 兼容接口</option></select></label>
      <label>接口地址<input disabled={active} value={baseUrl} onChange={e => setBaseUrl(e.target.value)} placeholder="兼容接口填写含 /v1 的地址" /></label>
      <label>视觉模型<input disabled={active} value={model} list="vision-models" onChange={e => setModel(e.target.value)} placeholder="选择或输入模型名" /><datalist id="vision-models">{models.filter(m => m.vision).map(m => <option key={m.name} value={m.name} />)}</datalist></label>
      <button className="btn" disabled={active} onClick={() => perform(detect)}>检测本地模型</button>
      <label>本次识别前几行<input type="number" min={1} max={200} disabled={active} value={limit} onChange={e => setLimit(Number(e.target.value))} /></label>
      <label className="score-cache-option"><input type="checkbox" disabled={active || strategy !== 'hybrid'} checked={force} onChange={e => setForce(e.target.checked)} />忽略缓存，重新识别未核对谱行</label>
    </div>
    {strategy === 'hybrid' && <p>优先读取弦线、品位和符尾；未变化的本地识谱结果会复用缓存，不支持的谱面再尝试所选模型。编号按画面顺序暂定，拍号暂按 4/4，需对照原图核对。</p>}
    {provider === 'compatible' && <p>此模式会将谱面发送到所填地址；密钥由本机环境变量 TAB_VISION_API_KEY 提供。</p>}
    </details>
    <button className="btn btn-primary" disabled={active || (strategy === 'vision' && !model) || !data?.manifest.rows.length} onClick={() => perform(async () => {
      await save()
      await call(base + '/recognize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider, strategy, layout, base_url: baseUrl, model, max_rows: limit, force }) })
      await load()
    })}>{data?.task.status === 'recognizing' ? `识谱中 ${data.task.current || 0}/${data.task.total || 0}` : `开始识谱 · 前 ${limit} 行`}</button>
    <details className="score-fold"><summary>高级修复</summary>
    <button className="btn" disabled={active || !model || !editing?.measures.length} onClick={() => perform(async () => {
      await save()
      await call(base + '/recognize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider, strategy: 'repair', local_review: true, layout, base_url: baseUrl, model, max_rows: limit, force }) })
      await load()
    })}>模型逐拍复核（保留其他音符）</button>
    <button className="btn" disabled={active || !data?.manifest.rows.some(r => r.layout === 'standard-tab')} onClick={() => perform(async () => {
      await save()
      await call(base + '/refresh-images', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ layout, stitch: true }) })
      await load()
      await call(base + '/recognize', { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ provider, strategy: 'hybrid', layout, base_url: baseUrl, model, max_rows: limit, rebuild: true, force: true }) })
      await load()
    })}>修复跨行和编号并重识谱（先备份）</button>
    </details>
    <button className="btn" disabled={active || !editing?.measures.length || !data?.manifest.rows.some(r => r.layout === 'standard-tab')} onClick={() => perform(async () => {
      await save()
      await call(base + '/recover-video', { method: 'POST' })
      await load(); setNotice('正在使用本项目原视频补读，结果另存为草稿，保存的乐谱保留。')
    })}>从原视频补读占位小节（另存草稿）</button>
    {data?.video_recovery && <div>
      <p>补读结果：恢复 {data.video_recovery.recovered} 小节 · 剩余占位 {data.video_recovery.placeholders}</p>
      <a className="btn" href={data.video_recovery.url}>下载原视频补读草稿 GP5</a>
      <details><summary>查看补读小节的原视频画面</summary>{data.video_recovery.evidence.map(e => <p key={e.number}><a href={e.url} target="_blank" rel="noreferrer">第 {e.number} 小节原图</a></p>)}</details>
    </div>}
    {data && <>
      <details className="score-fold"><summary>乐器与速度</summary>
      <div className="score-fields">
        <label>乐器<select disabled={active} value={editing?.instrument || 'bass'} onChange={e => changeSettings({ instrument: e.target.value as 'bass' | 'guitar', tuning: e.target.value === 'bass' ? [43, 38, 33, 28] : [64, 59, 55, 50, 45, 40], settings_confirmed: false })}><option value="bass">贝斯（默认四弦）</option><option value="guitar">吉他（默认六弦）</option></select></label>
        <label>速度 BPM<input disabled={active} type="number" min={20} max={300} value={editing?.tempo || 120} onChange={e => changeSettings({ tempo: Number(e.target.value), settings_confirmed: false })} /></label>
      </div>
      <label><input disabled={active} type="checkbox" checked={editing?.settings_confirmed || false} onChange={e => changeSettings({ settings_confirmed: e.target.checked })} />我已确认乐器、速度和调弦</label>
      </details>
      <details className="score-fold" onToggle={e => setShowReview(e.currentTarget.open)}><summary>校对乐谱 · {data.score.measures.length} 小节</summary>
      {showReview && <>
      <label>选择小节<select aria-label="选择校对小节" value={Math.min(reviewMeasure, Math.max(0,(editing?.measures.length || 1)-1))} onChange={e => setReviewMeasure(Number(e.target.value))}>
        {editing?.measures.map((m,i) => <option key={i} value={i}>第 {m.number} 小节{m.beats.some(b=>b.unresolved?.length) ? ' · 有疑点' : ''}{m.reviewed ? ' · 已核对' : ''}</option>)}
      </select></label>
      {editing?.measures.map((m,mi)=>({m,mi})).filter(({mi})=>mi===Math.min(reviewMeasure,Math.max(0,(editing?.measures.length || 1)-1))).map(({m,mi}) => <details open key={mi} className="score-measure">
        <summary>第 {m.number} 小节 · {m.numerator}/{m.denominator} · {m.reviewed ? '已核对' : '待核对'} · {m.beats.some(b => b.unresolved?.length) ? '有具体疑点' : '无未确定拍位'}</summary>
        <button className="btn" disabled={active} onClick={() => { const index = data.manifest.rows.findIndex(r => r.id === m.source); if (index >= 0) setSelected(index) }}>查看对应原图</button>
        <label>小节编号<input type="number" disabled={active} value={m.number} onChange={e => editMeasure(mi, x => { x.number = Number(e.target.value); x.reviewed = false })} /></label>
        <label>拍号<input type="number" disabled={active} value={m.numerator} onChange={e => editMeasure(mi, x => { x.numerator = Number(e.target.value); x.reviewed = false })} /> / <select disabled={active} value={m.denominator} onChange={e => editMeasure(mi, x => { x.denominator = Number(e.target.value); x.reviewed = false })}>{[1, 2, 4, 8, 16, 32].map(n => <option key={n}>{n}</option>)}</select></label>
        <p>数字识别分数用于筛选读数，不代表小节正确率。{!m.reviewed && m.confidence < .85 && m.beats.every(b => b.ocr_confidence == null) ? '旧数据仅有最低OCR分数，未记录具体位置；需查看原图，不能定位为某个音错误。' : ''}</p>
        {m.issues.map((issue, i) => <p key={i}>{issue}</p>)}
        {m.beats.map((b, bi) => <div key={bi} className="score-beat">
          {b.ocr_confidence != null && <p>数字读数：{m.reviewed ? '已人工核对' : b.pitch_evidence === 'staff' ? '已获五线谱音高佐证' : b.ocr_confidence < .85 ? '偏弱，需对照原图' : 'OCR读数较清楚'}；节奏来源：{b.rhythm_evidence === 'notation' ? '音符头与符尾关联' : b.rhythm_evidence === 'fallback' ? '原图规则回退，建议核对' : '未记录'}。</p>}
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
      <details><summary>高级：完整乐谱数据（可修改滑音等属性）</summary><textarea aria-label="乐谱数据" disabled={active} value={draft} spellCheck={false} onChange={e => { setDraft(e.target.value); setDirty(true) }} style={{ width: '100%', minHeight: 240, fontFamily: 'monospace', boxSizing: 'border-box' }} /></details>
      </>}
      </details>
      <div className="result-actions">
        <button className="btn" disabled={active || !editing?.measures.length} onClick={() => perform(async () => {
          await save()
          window.location.assign(base + '/download-diagnostic')
          setNotice('已读出的低置信度音符会保留并标 CHECK；缺失或时值错误小节以 UNREADABLE 占位，不代表原谱。')
        })}>下载诊断 GP5（保留低置信度音符）</button>
        <button className="btn" disabled={active} onClick={() => perform(async () => { await save(); setNotice('已保存并校验') })}>保存并校验</button>
        <details className="score-fold score-export-more"><summary>更多导出与核对</summary>
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
        </details>
      </div>
      {dirty && <p>有未保存的修改，请保存后导出。</p>}
      <details className="score-fold"><summary>校验详情 · {data.validation.filter(v=>v.severity==='error').length} 项待处理</summary>
      <div role="status">{[...data.validation].sort((a, b) => Number(b.severity === 'error') - Number(a.severity === 'error')).slice(0, 30).map((v, i) => <p key={i} style={{ color: v.severity === 'error' ? '#c44' : '#a76b00' }}>{v.measure ? `第 ${v.measure} 小节：` : ''}{v.message}</p>)}</div>
      </details>
      <details open={data.task.status === 'failed'}><summary>识谱日志 · {data.task.status}</summary>{data.task.log.map((line, i) => <p key={i}>{line}</p>)}</details>
    </>}
    <details className="score-fold"><summary>操作说明</summary>
    <p>先整理谱面，再识别与核对，最后下载 .gp5。第一版建议先试前 3 行。</p>
    <p>已有核对标记的谱行会自动保留。需要重新识别该行时，请先取消该行所有小节的核对标记。</p>
    <p>纯 TAB 沿用原识别；五线谱＋TAB 使用独立本地流程，从上方读取节奏、下方读取品位，也可选择逐小节视觉模型。切换类型后，请更新谱行图片或重新导入。新类型仍需人工校对。</p>
    <p>请使用生成本份 PDF 的原视频项目。补读会保留边缘像素、按印刷小节号拼接，并用已识别的相邻小节核对来源；仅接受通过音符与时值校验的候选。</p>
    <p>结构修复会拼接能够确认属于同一小节的相邻片段，并在所选前几行中重新识别联合谱，替换原有核对内容。缺少画面的片段会保留缺口提示，不会编造音符。</p>
    <p>逐拍模型复核会先备份，在所选前几行中只修改有疑点的拍位字段（包括已标记核对但仍有错误的小节），保留其余音符和拍位顺序。不接受增加新错误或让拍数偏差变大的修改；仍无法确定时保留原值。</p>
      <p>默认调弦为标准调弦，速度 120 是占位值。特殊调弦可在下方数据中修改，按最高音弦到最低音弦填写 MIDI 音高。</p>
      <p>时值：4=四分音符、8=八分音符；notes=[] 表示休止。弦号 1 是图中最上方的弦。修改数据后先保存并校验。</p>
      <p>诊断 GP5 不因置信度低而丢弃已读出的音符，保留候选音；具体疑点标 CHECK PITCH，弱数字读数标 CHECK OCR；缺失音符或时值错误的小节仍以 UNREADABLE 占位，占位不代表原谱。完整草稿和已核对版本仍需通过相应校验。</p>
    </details>
    {notice && <p role="status">{notice}</p>}
    {error && <p role="alert" style={{ color: '#c44', whiteSpace: 'pre-wrap' }}>{error}</p>}
  </div>
}
