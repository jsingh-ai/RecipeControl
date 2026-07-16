import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useMemo, useState } from 'react'
import { Analysis, ApiError, api, MachineCatalog, RuleSet, Segment, Timeline } from './api'
import SegmentDetail from './SegmentDetail'
import TimelineChart from './TimelineChart'
import { DisplayZone, minuteInputToUtc } from './time'
import { Alert, EmptyState, LoadingSkeleton, StatusBadge } from './ui'

const PRESET_START = '2026-06-11T19:50'
const PRESET_END = '2026-06-23T14:20'

export default function TimelinePage() {
  const liveEnabled = import.meta.env.VITE_ENABLE_LIVE_MODE === 'true'
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
  const machines = useQuery({ queryKey: ['machineCatalog'], queryFn: () => api<MachineCatalog>('/machine-catalog') })
  const selectedMachine = machines.data?.items.find((machine) => machine.id === Number(machineId))
  const ruleSets = useQuery({ queryKey: ['ruleSets', machineId], queryFn: () => api<RuleSet[]>(`/rule-sets?machine_id=${machineId}`), enabled: Boolean(machineId) })
  const versions = useMemo(() => ruleSets.data?.flatMap((item) => item.versions.map((version) => ({ ...version, definitionName: item.name }))).filter((item) => item.status === 'LOCKED') ?? [], [ruleSets.data])
  const analyses = useQuery({ queryKey: ['analyses', machineId, versionId], queryFn: () => api<Analysis[]>(`/analyses?machine_id=${machineId}${versionId ? `&rule_version_id=${versionId}` : ''}`), enabled: Boolean(machineId), refetchInterval: 5_000 })
  const analysis = useQuery({ queryKey: ['analysis', analysisId], queryFn: () => api<Analysis & { job: any }>(`/analyses/${analysisId}`), enabled: Boolean(analysisId), refetchInterval: (query) => ['QUEUED', 'RUNNING'].includes(query.state.data?.status ?? '') ? 2_000 : false })
  const timeline = useQuery({ queryKey: ['timeline', analysisId], queryFn: () => api<Timeline>(`/analyses/${analysisId}/timeline`), enabled: Boolean(analysisId) && ['COMPLETE', 'ACTIVE', 'STOPPED'].includes(analysis.data?.status ?? ''), refetchInterval: liveId ? 10_000 : false })
  const historicalVersionId = timeline.data?.analysis.rule_version_id
  const historicalVersion = useQuery({ queryKey: ['ruleVersion', historicalVersionId], queryFn: () => api<RuleSet['versions'][number]>(`/rule-versions/${historicalVersionId}`), enabled: Boolean(historicalVersionId) })
  const selectedVersion = versions.find((item) => item.id === (historicalVersionId ?? Number(versionId))) ?? historicalVersion.data
  const payload = { machine_id: Number(machineId), rule_version_id: Number(versionId), selected_start_utc: minuteInputToUtc(start), selected_end_utc: minuteInputToUtc(end) }
  const dateError = !start || !end ? 'Choose both UTC minutes.' : end < start ? 'Inclusive end minute must be at or after the start minute.' : ''

  const generate = useMutation<Analysis, Error, boolean>({
    mutationFn: (createDuplicate) => api<Analysis>('/analyses', { method: 'POST', body: JSON.stringify({ ...payload, create_duplicate: createDuplicate }) }),
    onSuccess: (created) => { setDuplicate(null); setSelected(null); setAnalysisId(created.id); queryClient.invalidateQueries({ queryKey: ['analyses'] }) },
    onError: (error) => { if (error instanceof ApiError && error.status === 409) setDuplicate(error.body); },
  })
  const startLive = useMutation({
    mutationFn: () => api<{ id: number; analysis_id: number }>('/live-sessions', { method: 'POST', body: JSON.stringify({ machine_id: Number(machineId), rule_version_id: Number(versionId), finalization_lag_minutes: 2 }) }),
    onSuccess: (live) => { setSelected(null); setLiveId(live.id); setAnalysisId(live.analysis_id); setAutoFollow(true) },
  })
  const stopLive = useMutation({ mutationFn: () => api(`/live-sessions/${liveId}/stop`, { method: 'POST' }), onSuccess: () => { setLiveId(null); setSelected(null); queryClient.invalidateQueries({ queryKey: ['timeline', analysisId] }); queryClient.invalidateQueries({ queryKey: ['analysis', analysisId] }) } })
  const repairLive = useMutation({ mutationFn: () => api(`/live-sessions/${liveId}/repair`, { method: 'POST' }), onSuccess: () => queryClient.invalidateQueries({ queryKey: ['timeline', analysisId] }) })
  const liveStatus = useQuery({ queryKey: ['live', liveId], queryFn: () => api<any>(`/live-sessions/${liveId}`), enabled: Boolean(liveId), refetchInterval: 10_000 })
  const handleSelect = useCallback((segment: Segment, clickedUtc: string) => setSelected({ segment, clickedUtc }), [])

  return <main className="app-shell">
    <header className="flex flex-wrap items-end justify-between gap-4">
      <div><p className="section-kicker">Analysis workspace</p><h1 className="mt-1 text-3xl font-black tracking-tight sm:text-4xl">Historical timeline</h1><p className="mt-1 max-w-2xl text-sm text-slate-400">Build a complete minute-by-minute operating record, then review and annotate exact segments.</p></div>
      <div className="flex rounded-xl border border-slate-700 bg-slate-900 p-1" aria-label="Timezone toggle"><button aria-pressed={zone === 'UTC'} className={zone === 'UTC' ? 'bg-cyan-400 text-slate-950' : 'button-quiet'} onClick={() => setZone('UTC')}>UTC</button><button aria-pressed={zone === 'Central'} className={zone === 'Central' ? 'bg-cyan-400 text-slate-950' : 'button-quiet'} onClick={() => setZone('Central')}>Central</button></div>
    </header>

    {machines.isLoading && <LoadingSkeleton label="Loading machine catalog" />}
    <section className="toolbar space-y-4" aria-label="Analysis controls">
      <div className="flex flex-wrap items-center justify-between gap-2"><div><p className="section-kicker">1 · Analysis definition</p><h2 className="text-lg font-bold">Choose source and time range</h2></div><span className="badge badge-muted">End minute is inclusive</span></div>
      <div className="toolbar-section">
        <label>Machine<select aria-label="Timeline machine" value={machineId} onChange={(event) => { setMachineId(Number(event.target.value) || ''); setVersionId(''); setAnalysisId(null); setSelected(null); setDuplicate(null) }}><option value="">Choose machine</option>{machines.data?.items.map((machine) => <option key={machine.id} value={machine.id}>{machine.name}{machine.enabled ? '' : ' (Inactive)'}</option>)}</select></label>
        <label>Saved definition version<select aria-label="Saved rule version" value={versionId} onChange={(event) => { setVersionId(Number(event.target.value) || ''); setAnalysisId(null); setSelected(null); setDuplicate(null) }}><option value="">Choose version</option>{versions.map((version) => <option key={version.id} value={version.id}>{version.definitionName} · v{version.version_number}</option>)}</select></label>
        <label>Start minute (UTC)<input type="datetime-local" value={start} onChange={(event) => setStart(event.target.value)} /></label>
        <label>Inclusive end minute (UTC)<input type="datetime-local" value={end} onChange={(event) => setEnd(event.target.value)} /></label>
      </div>
      <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-800 pt-4">
        <button className="button-secondary" onClick={() => { setStart(PRESET_START); setEnd(PRESET_END) }}>Use June 11–23 preset</button>
        <div className="flex items-center gap-3"><span className="hidden text-xs text-slate-500 sm:inline">{liveEnabled ? 'Live is experimental' : 'Historical mode · Live disabled'}</span><button className="button-primary min-w-32" disabled={!machineId || !versionId || !selectedMachine?.enabled || Boolean(dateError) || generate.isPending} onClick={() => generate.mutate(false)}>{generate.isPending ? 'Starting…' : 'Analyze'}</button>{liveEnabled && <button className="button-secondary" disabled={!machineId || !versionId || !selectedMachine?.enabled || Boolean(liveId)} onClick={() => startLive.mutate()}>Start Live · Experimental</button>}</div>
      </div>
    </section>

    {machines.data?.source_sync_warning && <Alert tone="warning" role="alert">{machines.data.source_sync_warning}</Alert>}
    {selectedMachine && !selectedMachine.enabled && <Alert tone="warning">Inactive machine: saved historical analyses remain available, but new definitions, analyses, and live sessions are disabled.</Alert>}
    {dateError && <Alert tone="error">{dateError}</Alert>}
    {generate.isError && !(generate.error instanceof ApiError && generate.error.status === 409) && <Alert tone="error">{generate.error.message}</Alert>}

    <section className="toolbar flex flex-wrap items-end gap-3" aria-label="Saved analysis controls">
      <div className="min-w-[min(100%,22rem)] flex-1"><p className="section-kicker mb-2">2 · Saved result</p><label>Load saved analysis<select aria-label="Load saved analysis" value={analysisId ?? ''} onChange={(event) => { setSelected(null); setDuplicate(null); setAnalysisId(Number(event.target.value) || null) }}><option value="">Choose saved analysis</option>{analyses.data?.map((item) => <option key={item.id} value={item.id}>#{item.id} · {item.status} · {item.selected_start_utc}</option>)}</select></label></div>
      {analysis.data && <StatusBadge status={analysis.data.status} />}
      {liveId && <><span className={'badge ' + (liveStatus.data?.worker_stale ? 'badge-bad' : 'badge-good')}>{liveStatus.data?.worker_stale ? '✕ Worker stale' : '✓ Live active'}</span><button className="button-secondary" onClick={() => setAutoFollow((value) => !value)}>{autoFollow ? 'Pause auto-follow' : 'Resume auto-follow'}</button><button className="button-secondary" onClick={() => repairLive.mutate()}>Repair recent window</button><button className="button-destructive" onClick={() => stopLive.mutate()}>Stop Live</button></>}
    </section>

    {analysisId && analysis.isLoading && <LoadingSkeleton label="Loading saved analysis" />}
    {analysis.data?.status === 'FAILED' && <Alert tone="error"><div><strong>Analysis failed</strong><p className="mt-1">{analysis.data.error_message || 'The historical worker could not complete this analysis. Check worker logs and retry.'}</p></div></Alert>}
    {['QUEUED', 'RUNNING'].includes(analysis.data?.status ?? '') && <><Alert tone="info"><div><strong>Analysis is {analysis.data?.status.toLowerCase()}</strong><p className="mt-1">The worker is generating one continuous minute-by-minute timeline. You can leave this page and return later.</p></div></Alert><LoadingSkeleton label="Generating historical timeline" /></>}
    {!analysisId && !timeline.data && <EmptyState title="No analysis selected" description="Choose a machine and locked definition to generate a historical timeline, or open a saved analysis above." />}
    {timeline.isLoading && <LoadingSkeleton label="Loading timeline" />}
    {timeline.data && timeline.data.segments.length === 0 && <EmptyState title="No visible segments" description="This analysis completed without visible timeline segments. Check the selected range and source availability." />}
    {timeline.data && timeline.data.segments.length > 0 && <section className="panel overflow-hidden"><div className="mb-4 flex flex-wrap gap-x-5 gap-y-2 text-xs text-slate-300" aria-label="Timeline legend"><span>✓ Good · green</span><span>✕ Bad · red</span><span>? Unsure · blue</span><span>○ Unlabeled · gray</span><span>▨ Data Gap / Insufficient History · patterned</span><span>Condition · pending yellow / active orange</span></div><TimelineChart timeline={timeline.data} zone={zone} onSelect={handleSelect} autoFollow={Boolean(liveId && autoFollow)} /></section>}

    {duplicate && <div className="fixed inset-0 z-40 grid place-items-center bg-black/75 p-4 backdrop-blur-sm" role="dialog" aria-modal="true" aria-label="Duplicate analysis"><div className="panel max-w-lg"><p className="section-kicker">Existing result</p><h2 className="mt-1 text-xl font-bold">Analysis already exists</h2><p className="my-4 text-slate-300">A saved analysis already covers this definition and exact period.</p><div className="flex flex-wrap gap-3"><button className="button-primary" onClick={() => { setSelected(null); setAnalysisId(duplicate.matches[0].id); setDuplicate(null) }}>Open Existing</button><button className="button-secondary" onClick={() => generate.mutate(true)}>Create New</button></div></div></div>}
    {selected && analysisId && selectedVersion && selected.segment.analysis_id === analysisId && <SegmentDetail key={analysisId + ':' + selected.segment.id} segment={selected.segment} clickedUtc={selected.clickedUtc} analysisId={analysisId} machineId={timeline.data!.analysis.machine_id} version={selectedVersion} zone={zone} liveId={liveId ?? undefined} onClose={() => setSelected(null)} />}
  </main>
}
