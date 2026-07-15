import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

type TrendPoint = { minute_utc: string; value: unknown; missing: boolean }
type TrendSeries = { tag_id: string; display_name: string; data_type: string; units?: string | null; points: TrendPoint[] }

function NumericTrend({ item }: { item: TrendSeries }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chart.setOption({
      animation: false,
      grid: { left: 58, right: 20, top: 24, bottom: 42 },
      tooltip: { trigger: 'axis', valueFormatter: (value: unknown) => value == null ? 'Missing' : String(value) + (item.units ? ' ' + item.units : '') },
      xAxis: { type: 'time', axisLabel: { color: '#94a3b8', hideOverlap: true }, axisLine: { lineStyle: { color: '#334155' } } },
      yAxis: { type: 'value', name: item.units || undefined, nameTextStyle: { color: '#94a3b8' }, axisLabel: { color: '#cbd5e1' }, splitLine: { lineStyle: { color: '#1e293b' } }, scale: true },
      series: [{ name: item.display_name, type: 'line', connectNulls: false, showSymbol: item.points.length < 90, symbolSize: 5, lineStyle: { width: 2, color: '#22d3ee' }, itemStyle: { color: '#67e8f9' }, areaStyle: { color: 'rgba(34,211,238,.08)' }, data: item.points.map((point) => [point.minute_utc, point.missing ? null : Number(point.value)]) }],
    })
    const resize = () => chart.resize()
    window.addEventListener('resize', resize)
    return () => { window.removeEventListener('resize', resize); chart.dispose() }
  }, [item])
  return <figure className="panel-subtle min-w-0"><figcaption className="mb-2 flex items-baseline justify-between gap-2"><strong>{item.display_name}</strong><span className="text-xs text-slate-400">{item.units || 'unitless'} · independent scale</span></figcaption><div ref={ref} className="h-52 w-full" role="img" aria-label={item.display_name + ' numeric trend with independent y-axis'} /></figure>
}

export default function TrendChart({ series }: { series: TrendSeries[] }) {
  const numeric = series.filter((item) => item.data_type === 'numeric')
  if (!numeric.length) return <div className="rounded-xl border border-dashed border-slate-700 p-5 text-center text-sm text-slate-400">No numeric trend series selected.</div>
  return <div className="grid gap-3 xl:grid-cols-2">{numeric.map((item) => <NumericTrend key={item.tag_id} item={item} />)}</div>
}
