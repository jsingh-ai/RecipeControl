import { zodResolver } from '@hookform/resolvers/zod'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useEffect, useState } from 'react'
import { useFieldArray, useForm } from 'react-hook-form'
import { z } from 'zod'
import { api, DataKind, Machine, RuleSet, RuleVersion, Tag } from './api'
import TagSearch from './TagSearch'
import { Alert, EmptyState } from './ui'

const conditionSchema = z.object({
  source_tag_key: z.string().min(1, 'Choose a variable'),
  source_display_name: z.string().min(1),
  source_raw_data_type: z.string().nullable().optional(),
  source_data_type: z.enum(['numeric', 'text', 'boolean']),
  operator: z.string().min(1, 'Choose an operator'),
  minimum: z.string().optional(),
  maximum: z.string().optional(),
  comparison_value: z.union([z.string(), z.boolean()]).optional(),
  delta_amount: z.string().optional(),
  delta_window_minutes: z.coerce.number().int().min(1).optional(),
  duration_minutes: z.coerce.number().int().min(0),
}).superRefine((condition, context) => {
  if (condition.operator === 'OUTSIDE_RANGE') {
    if (!condition.minimum || !condition.maximum) context.addIssue({ code: 'custom', message: 'Both range bounds are required' })
    else if (Number(condition.minimum) > Number(condition.maximum)) context.addIssue({ code: 'custom', message: 'Minimum cannot exceed maximum' })
  }
  if (condition.operator === 'BELOW_MINIMUM' && !condition.minimum) context.addIssue({ code: 'custom', message: 'Minimum is required' })
  if (condition.operator === 'ABOVE_MAXIMUM' && !condition.maximum) context.addIssue({ code: 'custom', message: 'Maximum is required' })
  if (['EQUALS', 'NOT_EQUALS'].includes(condition.operator) && condition.comparison_value === undefined) context.addIssue({ code: 'custom', message: 'Comparison value is required' })
  if (['INCREASE_BY', 'DECREASE_BY'].includes(condition.operator) && (!condition.delta_amount || Number(condition.delta_amount) <= 0)) context.addIssue({ code: 'custom', message: 'Delta amount must be positive' })
})

export const ruleFormSchema = z.object({
  root_operator: z.enum(['AND', 'OR']),
  groups: z.array(z.object({
    internal_operator: z.enum(['AND', 'OR']),
    conditions: z.array(conditionSchema).min(1, 'A group needs one condition'),
  })).min(1, 'Add at least one group'),
})

export type RuleForm = z.infer<typeof ruleFormSchema>

export function operatorsFor(dataType: DataKind): string[] {
  if (dataType === 'numeric') return ['BELOW_MINIMUM', 'ABOVE_MAXIMUM', 'OUTSIDE_RANGE', 'EQUALS', 'NOT_EQUALS', 'INCREASE_BY', 'DECREASE_BY']
  return ['EQUALS', 'NOT_EQUALS']
}

export function sortVersions(versions: RuleVersion[]): RuleVersion[] {
  return [...versions].sort((left, right) => left.version_number - right.version_number || left.id - right.id)
}

export function serializeRule(values: RuleForm) {
  const parsed = ruleFormSchema.parse(values)
  return { root_operator: parsed.root_operator, groups: parsed.groups.map((group) => ({ internal_operator: group.internal_operator, conditions: group.conditions.map((condition) => ({ tag_id: condition.source_tag_key, operator: condition.operator, minimum: condition.minimum, maximum: condition.maximum, comparison_value: condition.comparison_value, delta_amount: condition.delta_amount, delta_window_minutes: condition.delta_window_minutes, duration_minutes: condition.duration_minutes })) })) }
}

const blankCondition = (): RuleForm['groups'][number]['conditions'][number] => ({
  source_tag_key: '', source_display_name: '', source_data_type: 'numeric', operator: 'ABOVE_MAXIMUM',
  maximum: '', duration_minutes: 0,
})

export default function RuleBuilder() {
  const queryClient = useQueryClient()
  const [machineId, setMachineId] = useState<number | ''>('')
  const [name, setName] = useState('')
  const [version, setVersion] = useState<RuleVersion | null>(null)
  const [notice, setNotice] = useState('')
  const [showArchived, setShowArchived] = useState(false)
  const machines = useQuery({ queryKey: ['machines'], queryFn: () => api<Machine[]>('/machines') })
  const ruleSets = useQuery({ queryKey: ['ruleSets', machineId, showArchived], queryFn: () => api<RuleSet[]>(`/rule-sets?machine_id=${machineId}&include_archived=${showArchived}`), enabled: Boolean(machineId) })
  const form = useForm<RuleForm>({
    resolver: zodResolver(ruleFormSchema),
    defaultValues: { root_operator: 'OR', groups: [{ internal_operator: 'AND', conditions: [blankCondition()] }] },
  })
  const groups = useFieldArray({ control: form.control, name: 'groups' })
  const watched = form.watch()
  const selectedRuleSet = ruleSets.data?.find((item) => item.id === version?.rule_set_id)

  useEffect(() => {
    if (version) form.reset({
      root_operator: version.root_operator,
      groups: version.groups.length ? version.groups.map((group) => ({
        internal_operator: group.internal_operator,
        conditions: group.conditions.map((item) => ({
          source_tag_key: item.source_tag_key,
          source_display_name: item.source_display_name,
          source_raw_data_type: item.source_raw_data_type,
          source_data_type: item.source_data_type,
          operator: item.operator,
          minimum: item.minimum ?? undefined,
          maximum: item.maximum ?? undefined,
          comparison_value: typeof item.comparison_value === 'boolean' || typeof item.comparison_value === 'string' ? item.comparison_value : undefined,
          delta_amount: item.delta_amount ?? undefined,
          delta_window_minutes: item.delta_window_minutes ?? undefined,
          duration_minutes: item.duration_minutes,
        })),
      })) : [{ internal_operator: 'AND', conditions: [blankCondition()] }],
    })
  }, [version, form])

  const create = useMutation({
    mutationFn: () => api<{ rule_set_id: number; version: RuleVersion }>('/rule-sets', {
      method: 'POST', body: JSON.stringify({ machine_id: machineId, name }),
    }),
    onSuccess: (data) => { setVersion(data.version); setNotice('Draft created. Add conditions, then save and lock it.'); queryClient.invalidateQueries({ queryKey: ['ruleSets'] }) },
  })
  const persist = useMutation({
    mutationFn: async ({ values, lock }: { values: RuleForm; lock: boolean }) => {
      if (!version) throw new Error('Create a draft first')
      const saved = await api<RuleVersion>(`/rule-versions/${version.id}`, { method: 'PUT', body: JSON.stringify(serializeRule(values)) })
      return lock ? api<RuleVersion>(`/rule-versions/${version.id}/lock`, { method: 'POST' }) : saved
    },
    onSuccess: (saved, variables) => { setVersion(saved); setNotice(variables.lock ? `Version ${saved.version_number} saved and locked.` : `Draft version ${saved.version_number} saved.`); queryClient.invalidateQueries({ queryKey: ['ruleSets'] }) },
  })
  const newVersion = useMutation({
    mutationFn: () => api<RuleVersion>(`/rule-sets/${version!.rule_set_id}/versions`, { method: 'POST' }),
    onSuccess: (created) => { setVersion(created); form.reset({ root_operator: 'OR', groups: [{ internal_operator: 'AND', conditions: [blankCondition()] }] }); setNotice('New blank version created.'); queryClient.invalidateQueries({ queryKey: ['ruleSets'] }) },
  })
  const archive = useMutation({ mutationFn: (ruleSetId: number) => api(`/rule-sets/${ruleSetId}/archive`, { method: 'POST' }), onSuccess: () => { setVersion(null); setNotice('Definition archived.'); queryClient.invalidateQueries({ queryKey: ['ruleSets'] }) } })

  function addCondition(groupIndex: number) {
    const current = form.getValues(`groups.${groupIndex}.conditions`)
    form.setValue(`groups.${groupIndex}.conditions`, [...current, blankCondition()], { shouldDirty: true })
  }

  function removeCondition(groupIndex: number, conditionIndex: number) {
    const current = form.getValues(`groups.${groupIndex}.conditions`)
    form.setValue(`groups.${groupIndex}.conditions`, current.filter((_, index) => index !== conditionIndex), { shouldValidate: true })
  }

  const preview = watched.groups?.map((group) => `(${(group.conditions ?? []).map((item) => `${item.source_display_name || 'Variable'} ${item.operator.replaceAll('_', ' ').toLowerCase()}`).join(` ${group.internal_operator} `)})`).join(` ${watched.root_operator} `)

  return <main className="app-shell max-w-[1500px]" aria-label="Rule builder">
    <header>
      <p className="section-kicker">Definition studio</p>
      <h1 className="mt-1 text-3xl font-black tracking-tight sm:text-4xl">Build a break definition</h1>
      <p className="mt-2 text-slate-400">Compose operator-readable groups from authoritative source tags. Locked versions remain immutable.</p>
    </header>

    <section className="toolbar grid gap-4 md:grid-cols-[1fr_2fr_auto]">
      <label>Machine
        <select aria-label="Machine" value={machineId} onChange={(event) => { setMachineId(Number(event.target.value) || ''); setVersion(null); form.reset({ root_operator: 'OR', groups: [{ internal_operator: 'AND', conditions: [blankCondition()] }] }) }} disabled={Boolean(version)}>
          <option value="">Choose machine</option>
          {machines.data?.map((machine) => <option key={machine.id} value={machine.id}>{machine.name}</option>)}
        </select>
      </label>
      <label>Definition name
        <input value={name} onChange={(event) => setName(event.target.value)} placeholder="Example: Production break rules" disabled={Boolean(version)} />
      </label>
      {!version ? <button className="button-primary self-end" disabled={!machineId || !name.trim() || create.isPending} onClick={() => create.mutate()}>Create Draft</button>
        : <div className="flex items-center gap-2 self-end"><span className={'badge ' + (version.status === 'LOCKED' ? 'badge-good' : 'border-amber-600/50 bg-amber-950 text-amber-200')}><span aria-hidden="true">{version.status === 'LOCKED' ? '✓' : '◷'}</span><span>v{version.version_number} · {version.status}</span></span><button type="button" className="button-secondary" onClick={() => { setVersion(null); setName('') }}>Close</button></div>}
    </section>

    {machineId && <section className="panel space-y-3" aria-label="Definition versions"><div className="flex flex-wrap items-center justify-between gap-3"><div><p className="section-kicker">Version browser</p><h2 className="text-lg font-semibold">Saved definitions</h2><p className="text-sm text-slate-400">Machine: {machines.data?.find((item) => item.id === machineId)?.name}</p></div><label className="flex-row items-center"><input className="size-4 min-h-0 w-4" type="checkbox" checked={showArchived} onChange={(event) => setShowArchived(event.target.checked)} /> Show archived</label></div>{ruleSets.isLoading && <div className="skeleton h-20 w-full" role="status" aria-label="Loading definitions" />}{ruleSets.data?.length === 0 && <EmptyState title="No definitions yet" description="Create the first draft for this machine using the controls above." />}<div className="grid gap-3 md:grid-cols-2">{ruleSets.data?.map((ruleSet) => { const ordered = sortVersions(ruleSet.versions); return <article key={ruleSet.id} className="panel-subtle"><div className="flex justify-between gap-2"><h3 className="font-semibold">{ruleSet.name}</h3>{ruleSet.archived && <span className="badge badge-muted">Archived</span>}</div><div className="mt-3 flex flex-wrap gap-2">{ordered.map((item) => <button type="button" className="button-secondary" key={item.id} onClick={() => { setVersion(item); setName(ruleSet.name) }}><span aria-hidden="true">{item.status === 'LOCKED' ? '✓ ' : '◷ '}</span><span>v{item.version_number} · {item.status}</span></button>)}</div>{!ruleSet.archived && <div className="mt-3 flex gap-2"><button type="button" className="button-secondary" onClick={() => { const selected = ordered.at(-1); if (selected) setVersion(selected) }}>Open latest</button><button type="button" className="button-destructive" disabled={archive.isPending} onClick={() => archive.mutate(ruleSet.id)}>Archive</button></div>}</article> })}</div></section>}

    {version && <form className="space-y-4" onSubmit={(event) => event.preventDefault()}>
      <section className="toolbar flex flex-wrap items-end gap-4">
        <label>Root operator between groups
          <select aria-label="Root operator" {...form.register('root_operator')} disabled={version.status === 'LOCKED'}><option>OR</option><option>AND</option></select>
        </label>
        <div className="min-w-64 flex-1 rounded-xl border border-slate-800 bg-slate-950 p-3 text-sm text-slate-300"><span className="section-kicker mb-1 block">Expression preview</span>{preview}</div>
      </section>

      {groups.fields.map((field, groupIndex) => <section className="panel space-y-4" key={field.id}>
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-lg font-semibold">Group {groupIndex + 1}</h2>
          <div className="flex gap-2">
            <select aria-label={`Group ${groupIndex + 1} operator`} {...form.register(`groups.${groupIndex}.internal_operator`)} disabled={version.status === 'LOCKED'}><option>AND</option><option>OR</option></select>
            <button type="button" className="button-secondary" disabled={version.status === 'LOCKED'} onClick={() => groups.move(groupIndex, Math.max(0, groupIndex - 1))}>Move up</button>
            <button type="button" className="button-secondary" disabled={version.status === 'LOCKED'} onClick={() => groups.remove(groupIndex)}>Remove Group</button>
          </div>
        </div>
        {watched.groups?.[groupIndex]?.conditions?.map((condition, conditionIndex) => {
          const type = condition.source_data_type
          const operator = condition.operator
          return <div className="grid gap-3 rounded-xl border border-slate-700 p-4 lg:grid-cols-6" key={`${groupIndex}-${conditionIndex}`} data-testid="condition-row">
            <div className="lg:col-span-2"><TagSearch label={`Variable ${conditionIndex + 1}`} machineId={Number(machineId)} disabled={version.status === 'LOCKED'} value={condition.source_tag_key ? { key: condition.source_tag_key, display_name: condition.source_display_name, raw_data_type: condition.source_raw_data_type ?? null, data_kind: condition.source_data_type } as Tag : null} onClear={() => {
                form.setValue(`groups.${groupIndex}.conditions.${conditionIndex}.source_tag_key`, '', { shouldValidate: true })
                form.setValue(`groups.${groupIndex}.conditions.${conditionIndex}.source_display_name`, '', { shouldValidate: true })
                form.setValue(`groups.${groupIndex}.conditions.${conditionIndex}.source_raw_data_type`, null)
              }} onSelect={(selected) => {
                form.setValue(`groups.${groupIndex}.conditions.${conditionIndex}.source_tag_key`, selected.key)
                form.setValue(`groups.${groupIndex}.conditions.${conditionIndex}.source_display_name`, selected.display_name)
                form.setValue(`groups.${groupIndex}.conditions.${conditionIndex}.source_raw_data_type`, selected.raw_data_type)
                form.setValue(`groups.${groupIndex}.conditions.${conditionIndex}.source_data_type`, selected.data_kind)
                form.setValue(`groups.${groupIndex}.conditions.${conditionIndex}.operator`, operatorsFor(selected.data_kind)[0])
              }} /></div>
            <label>Operator
              <select aria-label={`Operator ${conditionIndex + 1}`} {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.operator`)} disabled={version.status === 'LOCKED'}>
                {operatorsFor(type).map((item) => <option key={item} value={item}>{item.replaceAll('_', ' ')}</option>)}
              </select>
            </label>
            {operator === 'BELOW_MINIMUM' && <label>Minimum<input disabled={version.status === 'LOCKED'} type="number" step="any" {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.minimum`)} /></label>}
            {operator === 'ABOVE_MAXIMUM' && <label>Maximum<input disabled={version.status === 'LOCKED'} type="number" step="any" {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.maximum`)} /></label>}
            {operator === 'OUTSIDE_RANGE' && <><label>Minimum<input disabled={version.status === 'LOCKED'} type="number" step="any" {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.minimum`)} /></label><label>Maximum<input disabled={version.status === 'LOCKED'} type="number" step="any" {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.maximum`)} /></label></>}
            {['EQUALS', 'NOT_EQUALS'].includes(operator) && <label>Comparison
              {type === 'boolean' ? <select disabled={version.status === 'LOCKED'} {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.comparison_value`)}><option value="true">true</option><option value="false">false</option></select> : <input disabled={version.status === 'LOCKED'} type={type === 'numeric' ? 'number' : 'text'} step="any" {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.comparison_value`)} />}
            </label>}
            {['INCREASE_BY', 'DECREASE_BY'].includes(operator) && <><label>Delta amount<input disabled={version.status === 'LOCKED'} type="number" min="0" step="any" {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.delta_amount`)} /></label><label>Window minutes<input disabled={version.status === 'LOCKED'} type="number" min="1" step="1" {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.delta_window_minutes`)} /></label></>}
            <label>Activation minutes<input type="number" min="0" step="1" {...form.register(`groups.${groupIndex}.conditions.${conditionIndex}.duration_minutes`)} disabled={version.status === 'LOCKED'} /></label>
            <button type="button" className="button-destructive self-end" disabled={version.status === 'LOCKED'} onClick={() => removeCondition(groupIndex, conditionIndex)}>Remove</button>
          </div>
        })}
        <button type="button" className="button-secondary" disabled={version.status === 'LOCKED'} onClick={() => addCondition(groupIndex)}>Add Condition</button>
      </section>)}

      <div className="sticky bottom-3 z-10 flex flex-wrap gap-3 rounded-xl border border-slate-700 bg-slate-950/95 p-3 shadow-2xl backdrop-blur">
        {version.status === 'DRAFT' && <><button type="button" className="button-secondary" onClick={() => groups.append({ internal_operator: 'AND', conditions: [blankCondition()] })}>Add Group</button><button className="button-secondary" type="button" disabled={persist.isPending} onClick={form.handleSubmit((values) => persist.mutate({ values, lock: false }))}>Save Draft</button><button className="button-primary" type="button" disabled={persist.isPending} onClick={form.handleSubmit((values) => persist.mutate({ values, lock: true }))}>Save & Lock Version</button></>}
        {version.status === 'LOCKED' && !selectedRuleSet?.archived && <button type="button" className="button-primary" onClick={() => newVersion.mutate()}>Create New Blank Version</button>}
      </div>
      {Object.keys(form.formState.errors).length > 0 && <Alert tone="error">Fix the highlighted rule fields. Every saved group needs a selected tag and valid condition.</Alert>}
    </form>}
    {(notice || create.error || persist.error || newVersion.error) && <Alert tone={create.error || persist.error || newVersion.error ? 'error' : 'success'}>{notice || create.error?.message || persist.error?.message || newVersion.error?.message}</Alert>}
  </main>
}
