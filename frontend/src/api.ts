export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api'

export class ApiError extends Error {
  constructor(public status: number, public body: any) {
    super(body?.message ?? body?.detail ?? `Request failed (${status})`)
  }
}

export async function api<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...init?.headers },
  })
  const body = await response.json().catch(() => null)
  if (!response.ok) throw new ApiError(response.status, body)
  return body as T
}

export type Machine = { id: number; source_key: string; name: string; enabled: boolean }
export type DataKind = 'numeric' | 'text' | 'boolean'
export type Tag = { key: string; display_name: string; raw_data_type: string | null; data_kind: DataKind; units?: string; node_id?: string; opc_path?: string }
export type TagPage = { items: Tag[]; limit: number; offset: number; has_more: boolean }
export type RuleVersion = {
  id: number
  rule_set_id: number
  version_number: number
  status: 'DRAFT' | 'LOCKED'
  root_operator: 'AND' | 'OR'
  groups: RuleGroup[]
}
export type RuleGroup = { id?: number; internal_operator: 'AND' | 'OR'; conditions: RuleCondition[] }
export type RuleCondition = {
  id?: number
  source_tag_key: string
  source_display_name: string
  source_raw_data_type?: string | null
  source_data_type: 'numeric' | 'text' | 'boolean'
  operator: string
  minimum?: string | null
  maximum?: string | null
  comparison_value?: unknown
  delta_amount?: string | null
  delta_window_minutes?: number | null
  duration_minutes: number
}
export type RuleSet = { id: number; machine_id: number; name: string; archived: boolean; versions: RuleVersion[] }
export type Analysis = {
  id: number
  machine_id: number
  rule_version_id: number
  selected_start_utc: string
  selected_end_utc: string
  mode: 'HISTORICAL' | 'LIVE'
  status: string
  error_message?: string
}
export type Segment = {
  id: number
  analysis_id: number
  start_utc: string
  end_utc: string
  system_state: 'NORMAL' | 'BREAK' | 'DATA_GAP' | 'INSUFFICIENT_HISTORY'
  contributing_condition_ids: number[]
  quality_label: 'GOOD' | 'BAD' | 'UNSURE' | null
  classification_id: number | null
  classification_name: string | null
  note: string | null
  active_live: boolean
  training_eligible: boolean
}
export type Timeline = {
  analysis: Analysis
  segments: Segment[]
  condition_intervals: Array<{ id: number; condition_id: number; start_utc: string; end_utc: string; state: string }>
  boundaries: Array<{ id: number; boundary_utc: string; explanation: string; context: any }>
  conditions?: Array<{ id: number; tag_id: string; display_name: string; raw_data_type: string | null; data_kind: DataKind; operator: string; minimum?: string | null; maximum?: string | null; comparison_value?: unknown; delta_amount?: string | null; delta_window_minutes?: number | null; duration_minutes: number }>
}

export type MinuteDetail = {
  analysis_id: number
  minute_utc: string
  segment: Segment
  conditions: Record<string, { condition_id: number; tag_id: string; display_name: string; value: unknown; operator: string; minimum?: string | null; maximum?: string | null; comparison_value?: unknown; delta_amount?: string | null; delta_window_minutes?: number | null; duration_minutes: number; raw_matched: boolean | null; pending_progress: { current: number; required: number }; qualified_active: boolean; lane_state: string; delta_reference?: { minute_utc: string; value: unknown } | null; source?: { quality?: string | null; status_code?: string | null; error_text?: string | null } | null }>
  groups: Record<string, boolean>
  root_expression_result: boolean
  active_condition_ids: number[]
  missing_tag_ids: string[]
  training_eligible: boolean
  training_ineligibility_reason: string | null
}
