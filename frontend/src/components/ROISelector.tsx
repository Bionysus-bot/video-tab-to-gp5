import { useEffect, useRef, useState } from 'react'
import type { FormEvent, PointerEvent } from 'react'
import type { ROI } from '../types'

interface Props {
  imageUrl: string
  videoWidth: number
  videoHeight: number
  displayWidth: number
  onROIChange: (roi: ROI) => void | Promise<void>
  initialROI?: ROI | null
}

interface DragState {
  pointerId: number
  bounds: DOMRect
  startX: number
  startY: number
  endX: number
  endY: number
}

const fields = [
  { key: 'x', label: '横向起点' },
  { key: 'y', label: '纵向起点' },
  { key: 'width', label: '宽度' },
  { key: 'height', label: '高度' },
] as const
type ROIFields = Record<keyof ROI, string>
const toFields = (roi: ROI): ROIFields => ({
  x: String(roi.x), y: String(roi.y), width: String(roi.width), height: String(roi.height),
})
const clamp = (value: number, max: number, min = 0) => Math.max(min, Math.min(value, max))
const dragBox = (drag: DragState): ROI => ({
  x: Math.min(drag.startX, drag.endX),
  y: Math.min(drag.startY, drag.endY),
  width: Math.abs(drag.endX - drag.startX),
  height: Math.abs(drag.endY - drag.startY),
})

export default function ROISelector({
  imageUrl, videoWidth, videoHeight, displayWidth, onROIChange, initialROI,
}: Props) {
  const [roi, setROI] = useState<ROI | null>(initialROI ?? null)
  const [draft, setDraft] = useState<ROIFields | null>(initialROI ? toFields(initialROI) : null)
  const [preview, setPreview] = useState<ROI | null>(null)
  const [message, setMessage] = useState('')
  const [error, setError] = useState('')
  const containerRef = useRef<HTMLDivElement>(null)
  const dragRef = useRef<DragState | null>(null)
  const frameRef = useRef<number | null>(null)
  const saveVersion = useRef(0)

  const constrain = (value: ROI): ROI => {
    const x = clamp(Math.round(value.x), videoWidth - 1)
    const y = clamp(Math.round(value.y), videoHeight - 1)
    return {
      x, y,
      width: clamp(Math.round(value.width), videoWidth - x, 1),
      height: clamp(Math.round(value.height), videoHeight - y, 1),
    }
  }

  useEffect(() => {
    const next = initialROI ? constrain(initialROI) : null
    setROI(next)
    setDraft(next ? toFields(next) : null)
  }, [initialROI?.x, initialROI?.y, initialROI?.width, initialROI?.height, videoWidth, videoHeight])

  useEffect(() => () => {
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    dragRef.current = null
    saveVersion.current += 1
  }, [])

  const clearDrag = () => {
    const drag = dragRef.current
    dragRef.current = null
    if (frameRef.current !== null) cancelAnimationFrame(frameRef.current)
    frameRef.current = null
    setPreview(null)
    if (drag && containerRef.current?.hasPointerCapture(drag.pointerId)) {
      containerRef.current.releasePointerCapture(drag.pointerId)
    }
  }

  const commit = (next: ROI, adjusted = false) => {
    setROI(next)
    setDraft(toFields(next))
    setError('')
    setMessage('正在保存选区…')
    const version = ++saveVersion.current
    // Only completed selections are saved; pointer moves stay entirely in the browser.
    Promise.resolve().then(() => onROIChange(next)).then(() => {
      if (version === saveVersion.current) {
        setMessage(adjusted ? '已保存，超出画面的参数已自动调整。' : '选区已保存。')
      }
    }).catch(() => {
      if (version === saveVersion.current) {
        setMessage('')
        setError('选区保存失败，请点击“应用参数”重试。')
      }
    })
  }

  const updatePoint = (drag: DragState, event: PointerEvent<HTMLDivElement>) => {
    drag.endX = clamp((event.clientX - drag.bounds.left) * videoWidth / drag.bounds.width, videoWidth)
    drag.endY = clamp((event.clientY - drag.bounds.top) * videoHeight / drag.bounds.height, videoHeight)
  }

  const handlePointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || !event.isPrimary || dragRef.current) return
    const bounds = event.currentTarget.getBoundingClientRect()
    if (!bounds.width || !bounds.height) return
    event.preventDefault()
    event.currentTarget.focus({ preventScroll: true })
    event.currentTarget.setPointerCapture(event.pointerId)
    const drag: DragState = {
      pointerId: event.pointerId, bounds, startX: 0, startY: 0, endX: 0, endY: 0,
    }
    updatePoint(drag, event)
    drag.startX = drag.endX
    drag.startY = drag.endY
    dragRef.current = drag
    setPreview(dragBox(drag))
  }

  const handlePointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    updatePoint(drag, event)
    // Read layout once at drag start, then draw at most once per animation frame.
    if (frameRef.current === null) {
      frameRef.current = requestAnimationFrame(() => {
        frameRef.current = null
        if (dragRef.current) setPreview(dragBox(dragRef.current))
      })
    }
  }

  const handlePointerUp = (event: PointerEvent<HTMLDivElement>) => {
    const drag = dragRef.current
    if (!drag || drag.pointerId !== event.pointerId) return
    updatePoint(drag, event)
    const next = dragBox(drag)
    clearDrag()
    // A click without a visible drag keeps the previous selection.
    if (next.width * drag.bounds.width / videoWidth < 2 ||
        next.height * drag.bounds.height / videoHeight < 2) return
    commit(constrain(next))
  }

  const handleApply = (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault()
    if (!draft) return
    if (fields.some(({ key }) => !draft[key].trim() || !Number.isSafeInteger(Number(draft[key])))) {
      setError('请为 X、Y、宽度和高度填写整数。')
      return
    }
    const requested = {
      x: Number(draft.x), y: Number(draft.y), width: Number(draft.width), height: Number(draft.height),
    }
    const next = constrain(requested)
    commit(next, fields.some(({ key }) => next[key] !== requested[key]))
  }

  const selection = preview ?? roi
  const dirty = roi && draft && fields.some(({ key }) => draft[key] !== String(roi[key]))

  return (
    <div className="roi-selector">
      <div className="roi-label">拖拽选择谱面区域</div>
      <div
        ref={containerRef}
        className="roi-container"
        aria-label="乐谱区域框选，拖动绘制，退出键取消"
        tabIndex={0}
        style={{ width: displayWidth, aspectRatio: `${videoWidth} / ${videoHeight}` }}
        onPointerDown={handlePointerDown}
        onPointerMove={handlePointerMove}
        onPointerUp={handlePointerUp}
        onPointerCancel={(event) => { if (dragRef.current?.pointerId === event.pointerId) clearDrag() }}
        onLostPointerCapture={() => { if (dragRef.current) clearDrag() }}
        onKeyDown={(event) => {
          if (event.key === 'Escape') clearDrag()
          if (roi && ['ArrowLeft','ArrowRight','ArrowUp','ArrowDown'].includes(event.key)) {
            event.preventDefault()
            const step=event.shiftKey?10:1
            commit(constrain({...roi,x:roi.x+(event.key==='ArrowRight'?step:event.key==='ArrowLeft'?-step:0),
              y:roi.y+(event.key==='ArrowDown'?step:event.key==='ArrowUp'?-step:0)}))
          }
        }}
      >
        <img src={imageUrl} alt="谱面选区预览" draggable={false} />
        {selection && (
          <div className="roi-box" style={{
            left: `${selection.x / videoWidth * 100}%`,
            top: `${selection.y / videoHeight * 100}%`,
            width: `${selection.width / videoWidth * 100}%`,
            height: `${selection.height / videoHeight * 100}%`,
          }} />
        )}
      </div>
      <div className="roi-hint">拖动框选，松开保存 · Esc 取消</div>
      {roi && draft && (
        <form className="roi-editor" onSubmit={handleApply} noValidate>
          <div className="roi-fields">
            {fields.map(({ key, label }) => (
              <label key={key} className="floating-field">
                <span className="field-label">{label}</span>
                <input type="number" step="1" min={key === 'x' || key === 'y' ? 0 : 1}
                  max={key === 'x' ? videoWidth - 1 : key === 'y' ? videoHeight - 1 : key === 'width' ? videoWidth : videoHeight}
                  value={draft[key]} disabled={preview !== null}
                  onChange={(event) => { setDraft({ ...draft, [key]: event.target.value }); setError('') }} />
              </label>
            ))}
          </div>
          <div className="roi-editor-actions">
            <button className="btn" type="submit" disabled={preview !== null}>应用参数</button>
            <span className="roi-hint">{videoWidth} × {videoHeight} 像素</span>
          </div>
          {error ? <div className="roi-error" role="alert">{error}</div> : (
            <div className="roi-coords" role="status">
              {dirty ? '参数尚未应用。' : message || `当前选区：${roi.width} × ${roi.height} 像素`}
            </div>
          )}
        </form>
      )}
    </div>
  )
}
