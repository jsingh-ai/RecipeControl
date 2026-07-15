import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useMemo, useState } from 'react'
import { api, RuleVersion, Segment, Tag } from './api'
import { DisplayZone, formatTime } from './time'
import TrendChart from './TrendChart'

type Props = { segment: Segment; clickedUtc: string; analysisId: number; machineId: number; version: RuleVersion; zone: DisplayZone; liveId?: number; onClose: () => void }
type Classification = { id: number; name: string; active: boolean }

export default function SegmentDetail({ segment, clickedUtc, analysisId, machineId, version, zone, liveId, onClose }: Props) {
  const queryClient = useQueryClient()
  const conditionTags = useMemo(() => [...new Set(version.groups.flatMap((group) => group.conditions.map((item) => item.source_tag_key)))], [version])
  const [temporary, setTemporary] = useState<string[]>([])
  const [lookback, setLookback] = useState(15)
  const [quality, setQuality] = useState(segment.quality_label ?? '')
  const [classificationId, setClassificationId] = useState(segment.classification_id?.toString() ?? '')
  const [note, setNote] = useState(segment.note ?? '')
  const [newClassification, setNewClassification] = useState('')
  const classifications = useQuery({ queryKey: ['classifications', version.id], queryFn: () => api<Classification[]>(`/rule-versions/${version.id}/classifications`) })
  const tags = useQuery({ queryKey: ['tags', machineId], queryFn: () => api<Tag[]>(`/machines/${machineId}/tags`) })
  const selectedTags = [...conditionTags, ...temporary]
  const trends = useQuery({
    queryKey: ['trends', analysisId, clickedUtc, lookback, selectedTags],
    queryFn: () => api<any>(`/analyses/${analysisId}/trends?clicked_utc=${encodeURIComponent(clickedUtc)}&lookback_minutes=${lookback}${selectedTags.map((tag) => `&tag_ids=${encodeURIComponent(tag)}`).join('')}`),
  })
  const latest = useQuery({ queryKey: ['latest', liveId], queryFn: () => api<any>(`/live-sessions/${liveId}/latest`), enabled: Boolean(liveId), refetchInterval: 15_000 })
  const save = useMutation({
    mutationFn: () => api<Segment>(`/segments/${segment.id}`, { method: 'PATCH', body: JSON.stringify({ quality_label: quality || null, classification_id: classificationId ? Number(classificationId) : null, note }) }),
    onSuccess: () => queryClient.invalidateQueries({ queryKey: ['timeline', analysisId] }),
  })
  const createClassification = useMutation({
    mutationFn: () => api<Classification>(`/rule-versions/${version.id}/classifications`, { method: 'POST', body: JSON.stringify({ name: newClassification }) }),
    onSuccess: (created) => { setClassificationId(String(created.id)); setNewClassification(''); queryClient.invalidateQueries({ queryKey: ['classifications', version.id] }) },
  })
  const removeClassification = useMutation({
    mutationFn: (id: number) => api(`/classifications/${id}`, { method: 'DELETE' }),
    onSuccess: () => { setClassificationId(''); queryClient.invalidateQueries({ queryKey: ['classifications', version.id] }) },
  })

  return <aside className="fixed inset-y-0 right-0 z-30 w-full max-w-2xl overflow-y-auto border-l border-slate-700 bg-slate-950 p-6 shadow-2xl" aria-label="Segment detail">
    <div className="flex items-start justify-between"><div><p className="text-sm uppercase tracking-wider text-cyan-400">Exact-point detail</p><h2 className="text-2xl font-bold">{segment.system_state}</h2></div><button className="button-secondary" onClick={onClose}>Close</button></div>
    <dl className="my-5 grid grid-cols-2 gap-3 rounded-xl bg-slate-900 p-4 text-sm">
      <div><dt className="text-slate-400">Segment</dt><dd>{formatTime(segment.start_utc, zone)} – {formatTime(segment.end_utc, zone)}</dd></div>
      <div><dt className="text-slate-400">Clicked time</dt><dd data-testid="clicked-time">{formatTime(clickedUtc, zone)}</dd></div>
      <div><dt className="text-slate-400">Break reasons</dt><dd>{segment.contributing_condition_ids.join(', ') || 'None'}</dd></div>
      <div><dt className="text-slate-400">Duration</dt><dd>{Math.round((Date.parse(segment.end_utc) - Date.parse(segment.start_utc)) / 60_000)} minutes</dd></div>
      <div><dt className="text-slate-400">Saved classification</dt><dd>{segment.classification_name || 'None'}</dd></div>
    </dl>
    {['DATA_GAP', 'INSUFFICIENT_HISTORY'].includes(segment.system_state) && <p className="rounded-lg border border-amber-500 bg-amber-950 p-3 text-amber-100">This system segment can be labeled, but is always excluded from model training.</p>}
    <fieldset className="my-5"><legend className="mb-2 font-semibold">Quality label</legend><div className="flex gap-4">{[['GOOD', '✓ Good'], ['BAD', '✕ Bad'], ['UNSURE', '? Unsure']].map(([value, label]) => <label className="flex-row items-center" key={value}><input type="radio" name="quality" value={value} checked={quality === value} onChange={() => setQuality(value)} /> {label}</label>)}</div></fieldset>
    <div className="grid gap-3 md:grid-cols-2">
      <label>Classification<select aria-label="Classification" value={classificationId} onChange={(event) => setClassificationId(event.target.value)}><option value="">None</option>{classifications.data?.map((item) => <option key={item.id} value={item.id}>{item.name}</option>)}</select></label>
      <div className="flex items-end gap-2"><label className="flex-1">New classification<input value={newClassification} onChange={(event) => setNewClassification(event.target.value)} /></label><button className="button-secondary" disabled={!newClassification.trim()} onClick={() => createClassification.mutate()}>Add</button></div>
      {classificationId && <button className="button-secondary text-red-300" onClick={() => removeClassification.mutate(Number(classificationId))}>Remove classification from future choices</button>}
    </div>
    <label className="my-4">Notes<textarea maxLength={4000} rows={4} value={note} onChange={(event) => setNote(event.target.value)} /></label>
    <button className="button-primary" disabled={save.isPending} onClick={() => save.mutate()}>Save segment label</button>

    <section className="mt-8 space-y-4"><div className="flex items-end justify-between"><div><h3 className="text-xl font-semibold">Values and trends</h3><p className="text-sm text-slate-400">Minutes leading up to the exact clicked point.</p></div><label>Lookback minutes<input aria-label="Trend lookback minutes" className="w-28" type="number" min="1" step="1" value={lookback} onChange={(event) => setLookback(Math.max(1, Number(event.target.value)))} /></label></div>
      <div className="grid gap-2 sm:grid-cols-2">{trends.data?.series.map((item: any) => { const point = item.points[item.points.length - 1]; const observed = latest.data?.values.find((value: any) => value.tag_id === item.tag_id); return <article className="rounded-lg bg-slate-900 p-3" key={item.tag_id}><h4 className="font-semibold">{item.display_name}</h4><p>{point?.missing ? 'Missing' : `${point?.value ?? '—'} ${item.units ?? ''}`}</p>{observed && <p className="text-xs text-cyan-300">Latest: {String(observed.value)} at {formatTime(observed.sampled_at_utc, zone)}</p>}{temporary.includes(item.tag_id) && <button className="mt-2 text-xs text-red-300" onClick={() => setTemporary((current) => current.filter((tag) => tag !== item.tag_id))}>Remove</button>}</article> })}</div>
      <TrendChart series={trends.data?.series ?? []} />
      <label>Add Variable<select aria-label="Add Variable" value="" onChange={(event) => event.target.value && setTemporary((current) => current.includes(event.target.value) ? current : [...current, event.target.value])}><option value="">Search/select another machine variable</option>{tags.data?.filter((tag) => !selectedTags.includes(tag.key)).map((tag) => <option key={tag.key} value={tag.key}>{tag.display_name}</option>)}</select></label>
    </section>
  </aside>
}
