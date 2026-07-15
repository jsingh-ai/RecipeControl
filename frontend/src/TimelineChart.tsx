import * as echarts from 'echarts'
import { useEffect, useMemo, useRef } from 'react'
import { Segment, Timeline } from './api'
import { DisplayZone, formatTime } from './time'

export function segmentAppearance(segment: Segment): { color: string; text: string; pattern: string } {
  if (segment.system_state === 'DATA_GAP') return { color: '#7c3aed', text: 'Data Gap · excluded', pattern: 'diagonal' }
  if (segment.system_state === 'INSUFFICIENT_HISTORY') return { color: '#d97706', text: 'Insufficient History · excluded', pattern: 'diagonal' }
  if (segment.quality_label === 'GOOD') return { color: '#22c55e', text: '✓ Good', pattern: 'solid' }
  if (segment.quality_label === 'BAD') return { color: '#ef4444', text: '✕ Bad', pattern: 'solid' }
  if (segment.quality_label === 'UNSURE') return { color: '#3b82f6', text: '? Unsure', pattern: 'solid' }
  return { color: '#64748b', text: '○ Unlabeled', pattern: 'solid' }
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
    const lanes = ['Primary segments', ...conditionIds.map((id) => `Condition ${id}`)]
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
      grid: { left: 130, right: 24, top: 24, bottom: 70 },
      xAxis: { type: 'time', axisLabel: { color: '#cbd5e1', formatter: (value: number) => formatTime(new Date(value).toISOString(), zone) } },
      yAxis: { type: 'category', data: lanes, inverse: true, axisLabel: { color: '#e2e8f0' } },
      dataZoom: [{ type: 'inside', xAxisIndex: 0, filterMode: 'none' }, { type: 'slider', xAxisIndex: 0, bottom: 12, height: 26 }],
      tooltip: {
        formatter: (params: any) => {
          const [lane, start, end, id] = params.value
          if (lane !== 0) return `${lanes[lane]}<br/>${formatTime(new Date(start).toISOString(), zone)} – ${formatTime(new Date(end).toISOString(), zone)}`
          const segment = segments.find((item) => item.id === id)!
          const boundary = timeline.boundaries.find((item) => Date.parse(item.boundary_utc) === start)
          const evaluations = Object.values(boundary?.context?.conditions ?? {}).map((item: any) => `${escapeHtml(item.display_name)}: ${escapeHtml(item.value)} · raw ${escapeHtml(item.raw_predicate)} · ${escapeHtml(item.lane_state)}${item.delta_reference ? ` · reference ${escapeHtml(item.delta_reference.value)} at ${escapeHtml(item.delta_reference.timestamp)}` : ''}`).join('<br/>')
          const duration = Math.round((Date.parse(segment.end_utc) - Date.parse(segment.start_utc)) / 60_000)
          return `<strong>${escapeHtml(segmentAppearance(segment).text)}</strong><br/>${escapeHtml(segment.system_state)} · ${duration} minutes<br/>${escapeHtml(formatTime(segment.start_utc, zone))} – ${escapeHtml(formatTime(segment.end_utc, zone))}<br/>Classification: ${escapeHtml(segment.classification_name || 'none')}<br/>Reasons: ${escapeHtml(segment.contributing_condition_ids.join(', ') || 'none')}<br/>${escapeHtml(boundary?.explanation ?? '')}<br/>Groups: ${escapeHtml(JSON.stringify(boundary?.context?.groups ?? {}))} · root ${escapeHtml(boundary?.context?.root_expression_result)}<br/>Missing: ${escapeHtml((boundary?.context?.missing_variables ?? []).join(', ') || 'none')}<br/>${evaluations}`
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
    if (autoFollow && segments.length) chart.dispatchAction({ type: 'dataZoom', start: 80, end: 100 })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => { window.removeEventListener('resize', resize); chart.getZr().off('click', click); chart.dispose() }
  }, [timeline, zone, conditionIds, segments, onSelect, autoFollow])

  return <div>
    <div ref={ref} className="h-[420px] w-full" role="img" aria-label="Scrollable primary and condition timeline lanes" />
    <div className="flex flex-wrap gap-2" aria-label="Keyboard segment list">
      {segments.map((segment) => <button key={segment.id} className="button-secondary text-xs" onClick={() => onSelect(segment, new Date((Date.parse(segment.start_utc) + Date.parse(segment.end_utc)) / 2).toISOString())}>{segmentAppearance(segment).text} · {formatTime(segment.start_utc, zone)}</button>)}
    </div>
  </div>
}
