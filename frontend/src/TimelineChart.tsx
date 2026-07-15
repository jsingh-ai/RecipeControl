import * as echarts from 'echarts'
import { useEffect, useMemo, useRef } from 'react'
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

function expression(condition: NonNullable<Timeline['conditions']>[number]): string {
  const threshold = condition.operator === 'BELOW_MINIMUM' ? condition.minimum : condition.operator === 'ABOVE_MAXIMUM' ? condition.maximum : condition.operator === 'OUTSIDE_RANGE' ? `${condition.minimum}–${condition.maximum}` : ['INCREASE_BY', 'DECREASE_BY'].includes(condition.operator) ? `${condition.delta_amount} / ${condition.delta_window_minutes} min` : String(condition.comparison_value ?? '')
  return `${condition.display_name} · ${condition.operator.replaceAll('_', ' ')} ${threshold}${condition.duration_minutes ? ` · ${condition.duration_minutes} min` : ''}`
}

function escapeHtml(value: unknown): string {
  return String(value ?? '').replace(/[&<>'"]/g, (character) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', "'": '&#39;', '"': '&quot;' })[character]!)
}

type Props = {
  timeline: Timeline
  zone: DisplayZone
  onSelect: (segment: Segment, clickedUtc: string) => void
  autoFollow?: boolean
}

export default function TimelineChart({ timeline, zone, onSelect, autoFollow = false }: Props) {
  const ref = useRef<HTMLDivElement>(null)
  const segments = timeline.segments
  const conditionIds = useMemo(() => [...new Set(timeline.condition_intervals.map((item) => item.condition_id))], [timeline])

  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    const conditionById = new Map((timeline.conditions ?? []).map((item) => [item.id, item]))
    const lanes = ['Primary segments', ...conditionIds.map((id) => conditionById.has(id) ? expression(conditionById.get(id)!) : `Condition ${id}`)]
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
    chart.setOption({
      animation: false,
      grid: { left: 310, right: 24, top: 24, bottom: 70 },
      xAxis: { type: 'time', axisLabel: { color: '#cbd5e1', formatter: (value: number) => formatTime(new Date(value).toISOString(), zone) } },
      yAxis: { type: 'category', data: lanes, inverse: true, axisLabel: { color: '#e2e8f0' } },
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }, { type: 'slider', xAxisIndex: 0, bottom: 12, height: 26 }],
      tooltip: {
        formatter: (params: any) => {
          const [lane, start, end, id] = params.value
          if (lane !== 0) return `${lanes[lane]}<br/>${formatTime(new Date(start).toISOString(), zone)} – ${formatTime(new Date(end).toISOString(), zone)}`
          const segment = segments.find((item) => item.id === id)!
          const detail = hoveredMinute ? minuteCache.get(hoveredMinute) : undefined
          const evaluations = Object.values(detail?.conditions ?? {}).map((item) => `${escapeHtml(item.display_name)} (#${item.condition_id}): ${escapeHtml(item.value)} · ${escapeHtml(item.operator)} · raw ${escapeHtml(item.raw_matched)} · ${escapeHtml(item.pending_progress.current)}/${escapeHtml(item.pending_progress.required)} · qualified ${escapeHtml(item.qualified_active)}${item.delta_reference ? ` · reference ${escapeHtml(item.delta_reference.value)} at ${escapeHtml(item.delta_reference.minute_utc)}` : ''} · quality ${escapeHtml(item.source?.quality ?? '—')} / ${escapeHtml(item.source?.status_code ?? '—')}`).join('<br/>')
          const duration = Math.round((Date.parse(segment.end_utc) - Date.parse(segment.start_utc)) / 60_000)
          return `<strong>${escapeHtml(segmentAppearance(segment).text)}</strong><br/>${escapeHtml(segment.system_state)} · ${duration} minutes<br/>${escapeHtml(formatTime(segment.start_utc, zone))} – ${escapeHtml(formatTime(segment.end_utc, zone))}<br/>Hovered minute: ${escapeHtml(hoveredMinute ? formatTime(hoveredMinute, zone) : 'move within segment')}<br/>Classification: ${escapeHtml(segment.classification_name || 'none')}<br/>Active reasons: ${escapeHtml(detail?.active_condition_ids.join(', ') || 'none')}<br/>Groups: ${escapeHtml(JSON.stringify(detail?.groups ?? {}))} · root ${escapeHtml(detail?.root_expression_result)}<br/>Missing: ${escapeHtml(detail?.missing_tag_ids.join(', ') || 'none')}<br/>Training: ${escapeHtml(detail?.training_eligible ? 'eligible' : detail?.training_ineligibility_reason ?? 'loading exact minute…')}<br/>${evaluations}`
        },
      },
      series: [{
        type: 'custom',
        encode: { x: [1, 2], y: 0 },
        data: [...primaryData, ...conditionData],
        renderItem: (params: any, api: any) => {
          const lane = api.value(0)
          const start = api.coord([api.value(1), lane])
          const end = api.coord([api.value(2), lane])
          const height = api.size([0, 1])[1] * 0.62
          return { type: 'rect', shape: echarts.graphic.clipRectByRect({ x: start[0], y: start[1] - height / 2, width: Math.max(1, end[0] - start[0]), height }, params.coordSys), style: api.visual('style') }
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
      const converted = chart.convertFromPixel({ xAxisIndex: 0 }, event.offsetX) as number
      const clicked = Math.floor(converted / 60_000) * 60_000
      const segmentIndex = segments.findIndex((item) => Date.parse(item.start_utc) <= clicked && clicked < Date.parse(item.end_utc))
      if (segmentIndex < 0) return
      hoveredMinute = new Date(clicked).toISOString()
      if (minuteCache.has(hoveredMinute)) return
      window.clearTimeout(hoverTimer)
      hoverTimer = window.setTimeout(() => {
        const requestedMinute = hoveredMinute!
        requestApi<MinuteDetail>(`/analyses/${timeline.analysis.id}/minutes/${encodeURIComponent(requestedMinute)}`).then((detail) => { minuteCache.set(requestedMinute, detail); if (hoveredMinute === requestedMinute) chart.dispatchAction({ type: 'showTip', seriesIndex: 0, dataIndex: segmentIndex }) }).catch(() => undefined)
      }, 150)
    }
    chart.getZr().on('mousemove', hover)
    if (autoFollow && segments.length) chart.dispatchAction({ type: 'dataZoom', start: 80, end: 100 })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => { window.clearTimeout(hoverTimer); window.removeEventListener('resize', resize); chart.getZr().off('click', click); chart.getZr().off('mousemove', hover); chart.dispose() }
  }, [timeline, zone, conditionIds, segments, onSelect, autoFollow])

  return <div>
    <div ref={ref} className="h-[420px] w-full" role="img" aria-label="Scrollable primary and condition timeline lanes" />
    <div className="flex flex-wrap gap-2" aria-label="Keyboard segment list">
      {segments.map((segment) => <button key={segment.id} className="button-secondary text-xs" onClick={() => { const midpoint = (Date.parse(segment.start_utc) + Date.parse(segment.end_utc)) / 2; onSelect(segment, new Date(Math.floor(midpoint / 60_000) * 60_000).toISOString()) }}>{segmentAppearance(segment).text} · {formatTime(segment.start_utc, zone)}</button>)}
    </div>
  </div>
}
