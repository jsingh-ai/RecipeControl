import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { Analysis, ApiError, api, Machine, RuleSet, Segment, Timeline } from './api'
import SegmentDetail from './SegmentDetail'
import TimelineChart, { segmentAppearance } from './TimelineChart'
import { DisplayZone, minuteInputToUtc } from './time'

const PRESET_START = '2026-06-11T19:50'
const PRESET_END = '2026-06-23T14:20'

export default function TimelinePage() {
  const queryClient = useQueryClient()
  const [machineId, setMachineId] = useState<number | ''>('')
  const [versionId, setVersionId] = useState<number | ''>('')
  const [start, setStart] = useState(PRESET_START)
  const [end, setEnd] = useState(PRESET_END)
  const [zone, setZone] = useState<DisplayZone>('UTC')
  const [analysisId, setAnalysisId] = useState<number | null>(null)
  const [duplicate, setDuplicate] = useState<any>(null)
  const [selected, setSelected] = useState<{ segment: Segment; clickedUtc: string } | null>(null)
  const [liveId, setLiveId] = useState<number | null>(null)
  const [autoFollow, setAutoFollow] = useState(true)
  const machines = useQuery({ queryKey: ['machines'], queryFn: () => api<Machine[]>('/machines') })
  const ruleSets = useQuery({ queryKey: ['ruleSets', machineId], queryFn: () => api<RuleSet[]>(`/rule-sets?machine_id=${machineId}`), enabled: Boolean(machineId) })
  const versions = useMemo(() => ruleSets.data?.flatMap((item) => item.versions.map((version) => ({ ...version, definitionName: item.name }))).filter((item) => item.status === 'LOCKED') ?? [], [ruleSets.data])
  const analyses = useQuery({ queryKey: ['analyses', machineId, versionId], queryFn: () => api<Analysis[]>(`/analyses?machine_id=${machineId}${versionId ? `&rule_version_id=${versionId}` : ''}`), enabled: Boolean(machineId), refetchInterval: 5_000 })
  const analysis = useQuery({ queryKey: ['analysis', analysisId], queryFn: () => api<Analysis & { job: any }>(`/analyses/${analysisId}`), enabled: Boolean(analysisId), refetchInterval: (query) => ['QUEUED', 'RUNNING'].includes(query.state.data?.status ?? '') ? 2_000 : false })
  const timeline = useQuery({ queryKey: ['timeline', analysisId], queryFn: () => api<Timeline>(`/analyses/${analysisId}/timeline`), enabled: Boolean(analysisId) && ['COMPLETE', 'ACTIVE', 'STOPPED'].includes(analysis.data?.status ?? ''), refetchInterval: liveId ? 10_000 : false })
  const selectedVersion = versions.find((item) => item.id === (timeline.data?.analysis.rule_version_id ?? Number(versionId)))
  const payload = { machine_id: Number(machineId), rule_version_id: Number(versionId), selected_start_utc: minuteInputToUtc(start), selected_end_utc: minuteInputToUtc(end) }

  const generate = useMutation<Analysis, Error, boolean>({
    mutationFn: (createDuplicate) => api<Analysis>('/analyses', { method: 'POST', body: JSON.stringify({ ...payload, create_duplicate: createDuplicate }) }),
    onSuccess: (created) => { setDuplicate(null); setAnalysisId(created.id); queryClient.invalidateQueries({ queryKey: ['analyses'] }) },
    onError: (error) => { if (error instanceof ApiError && error.status === 409) setDuplicate(error.body); },
  })
  const startLive = useMutation({
    mutationFn: () => api<{ id: number; analysis_id: number }>('/live-sessions', { method: 'POST', body: JSON.stringify({ machine_id: Number(machineId), rule_version_id: Number(versionId), finalization_lag_minutes: 2 }) }),
    onSuccess: (live) => { setLiveId(live.id); setAnalysisId(live.analysis_id); setAutoFollow(true) },
  })
  const stopLive = useMutation({ mutationFn: () => api(`/live-sessions/${liveId}/stop`, { method: 'POST' }), onSuccess: () => setLiveId(null) })
  const repairLive = useMutation({ mutationFn: () => api(`/live-sessions/${liveId}/repair`, { method: 'POST' }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['timeline', analysisId] }) })
  const liveStatus = useQuery({ queryKey: ['live', liveId], queryFn: () => api<any>(`/live-sessions/${liveId}`), enabled: Boolean(liveId), refetchInterval: 10_000 })
  const handleSelect = useCallback((segment: Segment, clickedUtc: string) => setSelected({ segment, clickedUtc }), [])

  return <main className="mx-auto max-w-[1600px] space-y-5 p-6">
    <header className="flex flex-wrap items-end justify-between gap-3"><div><p className="text-sm uppercase tracking-[0.3em] text-cyan-400">Analysis workspace</p><h1 className="text-3xl font-bold">Segment timeline</h1></div><div className="flex rounded-lg border border-slate-700 p-1" aria-label="Timezone toggle"><button aria-pressed={zone === 'UTC'} className={zone === 'UTC' ? 'bg-cyan-500 text-slate-950' : ''} onClick={() => setZone('UTC')}>UTC</button><button aria-pressed={zone === 'Central'} className={zone === 'Central' ? 'bg-cyan-500 text-slate-950' : ''} onClick={() => setZone('Central')}>Central</button></div></header>
    <section className="panel grid gap-3 xl:grid-cols-6">
      <label>Machine<select aria-label="Timeline machine" value={machineId} onChange={(event) => { setMachineId(Number(event.target.value) || ''); setVersionId('') }}><option value="">Choose machine</option>{machines.data?.map((machine) => <option key={machine.id} value={machine.id}>{machine.name}</option>)}</select></label>
      <label>Saved definition version<select aria-label="Saved rule version" value={versionId} onChange={(event) => setVersionId(Number(event.target.value) || '')}><option value="">Choose version</option>{versions.map((version) => <option key={version.id} value={version.id}>{version.definitionName} · v{version.version_number}</option>)}</select></label>
      <label>Start minute (UTC)<input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
      <label>Inclusive end minute (UTC)<input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
      <button className="button-secondary self-end" onClick={() => { setStart(PRESET_START); setEnd(PRESET_END) }}>June 11–23 preset</button>
      <div className="flex items-end gap-2"><button className="button-primary flex-1" disabled={!machineId || !versionId || generate.isPending} onClick={() => generate.mutate(false)}>Analyze</button><button className="button-secondary" disabled={!machineId || !versionId || Boolean(liveId)} onClick={() => startLive.mutate()}>Start Live</button></div>
    </section>
    <section className="panel flex flex-wrap items-end gap-3"><label className="min-w-72">Load saved analysis<select aria-label="Load saved analysis" value={analysisId ?? ''} onChange={(event) => setAnalysisId(Number(event.target.value) || null)}><option value="">Choose saved analysis</option>{analyses.data?.map((item) => <option key={item.id} value={item.id}>#{item.id} · {item.status} · {item.selected_start_utc}</option>)}</select></label>{analysis.data && <span className="badge bg-slate-700">{analysis.data.status}</span>}{liveId && <><span className={`badge ${liveStatus.data?.worker_stale ? 'bg-red-800' : 'bg-green-800'}`}>{liveStatus.data?.worker_stale ? 'Worker stale' : 'Live active'}</span><button className="button-secondary" onClick={() => setAutoFollow((value) => !value)}>{autoFollow ? 'Pause auto-follow' : 'Resume auto-follow'}</button><button className="button-secondary" onClick={() => repairLive.mutate()}>Repair recent window</button><button className="button-secondary text-red-300" onClick={() => stopLive.mutate()}>Stop Live</button></>}</section>
    {analysis.data?.status === 'FAILED' && <p role="alert" className="panel text-red-300">{analysis.data.error_message}</p>}
    {['QUEUED', 'RUNNING'].includes(analysis.data?.status ?? '') && <p role="status" className="panel">Analysis is {analysis.data?.status.toLowerCase()}. The worker is generating a complete timeline…</p>}
    {timeline.data && <section className="panel overflow-hidden"><div className="mb-3 flex flex-wrap gap-3 text-xs" aria-label="Timeline legend"><span>✓ Good — green</span><span>✕ Bad — red</span><span>? Unsure — blue</span><span>○ Unlabeled — gray</span><span>▨ Data Gap — purple pattern</span><span>▨ Insufficient History — amber pattern</span><span>Condition: pending yellow / active orange</span></div><TimelineChart timeline={timeline.data} zone={zone} onSelect={handleSelect} autoFollow={Boolean(liveId && autoFollow)} /></section>}
    {timeline.data && <section className="grid gap-2 md:grid-cols-4" aria-label="Segment label summary">{timeline.data.segments.slice(0, 12).map((segment) => <button key={segment.id} className="panel text-left" onClick={() => handleSelect(segment, segment.start_utc)}><span className="badge" style={{ backgroundColor: segmentAppearance(segment).color }}>{segmentAppearance(segment).text}</span><p className="mt-2 text-xs">{segment.system_state}</p></button>)}</section>}
    {duplicate && <div className="fixed inset-0 z-40 grid place-items-center bg-black/70 p-4" role="dialog" aria-modal="true" aria-label="Duplicate analysis"><div className="panel max-w-lg"><h2 className="text-xl font-bold">Analysis already exists</h2><p className="my-4">An analysis already exists for this definition and period.</p><div className="flex gap-3"><button className="button-primary" onClick={() => { setAnalysisId(duplicate.matches[0].id); setDuplicate(null) }}>Open Existing</button><button className="button-secondary" onClick={() => generate.mutate(true)}>Create New</button></div></div></div>}
    {selected && analysisId && selectedVersion && <SegmentDetail segment={selected.segment} clickedUtc={selected.clickedUtc} analysisId={analysisId} machineId={timeline.data!.analysis.machine_id} version={selectedVersion} zone={zone} liveId={liveId ?? undefined} onClose={() => setSelected(null)} />}
  </main>
}
