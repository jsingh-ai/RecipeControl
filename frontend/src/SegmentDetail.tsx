import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useMemo, useState } from 'react'
import { api, MinuteDetail, RuleVersion, Segment, Tag } from './api'
import TagSearch from './TagSearch'
import { conditionExpression, segmentAppearance } from './TimelineChart'
import { DisplayZone, formatTime } from './time'
import TrendChart from './TrendChart'
import { Alert } from './ui'

type Props = { segment: Segment; clickedUtc: string; analysisId: number; machineId: number; version: RuleVersion; zone: DisplayZone; liveId?: number; onClose: () => void }
type Classification = { id: number; name: string; active: boolean }

export default function SegmentDetail({ segment, clickedUtc, analysisId, machineId, version, zone, liveId, onClose }: Props) {
  const queryClient = useQueryClient()
  const conditionTags = useMemo(() => [...new Set(version.groups.flatMap((group) => group.conditions.map((item) => item.source_tag_key)))], [version])
  const [displayed, setDisplayed] = useState(segment)
  const [temporary, setTemporary] = useState<Tag[]>([])
  const [lookback, setLookback] = useState(15)
  const [quality, setQuality] = useState(segment.quality_label ?? '')
  const [classificationId, setClassificationId] = useState(segment.classification_id?.toString() ?? '')
  const [note, setNote] = useState(segment.note ?? '')
  const [newClassification, setNewClassification] = useState('')
  const [feedback, setFeedback] = useState('')

  useEffect(() => {
    setDisplayed(segment)
    setTemporary([])
    setQuality(segment.quality_label ?? '')
    setClassificationId(segment.classification_id?.toString() ?? '')
    setNote(segment.note ?? '')
    setNewClassification('')
    setFeedback('')
  }, [analysisId, segment])

  const classifications = useQuery({ queryKey: ['classifications', version.id], queryFn: () => api<Classification[]>('/rule-versions/' + version.id + '/classifications?include_inactive=true') })
  const classificationChoices = useMemo(() => classifications.data?.filter((item) => item.active || item.id === displayed.classification_id) ?? [], [classifications.data, displayed.classification_id])
  const selectedClassification = classificationChoices.find((item) => String(item.id) === classificationId)
  const selectedTags = [...conditionTags, ...temporary.map((tag) => tag.key)]
  const conditionsById = useMemo(() => new Map(version.groups.flatMap((group) => group.conditions).map((condition) => [condition.id, condition])), [version])
  const trendPath = '/analyses/' + analysisId + '/trends?clicked_utc=' + encodeURIComponent(clickedUtc) + '&lookback_minutes=' + lookback + selectedTags.map((tag) => '&tag_ids=' + encodeURIComponent(tag)).join('')
  const trends = useQuery({ queryKey: ['trends', analysisId, clickedUtc, lookback, selectedTags], queryFn: () => api<any>(trendPath) })
  const minute = useQuery({ queryKey: ['minute', analysisId, clickedUtc], queryFn: () => api<MinuteDetail>('/analyses/' + analysisId + '/minutes/' + encodeURIComponent(clickedUtc)) })
  const latest = useQuery({ queryKey: ['latest', liveId], queryFn: () => api<any>('/live-sessions/' + liveId + '/latest'), enabled: Boolean(liveId), refetchInterval: 15_000 })
  const activeReasons = Object.values(minute.data?.conditions ?? {}).filter((item) => minute.data?.active_condition_ids?.includes(item.condition_id))
  const appearance = segmentAppearance(displayed)
  const duration = Math.round((Date.parse(displayed.end_utc) - Date.parse(displayed.start_utc)) / 60_000)

  const save = useMutation({
    mutationFn: () => {
      if (displayed.analysis_id !== analysisId) throw new Error('This segment is not part of the loaded analysis.')
      return api<Segment>('/analyses/' + analysisId + '/segments/' + displayed.id, { method: 'PATCH', body: JSON.stringify({ quality_label: quality || null, classification_id: classificationId ? Number(classificationId) : null, note: note || null }) })
    },
    onSuccess: (updated) => {
      setDisplayed(updated)
      setQuality(updated.quality_label ?? '')
      setClassificationId(updated.classification_id?.toString() ?? '')
      setNote(updated.note ?? '')
      setFeedback('Segment annotation saved.')
      queryClient.invalidateQueries({ queryKey: ['timeline', analysisId] })
      queryClient.invalidateQueries({ queryKey: ['minute', analysisId] })
    },
    onError: (error) => setFeedback(error.message),
  })
  const createClassification = useMutation({ mutationFn: () => api<Classification>('/rule-versions/' + version.id + '/classifications', { method: 'POST', body: JSON.stringify({ name: newClassification }) }), onSuccess: (created) => { setClassificationId(String(created.id)); setNewClassification(''); queryClient.invalidateQueries({ queryKey: ['classifications', version.id] }) } })
  const removeClassification = useMutation({ mutationFn: (id: number) => api('/classifications/' + id, { method: 'DELETE' }), onSuccess: (_result, retiredId) => { if (displayed.classification_id !== retiredId) setClassificationId(''); queryClient.invalidateQueries({ queryKey: ['classifications', version.id] }) } })

  return <>
    <div className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm" aria-hidden="true" onClick={onClose} />
    <aside className="fixed inset-y-0 right-0 z-40 w-full max-w-3xl overflow-y-auto border-l border-slate-700 bg-slate-950 shadow-2xl shadow-black" aria-label="Segment detail">
      <header className="sticky top-0 z-10 flex items-start justify-between gap-4 border-b border-slate-800 bg-slate-950/95 px-5 py-4 backdrop-blur sm:px-7">
        <div><p className="section-kicker">Segment review</p><div className="mt-1 flex flex-wrap items-center gap-2"><h2 className="text-2xl font-black">{displayed.system_state.replaceAll('_', ' ')}</h2><span className="badge" style={{ borderColor: appearance.color, color: appearance.color }}>{appearance.text}</span></div></div>
        <button className="button-secondary" onClick={onClose}>Close</button>
      </header>

      <div className="space-y-7 p-5 sm:p-7">
        <section aria-labelledby="operator-summary-heading">
          <p className="section-kicker">Operator summary</p>
          <h3 id="operator-summary-heading" className="mt-1 text-xl font-bold">What happened at this minute</h3>
          <dl className="mt-3 grid gap-3 rounded-xl border border-slate-800 bg-slate-900/80 p-4 text-sm sm:grid-cols-2">
            <div><dt className="text-slate-400">Hovered minute</dt><dd data-testid="clicked-time" className="mt-1 font-semibold">{formatTime(clickedUtc, zone)}</dd></div>
            <div><dt className="text-slate-400">Segment duration</dt><dd className="mt-1 font-semibold">{duration} minutes</dd></div>
            <div className="sm:col-span-2"><dt className="text-slate-400">Segment window</dt><dd className="mt-1">{formatTime(displayed.start_utc, zone)} – {formatTime(displayed.end_utc, zone)}</dd></div>
            <div className="sm:col-span-2"><dt className="text-slate-400">Active break reasons</dt><dd className="mt-1 font-semibold">{activeReasons.map((item) => { const condition = conditionsById.get(item.condition_id); return condition ? conditionExpression({ ...condition, id: condition.id ?? item.condition_id, tag_id: condition.source_tag_key, display_name: condition.source_display_name, raw_data_type: condition.source_raw_data_type ?? null, data_kind: condition.source_data_type }) : item.display_name }).join(', ') || 'No duration-qualified break condition at this minute'}</dd></div>
            <div><dt className="text-slate-400">Classification</dt><dd className="mt-1">{displayed.classification_name || 'None'}</dd></div>
            <div><dt className="text-slate-400">Training use</dt><dd className="mt-1">{minute.data?.training_eligible ? '✓ Eligible' : minute.data?.training_ineligibility_reason ?? 'Not eligible'}</dd></div>
          </dl>
          {['DATA_GAP', 'INSUFFICIENT_HISTORY'].includes(displayed.system_state) && <div className="mt-3"><Alert tone="warning">This keeps its system pattern over any Good, Bad, or Unsure label and remains training-ineligible.</Alert></div>}
        </section>

        <section className="space-y-4 border-t border-slate-800 pt-6" aria-labelledby="annotation-heading">
          <div><p className="section-kicker">Annotation</p><h3 id="annotation-heading" className="mt-1 text-xl font-bold">Quality, classification, and note</h3></div>
          <fieldset><legend className="mb-2 text-sm font-bold text-slate-300">Quality label</legend><div className="grid gap-2 sm:grid-cols-4">{[['GOOD', '✓ Good'], ['BAD', '✕ Bad'], ['UNSURE', '? Unsure']].map(([value, label]) => <label className={'cursor-pointer flex-row items-center rounded-xl border p-3 ' + (quality === value ? 'border-cyan-400 bg-cyan-950/50' : 'border-slate-700 bg-slate-900')} key={value}><input className="size-4 min-h-0 w-4" type="radio" name="quality" value={value} checked={quality === value} onChange={() => setQuality(value)} /> {label}</label>)}<button type="button" className="button-secondary" onClick={() => setQuality('')}>○ Unlabeled</button></div></fieldset>
          <div className="grid gap-3 md:grid-cols-2"><label>Classification<select aria-label="Classification" value={classificationId} onChange={(event) => setClassificationId(event.target.value)}><option value="">None</option>{classificationChoices.map((item) => <option key={item.id} value={item.id}>{item.name}{item.active ? '' : ' (Retired)'}</option>)}</select></label><div className="flex items-end gap-2"><label className="flex-1">New classification<input value={newClassification} onChange={(event) => setNewClassification(event.target.value)} /></label><button className="button-secondary" disabled={!newClassification.trim() || createClassification.isPending} onClick={() => createClassification.mutate()}>Add</button></div>{classificationId && <button className="button-secondary" type="button" onClick={() => setClassificationId('')}>Clear classification</button>}{selectedClassification?.active && <button className="button-destructive" disabled={removeClassification.isPending} onClick={() => removeClassification.mutate(selectedClassification.id)}>Retire from future choices</button>}</div>
          <label>Notes<textarea maxLength={4000} rows={4} value={note} onChange={(event) => setNote(event.target.value)} placeholder="Record the operator-observed reason, action, or context…" /></label>
          <div className="flex flex-wrap gap-2"><button className="button-primary" disabled={save.isPending || displayed.analysis_id !== analysisId} onClick={() => { setFeedback(''); save.mutate() }}>{save.isPending ? 'Saving…' : 'Save segment label'}</button><button type="button" className="button-secondary" onClick={() => setNote('')}>Clear note</button></div>
          {feedback && <Alert tone={save.isError ? 'error' : 'success'}>{feedback}</Alert>}
        </section>

        <section className="space-y-4 border-t border-slate-800 pt-6" aria-labelledby="trends-heading">
          <div className="flex flex-wrap items-end justify-between gap-3"><div><p className="section-kicker">Context</p><h3 id="trends-heading" className="mt-1 text-xl font-bold">Values and trends</h3><p className="text-sm text-slate-400">Each numeric variable uses an independent y-axis so incompatible units are never overlaid.</p></div><label>Lookback minutes<input aria-label="Trend lookback minutes" className="w-28" type="number" min="1" step="1" value={lookback} onChange={(event) => setLookback(Math.max(1, Number(event.target.value)))} /></label></div>
          {trends.isLoading && <div className="skeleton h-52 w-full" role="status" aria-label="Loading trends" />}
          {trends.isError && <Alert tone="error">Trend history is unavailable for this minute.</Alert>}
          <div className="grid gap-2 sm:grid-cols-2">{trends.data?.series.map((item: any) => { const point = item.points[item.points.length - 1]; const observed = latest.data?.values.find((value: any) => value.tag_id === item.tag_id); return <article className="panel-subtle" key={item.tag_id}><h4 className="font-semibold">{item.display_name}</h4><p className="mt-1 text-lg">{point?.missing ? 'Missing' : String(point?.value ?? '—') + (item.units ? ' ' + item.units : '')}</p>{observed && <p className="text-xs text-cyan-300">Latest: {String(observed.value)} at {formatTime(observed.sampled_at_utc, zone)}</p>}{temporary.some((tag) => tag.key === item.tag_id) && <button className="button-destructive mt-2 text-xs" onClick={() => setTemporary((current) => current.filter((tag) => tag.key !== item.tag_id))}>Remove</button>}</article> })}</div>
          <TrendChart series={trends.data?.series ?? []} />
          <div className="space-y-2">{trends.data?.series.filter((item: any) => item.data_type !== 'numeric').map((item: any) => <article key={item.tag_id} className="panel-subtle overflow-x-auto"><h4 className="font-semibold">{item.display_name} event history</h4><table className="mt-2 w-full text-left text-sm"><thead><tr className="text-slate-400"><th className="py-1">Minute</th><th>Value</th></tr></thead><tbody>{item.points.map((point: any) => <tr key={point.minute_utc} className="border-t border-slate-800"><td className="py-1">{formatTime(point.minute_utc, zone)}</td><td>{point.missing ? 'Missing' : String(point.value)}</td></tr>)}</tbody></table></article>)}</div>
          <TagSearch machineId={machineId} label="Add Variable" exclude={selectedTags} onSelect={(tag) => setTemporary((current) => [...current, tag])} />
        </section>

        <details className="technical-details">
          <summary className="flex items-center justify-between gap-3 py-1 font-bold"><span>Technical details</span><span className="text-xs font-normal text-slate-400">Condition IDs, raw states, groups, source status</span></summary>
          <div className="mt-4 space-y-3 border-t border-slate-800 pt-4">
            {minute.isLoading && <div className="skeleton h-24 w-full" role="status" aria-label="Loading exact-minute details" />}
            {minute.isError && <Alert tone="error">Exact-minute evaluation details are unavailable.</Alert>}
            {Object.values(minute.data?.conditions ?? {}).map((item) => <article className="rounded-lg border border-slate-800 bg-slate-900 p-3 text-sm" key={item.condition_id}><h4 className="font-semibold">{item.display_name} <span className="font-mono text-xs text-slate-500">condition #{item.condition_id}</span></h4><p>Value: {item.value === null ? 'Missing' : String(item.value)} · {item.operator.replaceAll('_', ' ')}</p><p>Raw matched: {String(item.raw_matched)} · pending {item.pending_progress.current}/{item.pending_progress.required} · qualified active: {String(item.qualified_active)}</p>{item.delta_reference && <p>Delta reference: {String(item.delta_reference.value)} at {formatTime(item.delta_reference.minute_utc, zone)}</p>}<p>Source quality/status: {item.source?.quality ?? '—'} / {item.source?.status_code ?? '—'}{item.source?.error_text ? ' · ' + item.source.error_text : ''}</p></article>)}
            <dl className="grid gap-2 text-sm sm:grid-cols-2"><div><dt className="text-slate-400">Internal groups</dt><dd className="font-mono">{JSON.stringify(minute.data?.groups ?? {})}</dd></div><div><dt className="text-slate-400">Root expression</dt><dd className="font-mono">{String(minute.data?.root_expression_result)}</dd></div><div className="sm:col-span-2"><dt className="text-slate-400">Missing tag IDs</dt><dd className="font-mono">{minute.data?.missing_tag_ids?.join(', ') || 'None'}</dd></div></dl>
          </div>
        </details>
      </div>
    </aside>
  </>
}
