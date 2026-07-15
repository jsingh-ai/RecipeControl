import * as echarts from 'echarts'
import { useEffect, useRef } from 'react'

export default function TrendChart({ series }: { series: any[] }) {
  const ref = useRef<HTMLDivElement>(null)
  useEffect(() => {
    if (!ref.current) return
    const chart = echarts.init(ref.current)
    chart.setOption({
      animation: false,
      tooltip: { trigger: 'axis' },
      legend: { textStyle: { color: '#e2e8f0' } },
      xAxis: { type: 'time', axisLabel: { color: '#cbd5e1' } },
      yAxis: { type: 'value', axisLabel: { color: '#cbd5e1' }, splitLine: { lineStyle: { color: '#334155' } } },
      series: series.filter((item) => item.data_type === 'numeric').map((item) => ({ name: item.display_name, type: 'line', connectNulls: false, showSymbol: true, data: item.points.map((point: any) => [point.minute_utc, point.missing ? null : Number(point.value)]) })),
    })
    return () => chart.dispose()
  }, [series])
  return <div ref={ref} className="h-64 w-full" role="img" aria-label="Trend chart leading to clicked time" />
}

