import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { render, screen, waitFor } from '@testing-library/react'
import userEvent from '@testing-library/user-event'
import { ReactNode } from 'react'
import { describe, expect, it, vi } from 'vitest'
import { RuleVersion, Segment, Timeline } from '../api'
import { operatorsFor, ruleFormSchema, serializeRule } from '../RuleBuilder'
import SegmentDetail from '../SegmentDetail'
import TimelineChart, { segmentAppearance } from '../TimelineChart'
import TimelinePage from '../TimelinePage'
import { formatTime } from '../time'

function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } })}>{children}</QueryClientProvider>
}

function response(body: unknown, status = 200) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } }))
}

const segment: Segment = { id: 7, start_utc: '2026-06-11T20:00:00Z', end_utc: '2026-06-11T20:10:00Z', system_state: 'BREAK', contributing_condition_ids: [1], quality_label: null, classification_id: null, classification_name: null, note: null, active_live: false, training_eligible: false }
const version: RuleVersion = { id: 3, rule_set_id: 2, version_number: 1, status: 'LOCKED', root_operator: 'OR', groups: [{ internal_operator: 'OR', conditions: [{ id: 1, source_tag_key: 'temperature', source_display_name: 'Temperature', source_data_type: 'numeric', operator: 'ABOVE_MAXIMUM', maximum: '250', duration_minutes: 0 }] }] }

describe('rule builder domain UI', () => {
  it('filters operators by source data type', () => {
    expect(operatorsFor('boolean')).toEqual(['EQUALS', 'NOT_EQUALS'])
    expect(operatorsFor('text')).not.toContain('INCREASE_BY')
    expect(operatorsFor('numeric')).toContain('DECREASE_BY')
  })

  it('serializes one-level grouped rules', () => {
    const value = { root_operator: 'OR' as const, groups: [{ internal_operator: 'AND' as const, conditions: [{ source_tag_key: 'temperature', source_display_name: 'Temperature', source_data_type: 'numeric' as const, operator: 'ABOVE_MAXIMUM', maximum: '250', duration_minutes: 5 }] }] }
    expect(serializeRule(value).groups[0].conditions[0].duration_minutes).toBe(5)
  })

  it('rejects invalid ranges and empty groups', () => {
    expect(ruleFormSchema.safeParse({ root_operator: 'OR', groups: [] }).success).toBe(false)
    const result = ruleFormSchema.safeParse({ root_operator: 'OR', groups: [{ internal_operator: 'AND', conditions: [{ source_tag_key: 'x', source_display_name: 'X', source_data_type: 'numeric', operator: 'OUTSIDE_RANGE', minimum: '20', maximum: '10', duration_minutes: 0 }] }] })
    expect(result.success).toBe(false)
  })
})

describe('timeline presentation', () => {
  it('uses accessible quality text and required colors', () => {
    expect(segmentAppearance({ ...segment, quality_label: 'GOOD' }).text).toContain('Good')
    expect(segmentAppearance({ ...segment, quality_label: 'BAD' }).color).toBe('#ef4444')
    expect(segmentAppearance({ ...segment, quality_label: 'UNSURE' }).text).toContain('Unsure')
    expect(segmentAppearance({ ...segment, system_state: 'DATA_GAP' }).pattern).toBe('diagonal')
  })

  it('formats Central with America/Chicago rather than a fixed offset', () => {
    expect(formatTime('2026-01-15T12:00:00Z', 'Central')).toContain('CST')
    expect(formatTime('2026-07-15T12:00:00Z', 'Central')).toContain('CDT')
    expect(formatTime('2026-07-15T12:00:00Z', 'UTC')).toContain('UTC')
  })

  it('opens detail with the exact point chosen from one segment', async () => {
    const onSelect = vi.fn()
    const timeline: Timeline = { analysis: { id: 1, machine_id: 1, rule_version_id: 3, selected_start_utc: segment.start_utc, selected_end_utc: segment.end_utc, mode: 'HISTORICAL', status: 'COMPLETE' }, segments: [segment], condition_intervals: [], boundaries: [] }
    render(<TimelineChart timeline={timeline} zone="UTC" onSelect={onSelect} />)
    await userEvent.click(screen.getByRole('button', { name: /Unlabeled/ }))
    expect(onSelect).toHaveBeenCalledWith(segment, '2026-06-11T20:05:00.000Z')
  })
})

describe('analysis workflow', () => {
  it('shows both duplicate actions', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input)
      if (url.endsWith('/machines')) return response([{ id: 1, name: 'Line 1', source_key: 'line', enabled: true }])
      if (url.includes('/rule-sets')) return response([{ id: 2, machine_id: 1, name: 'Rule', archived: false, versions: [version] }])
      if (url.includes('/analyses?')) return response([])
      if (url.endsWith('/analyses') && init?.method === 'POST') return response({ code: 'DUPLICATE_ANALYSIS', message: 'An analysis already exists for this definition and period.', matches: [{ id: 9, status: 'COMPLETE' }] }, 409)
      return response({})
    }))
    render(<TimelinePage />, { wrapper })
    await screen.findByRole('option', { name: 'Line 1' })
    await userEvent.selectOptions(screen.getByLabelText('Timeline machine'), '1')
    await userEvent.selectOptions(await screen.findByLabelText('Saved rule version'), '3')
    await userEvent.click(screen.getByRole('button', { name: 'Analyze' }))
    expect(await screen.findByRole('dialog', { name: 'Duplicate analysis' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Open Existing' })).toBeInTheDocument()
    expect(screen.getByRole('button', { name: 'Create New' })).toBeInTheDocument()
  })

  it('toggles timezone presentation control', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => String(input).endsWith('/machines') ? response([]) : response([])))
    render(<TimelinePage />, { wrapper })
    const central = screen.getByRole('button', { name: 'Central' })
    expect(central).toHaveAttribute('aria-pressed', 'false')
    await userEvent.click(central)
    expect(central).toHaveAttribute('aria-pressed', 'true')
  })

  it('requests a 15-minute trend, adds a temporary variable, and labels one segment', async () => {
    const requested: string[] = []
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL, init?: RequestInit) => {
      const url = String(input); requested.push(url)
      if (url.includes('/classifications')) return response([{ id: 4, name: 'Normal Production', active: true }])
      if (url.includes('/machines/1/tags')) return response({ items: [{ key: 'temperature', display_name: 'Temperature', raw_data_type: 'Double', data_kind: 'numeric' }, { key: 'speed', display_name: 'Speed', raw_data_type: 'Double', data_kind: 'numeric' }], limit: 25, offset: 0, has_more: false })
      if (url.includes('/minutes/')) return response({ conditions: {}, active_condition_ids: [], missing_tag_ids: [], groups: {}, root_expression_result: true, training_eligible: false, training_ineligibility_reason: 'A Good or Bad label is required' })
      if (url.includes('/trends')) {
        const tags = url.includes('tag_ids=speed') ? ['temperature', 'speed'] : ['temperature']
        return response({ series: tags.map((tag) => ({ tag_id: tag, display_name: tag, data_type: 'numeric', points: [{ minute_utc: '2026-06-11T20:05:00Z', value: 1, missing: false }] })) })
      }
      if (url.includes('/segments/7') && init?.method === 'PATCH') return response({ ...segment, quality_label: 'BAD' })
      return response({})
    }))
    render(<SegmentDetail segment={segment} clickedUtc="2026-06-11T20:05:00Z" analysisId={1} machineId={1} version={version} zone="UTC" onClose={() => {}} />, { wrapper })
    await waitFor(() => expect(requested.some((url) => url.includes('lookback_minutes=15'))).toBe(true))
    const addVariable = await screen.findByRole('combobox', { name: 'Add Variable' })
    await userEvent.click(addVariable)
    await userEvent.type(addVariable, 'speed')
    await userEvent.click(await screen.findByRole('option', { name: /Speed/ }))
    await waitFor(() => expect(requested.some((url) => url.includes('tag_ids=speed'))).toBe(true))
    await userEvent.click(screen.getByLabelText(/Bad/))
    await userEvent.click(screen.getByRole('button', { name: 'Save segment label' }))
    await waitFor(() => expect((fetch as any).mock.calls.filter((call: any[]) => String(call[0]).includes('/segments/7')).length).toBe(1))
  })

  it('does not offer a removed classification for new labels', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/classifications')) return response([{ id: 2, name: 'Active category', active: true }])
      if (url.includes('/tags')) return response({ items: [], limit: 25, offset: 0, has_more: false })
      if (url.includes('/trends')) return response({ series: [] })
      if (url.includes('/minutes/')) return response({ conditions: {}, active_condition_ids: [], missing_tag_ids: [], groups: {}, root_expression_result: false, training_eligible: false })
      return response({})
    }))
    render(<SegmentDetail segment={segment} clickedUtc="2026-06-11T20:05:00Z" analysisId={1} machineId={1} version={version} zone="UTC" onClose={() => {}} />, { wrapper })
    expect(await screen.findByRole('option', { name: 'Active category' })).toBeInTheDocument()
    expect(screen.queryByRole('option', { name: 'Retired category' })).not.toBeInTheDocument()
  })

  it('resets unsaved annotation fields when switching directly between segments', async () => {
    vi.stubGlobal('fetch', vi.fn((input: RequestInfo | URL) => {
      const url = String(input)
      if (url.includes('/classifications')) return response([{ id: 4, name: 'Normal Production', active: true }])
      if (url.includes('/trends')) return response({ series: [] })
      if (url.includes('/minutes/')) return response({ conditions: {}, active_condition_ids: [], missing_tag_ids: [], groups: {}, root_expression_result: false, training_eligible: true })
      return response({ items: [], limit: 25, offset: 0, has_more: false })
    }))
    const second: Segment = { ...segment, id: 8, quality_label: 'GOOD', classification_id: 4, classification_name: 'Normal Production', note: 'Persisted B note' }
    const view = render(<SegmentDetail segment={segment} clickedUtc="2026-06-11T20:05:00Z" analysisId={1} machineId={1} version={version} zone="UTC" onClose={() => {}} />, { wrapper })
    await userEvent.click(screen.getByLabelText(/Bad/))
    await userEvent.type(screen.getByLabelText('Notes'), 'Unsaved A note')
    view.rerender(<SegmentDetail segment={second} clickedUtc="2026-06-11T20:15:00Z" analysisId={1} machineId={1} version={version} zone="UTC" onClose={() => {}} />)
    await waitFor(() => expect(screen.getByLabelText(/Good/)).toBeChecked())
    expect(screen.getByLabelText('Notes')).toHaveValue('Persisted B note')
    expect(screen.getByLabelText(/Bad/)).not.toBeChecked()
  })
})
