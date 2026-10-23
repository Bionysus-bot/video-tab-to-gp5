import { useCallback, useEffect, useRef, useState } from 'react';
import type { ProjectInfo, ProjectConfig, ROI } from '../types';
import * as legacy from '../services/api';
import { call, activeJob } from '../services/workspace';
import type { WorkspaceData, Revision, Job, PdfInput, Score } from '../services/workspace';
import type { Artifact } from '../services/workspace';
import ROISelector from '../components/ROISelector';
import MeasureEditor from '../components/MeasureEditor';
import Botanical from '../components/Botanical';
import '../studio.css';
type View = 'prepare' | 'convert' | 'results';
const labels: Record<string, string> = { pitch: '音高', duration: '时值', tie_or_technique: '延音 / 演奏法', fragment_gap: '片段缺失', number_conflict: '编号对应', settings_unconfirmed: '设置待确认', ocr_notice: '数字读数提醒' };
const stageNames: Record<string, string> = { prepare: '整理谱面', read: '本地识别', validate: '校验结果', recover: '原视频补读', review: '局部复核', export: '生成草稿' };
const originNames: Record<string, string> = { 'manual': '人工保存', 'legacy-import': '原项目结果', 'video-recovery-import': '原视频补读草稿', 'local-read': '本地识别', 'video-recovery': '视频补读', 'local-review': '模型复核' };
function preferences() {
    try {
        return JSON.parse(localStorage.getItem('score-studio-preferences') || '{}');
    }
    catch {
        return {};
    }
}
function Mark() { return <svg viewBox="0 0 32 32" fill="none" aria-hidden="true"><path d="M7 7v18M13 7v18M19 7v18M25 7v18M5 12h22M5 20h22" stroke="currentColor" strokeWidth=".75"/><circle cx="19" cy="12" r="3" fill="currentColor"/></svg>; }
export default function Studio() {
    const [project, setProject] = useState('');
    const [projects, setProjects] = useState<ProjectInfo[]>([]);
    const [config, setConfig] = useState<ProjectConfig | null>(null);
    const [data, setData] = useState<WorkspaceData | null>(null);
    const [revision, setRevision] = useState<Revision | null>(null);
    const [draft, setDraft] = useState<Score | null>(null);
    const [view, setView] = useState<View>('prepare');
    const [source, setSource] = useState<'video' | 'pdf' | 'existing'>('video');
    const [pdf, setPdf] = useState<PdfInput | null>(null);
    const [roi, setROI] = useState<ROI | null>(null);
    const [layout, setLayout] = useState('standard-tab');
    const [time, setTime] = useState(0);
    const [error, setError] = useState('');
    const [message, setMessage] = useState('');
    const [busy, setBusy] = useState(false);
    const [selected, setSelected] = useState(0);
    const [filter, setFilter] = useState('important');
    const [dirty, setDirty] = useState(false);
    const [overlay, setOverlay] = useState<{
        revision: string;
        source: string;
        url: string;
    } | null>(null);
    const [job, setJob] = useState<Job | null>(null);
    const [tempo, setTempo] = useState(120);
    const [model, setModel] = useState<string>(() => preferences().model || '');
    const [review, setReview] = useState<boolean>(() => !!preferences().review);
    const [provider, setProvider] = useState<string>(() => preferences().provider || 'ollama');
    const [baseUrl, setBaseUrl] = useState<string>(() => preferences().baseUrl || 'http://127.0.0.1:11434');
    const [models, setModels] = useState<string[]>([]);
    const [drawerTab, setDrawerTab] = useState('score');
    const settings = useRef<HTMLDialogElement>(null);
    const unsaved = useRef<HTMLDialogElement>(null);
    const pending = useRef<(() => void) | null>(null);
    const current = useRef('');
    const requestVersion = useRef(0);
    const dirtyRef = useRef(false);
    dirtyRef.current = dirty;
    const fileInput = useRef<HTMLInputElement>(null);
    const roiSave = useRef<Promise<unknown>>(Promise.resolve());
    const running = activeJob(job);
    const root = project ? `/projects/${project}` : '';
    useEffect(() => { localStorage.setItem('score-studio-preferences', JSON.stringify({ model, review, provider, baseUrl })); }, [model, review, provider, baseUrl]);
    const applyRevision = (value: Revision | null) => { setRevision(value); setDraft(value ? structuredClone(value.score) : null); setSelected(0); setDirty(false); };
    const refresh = useCallback(async (pid: string, reset = true) => {
        const next = await call<WorkspaceData>(`/projects/${pid}/workspace`);
        if (current.current !== pid)
            return;
        setData(next);
        setJob(next.job);
        setPdf(next.pdf);
        if (reset && !dirtyRef.current) {
            applyRevision(next.revision);
        }
        return next;
    }, []);
    const openProject = useCallback(async (pid: string) => {
        current.current = pid;
        requestVersion.current++;
        setProject(pid);
        setError('');
        setData(null);
        setConfig(null);
        applyRevision(null);
        setJob(null);
        localStorage.setItem('score-extractor-project', pid);
        const [p, next] = await Promise.all([legacy.getProject(pid), refresh(pid)]);
        if (current.current !== pid)
            return;
        setConfig(p.config);
        setROI(p.config.roi);
        setTime(0);
        setSource(next?.pdf ? 'pdf' : p.config.video ? 'video' : 'existing');
        if (next?.revision) {
            setTempo(next.revision.score.tempo);
            setView('results');
        }
        else {
            setView('prepare');
        }
    }, [refresh]);
    useEffect(() => {
        let alive = true;
        (async () => {
            const all = await legacy.listProjects();
            if (!alive)
                return;
            setProjects(all);
            const saved = localStorage.getItem('score-extractor-project');
            const pid = all.find(p => p.id === saved)?.id || all[0]?.id || (await legacy.createProject()).id;
            if (alive)
                await openProject(pid);
        })().catch(e => setError(e.message));
        return () => { alive = false; current.current = ''; };
    }, [openProject]);
    useEffect(() => {
        if (!project || !running || !job)
            return;
        const pid = project, jid = job.id;
        let alive = true;
        let waiting = false;
        const timer = setInterval(async () => {
            if (waiting)
                return;
            waiting = true;
            try {
                const next = await call<Job>(`/projects/${pid}/conversion-jobs/${jid}`);
                if (alive && current.current === pid) {
                    setJob(next);
                    if (!activeJob(next))
                        await refresh(pid, false);
                }
            }
            catch (e) {
                if (alive)
                    setError(String(e));
            }
            finally {
                waiting = false;
            }
        }, 1200);
        return () => { alive = false; clearInterval(timer); };
    }, [project, job?.id, running, refresh]);
    useEffect(() => {
        const handler = (e: BeforeUnloadEvent) => {
            if (dirtyRef.current) {
                e.preventDefault();
                e.returnValue = '';
            }
        };
        window.addEventListener('beforeunload', handler);
        return () => window.removeEventListener('beforeunload', handler);
    }, []);
    const guarded = (action: () => void) => {
        if (dirty) {
            pending.current = action;
            unsaved.current?.showModal();
        }
        else
            action();
    };
    const perform = async (action: () => Promise<unknown>) => {
        setBusy(true);
        setError('');
        setMessage('');
        try {
            await action();
        }
        catch (e) {
            setError(e instanceof Error ? e.message : String(e));
        }
        finally {
            setBusy(false);
        }
    };
    async function upload(file: File) {
        await perform(async () => {
            // New material always gets a new project, leaving existing music and assets untouched.
            const p = await legacy.createProject();
            current.current = p.id;
            setProject(p.id);
            applyRevision(null);
            setData(null);
            setPdf(null);
            setJob(null);
            setROI(null);
            setTime(0);
            localStorage.setItem('score-extractor-project', p.id);
            if (file.name.toLowerCase().endsWith('.pdf')) {
                const form = new FormData();
                form.append('file', file);
                const response = await fetch(`/api/projects/${p.id}/inputs/pdf`, { method: 'POST', body: form });
                if (!response.ok) {
                    const value = await response.json();
                    throw new Error(value.detail || 'pdf 导入失败');
                }
                const input = await response.json() as PdfInput;
                setPdf(input);
                setSource('pdf');
                setConfig(p.config);
            }
            else {
                await legacy.uploadVideo(p.id, file);
                const loaded = await legacy.getProject(p.id);
                setConfig(loaded.config);
                setSource('video');
            }
            await refresh(p.id);
            setProjects(await legacy.listProjects());
            setView('prepare');
            setMessage('素材已导入，请选择谱面区域和类型。');
        });
    }
    const saveROI = async (next: ROI) => {
        setROI(next);
        if (source === 'video') {
            const pid = project;
            const save = roiSave.current.catch(() => { }).then(() => legacy.setROI(pid, next));
            roiSave.current = save;
            await save;
        }
    };
    async function start() {
        await perform(async () => {
            await roiSave.current;
            if (source === 'video' && config) await legacy.setProcessingConfig(project, config.processing);
            const latest = await call<WorkspaceData>(root + '/workspace');
            const next = await call<Job>(root + '/conversion-jobs', {
                source, input_id: pdf?.id, layout, roi, base_revision: latest.state.active_revision, tempo, tuning: draft?.tuning || [43, 38, 33, 28],
                review, model, provider, base_url: baseUrl, recover: true
            });
            setJob(next);
            setView('convert');
        });
    }
    async function selectVersion(id: string) { await perform(async () => { const latest = await call<WorkspaceData>(root + '/workspace'); await call(root + `/revisions/${id}/activate`, { expected_revision: latest.state.active_revision }); await refresh(project); setView('results'); }); }
    async function save() {
        if (!draft || !revision)
            return false;
        try {
            const savingProject = project;
            setError('');
            const value = await call<Revision>(root + `/revisions/${revision.id}/edits`, { expected_revision: revision.id, score: draft });
            if (current.current !== savingProject) return false;
            applyRevision(value);
            await refresh(project, false);
            setMessage('已保存为新版本，修改内容受到保护。');
            return true;
        }
        catch (e) {
            setError(String(e));
            return false;
        }
    }
    async function createDraft(download = false) {
        if (!revision)
            return;
        await perform(async () => {
            if (dirty && !(await save()))
                return;
            const next = await call<WorkspaceData>(root + '/workspace');
            const id = next.state.active_revision;
            if (!id)
                return;
            const output = await call<Artifact>(root + `/revisions/${id}/artifacts`, {});
            await refresh(project, false);
            setMessage('当前版本的 gp5 草稿已生成。');
            if (download) window.location.assign(`/api${root}/artifacts/${output.id}/download`);
        });
    }
    const art = data?.artifacts.find(a => a.revision === revision?.id) || (job?.artifact && job.artifact.revision === revision?.id ? job.artifact : null);
    const issues = revision?.issues.filter(i => filter === 'all' || (filter === 'important' ? !['ocr_notice', 'settings_unconfirmed'].includes(i.kind) : i.kind === filter)) || [];
    const measure = draft?.measures[selected];
    const row = revision?.manifest.rows.find(r => r.id === measure?.source);
    const imageUrl = revision && row ? `/api${root}/revisions/${revision.id}/rows/${row.id}` : '';
    const width = source === 'pdf' ? pdf?.width : config?.video?.width;
    const height = source === 'pdf' ? pdf?.height : config?.video?.height;
    const preview = source === 'pdf' && pdf ? `/api${root}/inputs/${pdf.id}/preview` : config?.video ? legacy.getPreviewUrl(project, time, 1600) : '';
    const issueCount = revision?.issues.filter(i => !['ocr_notice', 'settings_unconfirmed'].includes(i.kind)).length || 0;
    const steps = Object.entries(stageNames);
    const botanicalVariant = ['prepare','convert','results'].indexOf(view);
    return <div className="studio"><header className="studio-header"><a className="brand" href="/" aria-label="谱间首页"><Mark /><span>谱间<small>video to score</small></span></a>
   <div className="project-switch"><label className="sr-only" htmlFor="project-select">当前项目</label><select id="project-select" disabled={busy} value={project} onChange={e => { const pid = e.target.value; guarded(() => { void perform(() => openProject(pid)); }); }}>{projects.map(p => <option key={p.id} value={p.id}>{p.config.source_video?.split(/[\\/]/).pop()?.replace(/^[a-f0-9]{32}/, '视频') || `本地项目 ${p.id.slice(0, 6)}`}</option>)}{project && !projects.some(p => p.id === project) && <option value={project}>新项目</option>}</select><span className="save-state">{dirty ? '有未保存修改' : '本地保存'}</span></div>
   <div className="header-tools"><button className="text-button" onClick={() => settings.current?.showModal()}>设置</button><a className="text-button" href="/?legacy=1">旧版界面 ↗</a></div>
 </header>
 <nav className="view-tabs" aria-label="工作视图">{([['prepare', '01', '准备素材'], ['convert', '02', '自动识谱'], ['results', '03', '结果校对']] as const).map(([key, num, name]) => <button key={key} aria-current={view === key ? 'step' : undefined} className={view === key ? 'selected' : ''} onClick={() => guarded(() => setView(key))}><span>{num}</span>{name}{key === 'convert' && running && <i className="live-dot"/>}</button>)}<div className="local-badge"><i /> 本机工作区</div></nav>
 <main className="studio-main">
   {error && <div className="banner error" role="alert"><span>{error}</span><button aria-label="关闭错误" onClick={() => setError('')}>×</button></div>}
   {message && <div className="banner notice" role="status">{message}</div>}
   {view === 'prepare' && <><div className="page-heading"><Botanical variant={botanicalVariant}/><div><p className="eyebrow">一份新的乐谱</p><h1>从画面，回到乐谱。</h1><p>选好区域与谱面类型，其余交给自动识谱。</p></div><button className="button secondary" disabled={busy || running} onClick={() => guarded(() => fileInput.current?.click())}>＋ 导入视频 / pdf</button></div>
   <input className="sr-only" type="file" accept="video/*,.pdf" ref={fileInput} aria-label="导入视频或 pdf" onChange={e => {
                const file = e.target.files?.[0];
                e.target.value = '';
                if (file)
                    void upload(file);
            }}/>
   <div className="preparation-grid"><section className="source-surface"><div className="surface-heading"><h2>{pdf?.name || (config?.video ? '视频谱面' : '素材预览')}</h2><span>{width && height ? `${width} × ${height}` : '视频 / pdf'}</span></div>
     {preview && width && height ? <><ROISelector key={`${project}-${source}`} imageUrl={preview} videoWidth={width} videoHeight={height} displayWidth={width} onROIChange={saveROI} initialROI={roi}/>
       {source === 'video' && config?.video && <div className="timeline"><span>画面时间</span><input aria-label="选择视频画面时间" type="range" min={0} max={config.video.duration} step={.5} value={time} onChange={e => setTime(Number(e.target.value))}/><output>{Math.floor(time / 60)}:{String(Math.floor(time % 60)).padStart(2, '0')}</output></div>}
       {pdf && <p className="canvas-caption">共 {pdf.pages} 页 · 在第一页确认区域，其他页按相同比例应用；版式不同请分项目导入。</p>}</> : <div className="empty-canvas"><Mark /><h2>放入一份想演奏的谱</h2><p>支持本地视频、pdf。原始素材会保留。</p><button className="button secondary" disabled={busy} onClick={() => fileInput.current?.click()}>选择文件</button>{data?.revision && <button className="text-button" onClick={() => setSource('existing')}>使用旧项目已有谱行</button>}</div>}
   </section><aside className="setup-panel"><p className="eyebrow">转谱配置</p><h2>转谱设置</h2><fieldset><legend>谱面类型</legend>{[['tab', '纯 tab', '数字指法与原有节奏读取'], ['standard-tab', '五线谱 ＋ tab', '上方读节奏，下方读品位']].map(([value, title, desc]) => <label className={'type-option ' + (layout === value ? 'chosen' : '')} key={value}><input type="radio" name="layout" value={value} checked={layout === value} onChange={() => setLayout(value)}/><span><strong>{title}</strong><small>{desc}</small></span></label>)}</fieldset>
   <div className="setup-row"><span>乐器</span><strong>四弦贝斯</strong></div><div className="setup-row"><span>速度</span><label className="floating-field"><input aria-label="速度 bpm" type="number" min={20} max={300} value={tempo} onChange={e => setTempo(Number(e.target.value))}/><span className="field-label"> bpm</span></label></div><p className="muted">当前速度和调弦为设置值，不代表已从原图确认。</p>
   <button className="text-button settings-link" onClick={() => { setDrawerTab('score'); settings.current?.showModal(); }}>更多设置 →</button>
   <div className="setup-note">{layout === 'standard-tab' ? '请框入完整的五线谱和下方 tab，保留小节编号。' : '请包含完整弦线、品位和节奏符号。'}</div>
   <button className="button primary start-button" disabled={busy || running || (!roi && source !== 'existing') || (source === 'existing' && !revision) || !project} onClick={() => guarded(() => { void start(); })}>{busy ? '正在准备…' : '开始自动识谱 →'}</button><span className="micro-copy">有疑点也会生成可下载草稿</span>
   </aside></div></>}
   {view === 'convert' && <><div className="page-heading"><Botanical variant={botanicalVariant}/><div><p className="eyebrow">转谱进行中</p><h1>{running ? '让乐谱逐渐清晰。' : job ? '这次转谱已有结果。' : '准备开始一次转谱。'}</h1><p>{job?.message || '先导入素材，确认区域和谱面类型。'}</p></div>{running && <button className="button secondary" onClick={() => perform(async () => setJob(await call(root + `/conversion-jobs/${job!.id}/cancel`, {})))}>取消任务</button>}</div>
   <div className="conversion-grid"><section className="progress-overview"><div className="surface-heading"><h2>{stageNames[job?.stage || ''] || '等待开始'}</h2><span>{job ? `${Math.round(job.elapsed_seconds)} 秒` : '—'}</span></div><div className="progress-center"><Mark /><strong>{job?.total ? `${job.current} / ${job.total}` : '自动转谱'}</strong><span>{running ? '正在处理 · 可以切换视图' : '已有素材和草稿会保留'}</span></div>{job && <details className="task-details"><summary>处理记录 · 缓存复用 {job.cache_hits} 次</summary><pre>{job.log.join('\n')}</pre></details>}</section>
   <aside className="stage-list">{steps.map(([key, title], i) => { const currentIndex = steps.findIndex(([key]) => key === job?.stage); const done = !!job && (i < currentIndex || job.status === 'completed'); return <div className={done ? 'done' : key === job?.stage ? 'current' : ''} key={key}><span className="stage-number">{done ? '✓' : String(i + 1).padStart(2, '0')}</span><div><strong>{title}</strong><small>{key === job?.stage ? job.message : done ? '已完成' : key === 'review' && !review ? '按需 / 可选' : '等待处理'}</small></div></div>; })}</aside></div>
   {job?.artifact && <div className="draft-strip"><div><span className="eyebrow">当前草稿</span><h2>草稿已可下载</h2><p>占位 {job.artifact.report.placeholders.length} 小节 · 局部待核对 {job.artifact.report.partial_bars?.length || 0} 小节{running ? ' · 自动复核继续进行' : ''}</p></div><div className="button-row"><button className="button secondary" onClick={() => guarded(() => {
                    if (job.revision)
                        void selectVersion(job.revision);
                })}>查看这份结果</button><a className="button primary" href={`/api${root}/artifacts/${job.artifact.id}/download`}>下载当前 gp5 草稿 ↓</a></div></div>}
   {!job && <button className="button primary" onClick={() => setView('prepare')}>前往准备素材</button>}{job && ['failed', 'partial', 'cancelled', 'interrupted'].includes(job.status) && <button className="button secondary" disabled={busy} onClick={() => perform(async () => setJob(await call(root + `/conversion-jobs/${job.id}/resume`, {})))}>从检查点继续</button>}
   </>}
   {view === 'results' && <><div className="page-heading"><Botanical variant={botanicalVariant}/><div><p className="eyebrow">你的乐谱</p><h1>先演奏，再细看。</h1><p>{draft ? `${draft.measures.length} 个小节 · ${issueCount} 个待确认项` : '还没有识谱结果。识谱完成后，草稿会出现在这里。'}</p></div><div className="button-row">{dirty ? <button className="button primary" disabled={busy} onClick={() => void createDraft(true)}>保存并下载草稿 ↓</button> : art ? <a className="button primary" href={`/api${root}/artifacts/${art.id}/download`}>下载 gp5 草稿 ↓</a> : <button className="button primary" disabled={!revision || busy} onClick={() => void createDraft()}>生成 gp5 草稿</button>}</div></div>
   {revision && draft ? <><div className="result-toolbar"><label className="floating-field"><span className="field-label">结果版本</span><select value={revision.id} onChange={e => { const id = e.target.value; guarded(() => { void selectVersion(id); }); }}>{data?.revisions.map(r => <option key={r.id} value={r.id}>{originNames[r.origin] || r.origin} · {new Date(r.created_at).toLocaleString()} · {r.measures} 小节</option>)}</select></label><span className="muted">{dirty ? '修改尚未保存' : '草稿不代表全部音符已准确'}</span>{art && <a className="text-button" href={`/api${root}/artifacts/${art.id}/issues`}>问题报告 ↗</a>}<button className="button secondary" disabled={!dirty || busy} onClick={() => perform(async () => { await save(); })}>保存修改</button></div>
   <div className="review-grid"><aside className="issue-queue"><div className="surface-heading"><h2>待确认</h2><span>{issues.length}</span></div><label className="sr-only" htmlFor="issue-filter">筛选疑点类型</label><select id="issue-filter" value={filter} onChange={e => setFilter(e.target.value)}><option value="important">主要疑点</option><option value="all">全部提示</option>{Object.entries(labels).map(([key, title]) => <option key={key} value={key}>{title}</option>)}</select><div className="issue-items">{issues.map(issue => <button key={issue.id} className={issue.measure_index === selected ? 'issue-item chosen' : 'issue-item'} onClick={() => guarded(() => {
                        if (issue.measure_index !== null)
                            setSelected(issue.measure_index);
                        else {
                            setDrawerTab('score');
                            settings.current?.showModal();
                        }
                    })}><span>{issue.number ? `第 ${issue.number} 小节` : '乐谱设置'}{issue.beat ? ` · 拍位 ${issue.beat}` : ''}</span><strong>{labels[issue.kind] || issue.kind}</strong><small>{issue.message}</small></button>)}{!issues.length && <div className="quiet-empty">当前筛选下没有待处理项。<small>程序检查不能代替演奏核对。</small></div>}</div></aside>
   <section className="review-content"><div className="measure-toolbar"><label className="floating-field"><span className="field-label">浏览小节</span><select value={selected} onChange={e => { const index = Number(e.target.value); guarded(() => setSelected(index)); }}>{draft.measures.map((m, i) => <option value={i} key={i}>第 {m.number} 小节</option>)}</select></label><div className="button-row"><button className="text-button" disabled={selected === 0} onClick={() => guarded(() => setSelected(selected - 1))}>← 上一小节</button><button className="text-button" disabled={selected >= draft.measures.length - 1} onClick={() => guarded(() => setSelected(selected + 1))}>下一小节 →</button></div></div>
   {measure && <><div className="source-heading"><h2>第 {measure.number} 小节</h2><span>{row?.source || measure.source || '旧版本未记录来源'} · {measure.numerator}/{measure.denominator}</span>{revision.protected.includes(revision.entities[selected]?.id) && <span className="protected-badge">人工内容保护</span>}</div><div className="score-canvas">{imageUrl ? <a href={overlay?.revision === revision.id && overlay.source === measure.source ? overlay.url : imageUrl} target="_blank" rel="noreferrer"><img src={overlay?.revision === revision.id && overlay.source === measure.source ? overlay.url : imageUrl} alt={`第 ${measure.number} 小节来源谱行，可打开原图放大`}/></a> : <div className="quiet-empty">此版本未关联可显示的原图。</div>}</div><div className="canvas-controls"><p className="canvas-caption">点击谱面可查看原图。保存修改后，自动识谱不会覆盖受保护的小节。</p>{row?.layout === 'standard-tab' && <button className="text-button" disabled={busy} onClick={() => perform(async () => {
                            if (overlay?.revision === revision.id && overlay.source === measure.source) {
                                setOverlay(null);
                                return;
                            }
                            const result = await call<{
                                url: string;
                            }>(root + `/revisions/${revision.id}/rows/${row.id}/analysis`, {});
                            setOverlay({ revision: revision.id, source: measure.source, url: result.url });
                            setMessage('关联图是重新读取的候选，不会覆盖已保存乐谱。绿框为关联结果，橙框为弱读数，红框为未确定位置。');
                        })}>{overlay?.revision === revision.id && overlay.source === measure.source ? '返回原图' : '查看音符关联图'}</button>}</div><MeasureEditor key={`${revision.id}-${selected}`} measure={measure} onChange={value => { const next = structuredClone(draft); next.measures[selected] = value; setDraft(next); setDirty(true); }}/></>}
   </section></div></> : <div className="empty-result"><Mark /><h2>乐谱尚未生成</h2><button className="button secondary" onClick={() => setView(running ? 'convert' : 'prepare')}>{running ? '查看识谱进度' : '导入并准备素材'}</button></div>}
   </>}
 </main>
 <footer className="studio-footer"><span>本地素材 · 版本保留 · 草稿可编辑</span><span>基于 guitar-score-extractor · 非商业使用 <button className="text-button" onClick={() => { setDrawerTab('about'); settings.current?.showModal(); }}>来源与说明</button></span></footer>
 <dialog className="settings-dialog" ref={settings} onClick={e => {
            if (e.target === settings.current)
                settings.current.close();
        }}><div className="drawer"><header><h2>工作区设置</h2><button className="icon-button" aria-label="关闭设置" onClick={() => settings.current?.close()}>×</button></header><nav>{[['score', '乐谱'], ['model', '模型'], ['video', '视频'], ['about', '说明']].map(([key, title]) => <button key={key} className={drawerTab === key ? 'selected' : ''} onClick={() => setDrawerTab(key)}>{title}</button>)}</nav>
 {drawerTab === 'score' && <div className="drawer-body"><h3>四弦贝斯</h3><p>调弦默认从高到低为 G、D、A、E。以下配置用于新任务，已有草稿不自动改变。</p><label className="floating-field"><span className="field-label">速度 bpm</span><input type="number" min={20} max={300} value={tempo} onChange={e => setTempo(Number(e.target.value))}/></label><p className="muted">调弦使用 midi 音高，从高弦到低弦。</p>{draft && <><div className="tuning-fields">{draft.tuning.map((value, index) => <label key={index} className="floating-field">{index + 1}<span className="field-label"> 弦</span><input type="number" min={0} max={127} value={value} onChange={e => { const next = structuredClone(draft); next.tuning[index] = Number(e.target.value); setDraft(next); setDirty(true); }}/></label>)}</div><label className="check-label"><input type="checkbox" checked={draft.settings_confirmed} onChange={e => { setDraft({ ...draft, settings_confirmed: e.target.checked, tempo }); setDirty(true); }}/>我已确认速度、调弦与拍号设置</label><button className="button secondary" disabled={!dirty} onClick={() => perform(async () => { await save(); })}>保存乐谱设置</button></>}<p>当前优先验证四弦贝斯。复杂演奏法和不完整画面仍可能需要核对。</p></div>}
 {drawerTab === 'model' && <div className="drawer-body"><h3>局部视觉复核</h3><label className="check-label"><input type="checkbox" checked={review} onChange={e => setReview(e.target.checked)}/>自动复核具体疑点</label><p>可选；未启用时仍可使用本地识谱并下载草稿。</p><label className="floating-field"><span className="field-label">服务</span><select value={provider} onChange={e => { setProvider(e.target.value); setBaseUrl(e.target.value === 'ollama' ? 'http://127.0.0.1:11434' : ''); }}><option value="ollama">本机 Ollama</option><option value="compatible">兼容图片接口</option></select></label><label className="floating-field"><span className="field-label">地址</span><input value={baseUrl} onChange={e => setBaseUrl(e.target.value)}/></label><label className="floating-field"><span className="field-label">视觉模型</span><input value={model} list="studio-models" placeholder="qwen3-vl:8b-instruct" onChange={e => setModel(e.target.value)}/><datalist id="studio-models">{models.map(m => <option key={m} value={m}/>)}</datalist></label><button className="button secondary" onClick={() => perform(async () => {
                const next = await call<{
                    models: {
                        name: string;
                        vision: boolean;
                    }[];
                    error: string;
                }>('/score/models');
                setModels(next.models.filter(m => m.vision).map(m => m.name));
                if (next.error)
                    throw new Error(next.error);
            })}>检测本地模型</button>{provider === 'compatible' && <p className="warning-text">启用后，谱面图片将发送到所填服务。密钥由本机 本机环境变量 环境变量提供。</p>}<p className="muted">局部请求最长 90 秒，总复核预算 10 分钟。无法确定时保留疑点。</p></div>}
 {drawerTab === 'video' && <div className="drawer-body"><h3>视频抽帧</h3><p>设置用于下次识谱；默认每秒 1 帧。</p>{config && <><label className="floating-field"><span className="field-label">每秒帧数</span><input type="number" min={.5} max={30} step={.5} value={config.processing.sample_fps} onChange={e => setConfig({ ...config, processing: { ...config.processing, sample_fps: Number(e.target.value) } })}/></label><label className="floating-field"><span className="field-label">开始时间（秒）</span><input type="number" min={0} value={config.processing.start_time} onChange={e => setConfig({ ...config, processing: { ...config.processing, start_time: Number(e.target.value) } })}/></label><button className="button secondary" disabled={running} onClick={() => perform(async () => { await legacy.setProcessingConfig(project, config.processing); setMessage('视频参数已保存，用于下次识谱。'); })}>保存视频设置</button></>}</div>}
 {drawerTab === 'about' && <div className="drawer-body"><h3>关于谱间</h3><p>视频 / pdf 转可编辑的 guitar pro 5 草稿。程序检查通过与零占位均不代表每个音符准确。</p><p>基于 <a href="https://github.com/codemanhr/guitar-score-extractor" target="_blank" rel="noreferrer">codemanhr/guitar-score-extractor</a>，原项目提供视频抽帧、区域选择和 pdf 导出。本项目增加识谱、复核、乐谱编辑及 gp5 输出。</p><p>原创新增内容的非商业限制以项目许可文件为准；上游及既有 MIT 权利保留。请只处理有权使用的素材，转换不自动取得传播或销售授权。</p><a href="/?legacy=1">打开旧版界面与原有高级工具 ↗</a></div>}
 </div></dialog>
 <dialog className="unsaved-dialog" ref={unsaved}><h2>保留这次修改？</h2><p>当前小节有未保存的内容。</p><div className="button-row"><button className="button secondary" onClick={() => { unsaved.current?.close(); pending.current = null; }}>留在当前页</button><button className="text-button" onClick={() => { setDirty(false); setDraft(revision ? structuredClone(revision.score) : null); unsaved.current?.close(); pending.current?.(); pending.current = null; }}>放弃修改</button><button className="button primary" onClick={async () => {
            if (await save()) {
                unsaved.current?.close();
                pending.current?.();
                pending.current = null;
            }
        }}>保存并继续</button></div></dialog>
 </div>;
}
