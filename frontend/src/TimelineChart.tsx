import * as echarts from 'echarts'
import { useEffect, useMemo, useRef, useState } from 'react'
import { api as requestApi, MinuteDetail, Segment, Timeline } from './api'
import { DisplayZone, formatTime } from './time'

export function segmentAppearance(segment: Segment): { color: string; text: string; pattern: string } {
  const pattern = ['DATA_GAP', 'INSUFFICIENT_HISTORY'].includes(segment.system_state) ? 'diagonal' : 'solid'
  const identity = segment.system_state === 'DATA_GAP' ? ' · Data Gap' : segment.system_state === 'INSUFFICIENT_HISTORY' ? ' · Insufficient History' : ''
  if (segment.quality_label === 'GOOD') return { color: '#22c55e', text: `✓ Good${identity}`, pattern }
  if (segment.quality_label === 'BAD') return { color: '#ef4444', text: `✕ Bad${identity}`, pattern }
  if (segment.quality_label === 'UNSURE') return { color: '#3b82f6', text: `? Unsure${identity}`, pattern }
  return { color: '#64748b', text: `○ Unlabeled${identity}`, pattern }
}

export function conditionExpression(condition: NonNullable<Timeline['conditions']>[number]): string {
  const symbol: Record<string, string> = { BELOW_MINIMUM: '<', ABOVE_MAXIMUM: '>', OUTSIDE_RANGE: 'outside', EQUALS: '=', NOT_EQUALS: '≠', INCREASE_BY: 'increases by', DECREASE_BY: 'decreases by' }
  const threshold = condition.operator === 'BELOW_MINIMUM' ? condition.minimum : condition.operator === 'ABOVE_MAXIMUM' ? condition.maximum : condition.operator === 'OUTSIDE_RANGE' ? `${condition.minimum}–${condition.maximum}` : ['INCREASE_BY', 'DECREASE_BY'].includes(condition.operator) ? `${condition.delta_amount} / ${condition.delta_window_minutes} min` : String(condition.comparison_value ?? '')
  return `${condition.display_name} ${symbol[condition.operator] ?? condition.operator.replaceAll('_', ' ')} ${threshold}${condition.duration_minutes ? ` · ${condition.duration_minutes} min` : ''}`
}

export function showCachedMinute(cache: Map<string, MinuteDetail>, minute: string, show: () => void): boolean {
  if (!cache.has(minute)) return false
  show()
  return true
}

function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]!)
}

function formatAxisTime(value: number, zone: DisplayZone): string {
  return new Intl.DateTimeFormat('en-US', {
    timeZone: zone === 'UTC' ? 'UTC' : 'America/Chicago',
    month: 'short',
    day: 'numeric',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  }).format(new Date(value))
}

export function hoverDataIndex(
  segments: Segment[],
  intervals: Timeline['condition_intervals'],
  conditionIds: number[],
  clicked: number,
  laneIndex: number,
): number | null {
  if (laneIndex === 0) {
    const segmentIndex = segments.findIndex((item) => Date.parse(item.start_utc) <= clicked && clicked < Date.parse(item.end_utc))
    return segmentIndex < 0 ? null : segmentIndex
  }
  const conditionId = conditionIds[laneIndex - 1]
  const intervalIndex = intervals.findIndex((item) => item.condition_id === conditionId && Date.parse(item.start_utc) <= clicked && clicked < Date.parse(item.end_utc))
  return intervalIndex < 0 ? null : segments.length + intervalIndex
}

export function conditionMinuteTooltip(
  condition: NonNullable<Timeline['conditions']>[number],
  detail: MinuteDetail,
  zone: DisplayZone,
): string {
  const evaluation = detail.conditions[String(condition.id)]
  if (!evaluation) return `${escapeHtml(conditionExpression(condition))}<br/>Exact-minute evaluation unavailable`
  const groupResult = condition.group_id == null ? 'unknown' : detail.groups[String(condition.group_id)]
  const reference = evaluation.delta_reference ? `<br/>Delta reference: ${escapeHtml(evaluation.delta_reference.value)} at ${escapeHtml(formatTime(evaluation.delta_reference.minute_utc, zone))}` : ''
  const sourceError = evaluation.source?.error_text ? ` · error ${escapeHtml(evaluation.source.error_text)}` : ''
  return `<strong>${escapeHtml(conditionExpression(condition))}</strong><br/>Minute: ${escapeHtml(formatTime(detail.minute_utc, zone))}<br/>Value: ${escapeHtml(evaluation.value === null ? 'Missing' : evaluation.value)}<br/>Raw matched: ${escapeHtml(evaluation.raw_matched)} · pending ${escapeHtml(evaluation.pending_progress.current)}/${escapeHtml(evaluation.pending_progress.required)} · qualified ${escapeHtml(evaluation.qualified_active)}<br/>Group ${escapeHtml(condition.group_id ?? '—')} (${escapeHtml(condition.group_operator ?? '—')}): ${escapeHtml(groupResult)} · root: ${escapeHtml(detail.root_expression_result)}<br/>Quality/status: ${escapeHtml(evaluation.source?.quality ?? '—')} / ${escapeHtml(evaluation.source?.status_code ?? '—')}${sourceError}${reference}`
}

type Props = {
  timeline: Timeline
  zone: DisplayZone
  onSelect: (segment: Segment, clickedUtc: string) => void
  autoFollow?: boolean
}

const SEGMENT_PAGE_SIZE = 20

export function SegmentNavigator({ segments, zone, onSelect }: Pick<Props, 'zone' | 'onSelect'> & { segments: Segment[] }) {
  const [query, setQuery] = useState('')
  const [page, setPage] = useState(0)
  const filtered = useMemo(() => {
    const normalized = query.trim().toLocaleLowerCase()
    if (!normalized) return segments
    return segments.filter((segment) => [segment.system_state, segmentAppearance(segment).text, segment.classification_name, formatTime(segment.start_utc, zone)].some((value) => String(value ?? '').toLocaleLowerCase().includes(normalized)))
  }, [query, segments, zone])
  const pageCount = Math.max(1, Math.ceil(filtered.length / SEGMENT_PAGE_SIZE))
  const visible = filtered.slice(page * SEGMENT_PAGE_SIZE, (page + 1) * SEGMENT_PAGE_SIZE)

  useEffect(() => setPage(0), [query, segments])

  return <details className="mt-4 rounded-xl border border-slate-700 bg-slate-950/50 p-3" open>
    <summary className="flex items-center justify-between gap-3 px-1 py-2 font-bold"><span>Accessible segment navigator</span><span className="badge badge-muted">{segments.length} segments</span></summary>
    <div className="mt-3 flex flex-wrap items-end gap-3 border-t border-slate-800 pt-3">
      <label className="min-w-56 flex-1">Search segments<input type="search" value={query} onChange={(event) => setQuery(event.target.value)} placeholder="State, label, classification, or time" /></label>
      <span className="text-xs text-slate-400">Showing {filtered.length ? page * SEGMENT_PAGE_SIZE + 1 : 0}–{Math.min((page + 1) * SEGMENT_PAGE_SIZE, filtered.length)} of {filtered.length}</span>
    </div>
    {visible.length ? <div className="mt-3 grid gap-2 sm:grid-cols-2 xl:grid-cols-4">{visible.map((segment) => <button key={segment.id} className="button-secondary flex items-center justify-between gap-3 text-left text-xs" onClick={() => { const midpoint = (Date.parse(segment.start_utc) + Date.parse(segment.end_utc)) / 2; onSelect(segment, new Date(Math.floor(midpoint / 60_000) * 60_000).toISOString()) }}><span><span className="block font-bold">{segmentAppearance(segment).text}</span><span className="text-slate-400">{segment.system_state} · {formatTime(segment.start_utc, zone)}</span></span><span aria-hidden="true">→</span></button>)}</div> : <p className="mt-3 rounded-lg border border-dashed border-slate-700 p-5 text-center text-sm text-slate-400">No segments match this search.</p>}
    <div className="mt-3 flex items-center justify-end gap-2"><button className="button-secondary" disabled={page === 0} onClick={() => setPage((current) => Math.max(0, current - 1))}>Previous</button><span className="text-xs text-slate-400">Page {Math.min(page + 1, pageCount)} of {pageCount}</span><button className="button-secondary" disabled={page + 1 >= pageCount} onClick={() => setPage((current) => Math.min(pageCount - 1, current + 1))}>Next</button></div>
  </details>
}

export default function TimelineChart({ timeline, zone, onSelect, autoFollow = false }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const [compactLabels, setCompactLabels] = useState(false)
  const segments = timeline.segments
  const conditionIds = useMemo(() => [...new Set(timeline.condition_intervals.map((item) => item.condition_id))], [timeline])

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    const conditionById = new Map((timeline.conditions ?? []).map((item) => [item.id, item]))
    const lanes = ['Primary segments', ...conditionIds.map((id) => conditionById.has(id) ? conditionExpression(conditionById.get(id)!) : `Condition ${id}`)]
    const minuteCache = new Map<string, MinuteDetail>()
    let hoveredMinute: string | null = null
    let hoverTimer: number | undefined
    const conditionColors: Record<string, string> = { FALSE: '#334155', PENDING: '#facc15', ACTIVE: '#f97316', MISSING: '#7c3aed', INSUFFICIENT_HISTORY: '#d97706' }
    const primaryData = segments.map((segment) => ({
      value: [0, Date.parse(segment.start_utc), Date.parse(segment.end_utc), segment.id],
      itemStyle: { color: segmentAppearance(segment).color, decal: ['DATA_GAP', 'INSUFFICIENT_HISTORY'].includes(segment.system_state) ? { symbol: 'rect', dashArrayX: [1, 0], dashArrayY: [4, 3], rotation: -0.7, color: 'rgba(255,255,255,.45)' } : undefined, borderColor: segment.active_live ? '#fff' : 'transparent', borderType: segment.active_live ? 'dashed' : 'solid', borderWidth: 2 },
    }))
    const conditionData = timeline.condition_intervals.map((item) => ({
      value: [conditionIds.indexOf(item.condition_id) + 1, Date.parse(item.start_utc), Date.parse(item.end_utc), item.id],
      itemStyle: { color: conditionColors[item.state] ?? '#334155' },
    }))
    const renderedData = [...primaryData, ...conditionData]
    chart.setOption({
      animation: false,
      grid: { left: compactLabels ? 112 : Math.min(320, Math.max(190, (ref.current?.clientWidth ?? 1200) * 0.24)), right: 24, top: 24, bottom: 70 },
      xAxis: { type: 'time', splitNumber: 6, axisLabel: { color: '#cbd5e1', hideOverlap: true, formatter: (value: number) => formatAxisTime(value, zone) } },
      yAxis: { type: 'category', data: lanes, inverse: true, axisLabel: { color: '#e2e8f0', width: compactLabels ? 88 : 286, overflow: 'truncate', formatter: (value: string) => compactLabels && value.length > 16 ? value.slice(0, 14) + '…' : value } },
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }, { type: 'slider', xAxisIndex: 0, bottom: 12, height: 26 }],
      tooltip: {
        formatter: (params: any) => {
          const [lane, start, end, id] = params.value
          const detail = hoveredMinute ? minuteCache.get(hoveredMinute) : undefined
          if (lane !== 0) {
            const condition = conditionById.get(conditionIds[lane - 1])
            return condition && detail ? conditionMinuteTooltip(condition, detail, zone) : `${lanes[lane]}<br/>${formatTime(new Date(start).toISOString(), zone)} – ${formatTime(new Date(end).toISOString(), zone)}<br/>Loading exact minute…`
          }
          const segment = segments.find((item) => item.id === id)!
          const evaluations = Object.values(detail?.conditions ?? {}).map((item) => `${escapeHtml(item.display_name)} (#${item.condition_id}): ${escapeHtml(item.value)} · ${escapeHtml(item.operator)} · raw ${escapeHtml(item.raw_matched)} · ${escapeHtml(item.pending_progress.current)}/${escapeHtml(item.pending_progress.required)} · qualified ${escapeHtml(item.qualified_active)}${item.delta_reference ? ` · reference ${escapeHtml(item.delta_reference.value)} at ${escapeHtml(item.delta_reference.minute_utc)}` : ''} · quality ${escapeHtml(item.source?.quality ?? '—')} / ${escapeHtml(item.source?.status_code ?? '—')}`).join('<br/>')
          const duration = Math.round((Date.parse(segment.end_utc) - Date.parse(segment.start_utc)) / 60_000)
          const activeNames = Object.values(detail?.conditions ?? {}).filter((item) => detail?.active_condition_ids.includes(item.condition_id)).map((item) => item.display_name).join(', ')
          return `<strong>${escapeHtml(segmentAppearance(segment).text)}</strong><br/>${escapeHtml(segment.system_state)} · ${duration} minutes<br/>${escapeHtml(formatTime(segment.start_utc, zone))} – ${escapeHtml(formatTime(segment.end_utc, zone))}<br/>Hovered minute: ${escapeHtml(hoveredMinute ? formatTime(hoveredMinute, zone) : 'move within segment')}<br/>Classification: ${escapeHtml(segment.classification_name || 'none')}<br/>Active reasons: ${escapeHtml(activeNames || 'none')}<br/>Groups: ${escapeHtml(JSON.stringify(detail?.groups ?? {}))} · root ${escapeHtml(detail?.root_expression_result)}<br/>Missing: ${escapeHtml(detail?.missing_tag_ids.join(', ') || 'none')}<br/>Training: ${escapeHtml(detail?.training_eligible ? 'eligible' : detail?.training_ineligibility_reason ?? 'loading exact minute…')}<br/>${evaluations}`
        },
      },
      series: [{
        type: 'custom',
        encode: { x: [1, 2], y: 0 },
        data: renderedData,
        renderItem: (params: any, api: any) => {
          const lane = api.value(0)
          const start = api.coord([api.value(1), lane])
          const end = api.coord([api.value(2), lane])
          const height = api.size([0, 1])[1] * 0.62
          const itemStyle = renderedData[params.dataIndex]?.itemStyle as any
          return { type: 'rect', shape: echarts.graphic.clipRectByRect({ x: start[0], y: start[1] - height / 2, width: Math.max(1, end[0] - start[0]), height }, params.coordSys), style: { ...api.visual('style'), fill: itemStyle?.color, stroke: itemStyle?.borderColor, lineWidth: itemStyle?.borderWidth, lineDash: itemStyle?.borderType === 'dashed' ? [6, 4] : undefined, decal: itemStyle?.decal } }
        },
      }],
    })
    const click = (event: any) => {
      if (!chart.containPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY])) return
      const converted = chart.convertFromPixel({ xAxisIndex: 0 }, event.offsetX) as number
      const clicked = Math.floor(converted / 60_000) * 60_000
      const segment = segments.find((item) => Date.parse(item.start_utc) <= clicked && clicked < Date.parse(item.end_utc))
      if (segment) onSelect(segment, new Date(clicked).toISOString())
    }
    chart.getZr().on('click', click)
    const hover = (event: any) => {
      if (!chart.containPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY])) return
      const converted = chart.convertFromPixel({ gridIndex: 0 }, [event.offsetX, event.offsetY]) as [number, number | string]
      const clicked = Math.floor(converted[0] / 60_000) * 60_000
      const laneIndex = typeof converted[1] === 'number' ? Math.round(converted[1]) : lanes.indexOf(String(converted[1]))
      const dataIndex = hoverDataIndex(segments, timeline.condition_intervals, conditionIds, clicked, laneIndex)
      if (dataIndex == null) return
      hoveredMinute = new Date(clicked).toISOString()
      if (showCachedMinute(minuteCache, hoveredMinute, () => chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex }))) return
      window.clearTimeout(hoverTimer)
      hoverTimer = window.setTimeout(() => {
        const requestedMinute = hoveredMinute!
        requestApi<MinuteDetail>(`/analyses/${timeline.analysis.id}/minutes/${encodeURIComponent(requestedMinute)}`).then((detail) => { minuteCache.set(requestedMinute, detail); if (hoveredMinute === requestedMinute) chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex }) }).catch(() => undefined)
      }, 150)
    }
    chart.getZr().on('mousemove', hover)
    if (autoFollow && segments.length) chart.dispatchAction({ type: 'dataZoom', start: 80, end: 100 })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => { window.clearTimeout(hoverTimer); window.removeEventListener('resize', resize); chart.getZr().off('click', click); chart.getZr().off('mousemove', hover); chart.dispose() }
  }, [timeline, zone, conditionIds, segments, onSelect, autoFollow, compactLabels])

  return <div>
    <div className="mb-2 flex flex-wrap items-center justify-between gap-2"><div><h2 className="font-bold">Primary and condition lanes</h2><p className="text-xs text-slate-400">Scroll to zoom · drag to move · select any minute for detail</p></div><button className="button-secondary text-xs" aria-pressed={compactLabels} onClick={() => setCompactLabels((value) => !value)}>{compactLabels ? 'Expand condition labels' : 'Compact condition labels'}</button></div>
    <div ref={ref} className="h-[350px] w-full sm:h-[420px] 2xl:h-[520px]" role="img" aria-label="Scrollable primary and condition timeline lanes" />
    <SegmentNavigator segments={segments} zone={zone} onSelect={onSelect} />
  </div>
}
