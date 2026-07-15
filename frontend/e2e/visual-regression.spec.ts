import { expect, Page, test, TestInfo } from '@playwright/test'
import { mkdirSync } from 'node:fs'
import path from 'node:path'

type AnalysisState = 'COMPLETE' | 'RUNNING' | 'FAILED'

const machine = { id: 1, source_key: 'press-line', name: 'Press Line 4', enabled: true }
const conditionOne = { id: 1, source_tag_key: 'temperature', source_display_name: 'Motor Temperature', source_raw_data_type: 'Double', source_data_type: 'numeric', operator: 'ABOVE_MAXIMUM', maximum: '250', duration_minutes: 5 }
const conditionTwo = { id: 2, source_tag_key: 'motor_running', source_display_name: 'Motor Running', source_raw_data_type: 'Boolean', source_data_type: 'boolean', operator: 'EQUALS', comparison_value: false, duration_minutes: 2 }
const version = { id: 10, rule_set_id: 5, version_number: 2, status: 'LOCKED', root_operator: 'OR', groups: [{ id: 7, internal_operator: 'AND', conditions: [conditionOne] }, { id: 8, internal_operator: 'OR', conditions: [conditionTwo] }] }
const analysis = (status: AnalysisState) => ({ id: 20, machine_id: 1, rule_version_id: 10, selected_start_utc: '2026-06-11T19:50:00Z', selected_end_utc: '2026-06-11T20:39:00Z', mode: 'HISTORICAL', status, error_message: status === 'FAILED' ? 'The source query timed out. Verify collector connectivity and retry.' : null })

function segment(id: number, start: string, end: string, state: string, quality: string | null, conditionIds: number[] = []) {
  return { id, analysis_id: 20, start_utc: start, end_utc: end, system_state: state, contributing_condition_ids: conditionIds, quality_label: quality, classification_id: quality === 'BAD' ? 4 : null, classification_name: quality === 'BAD' ? 'Confirmed process stop' : null, note: null, active_live: false, training_eligible: quality === 'GOOD' || quality === 'BAD' }
}

const regularSegments = [
  segment(101, '2026-06-11T19:50:00Z', '2026-06-11T20:00:00Z', 'NORMAL', 'GOOD'),
  segment(102, '2026-06-11T20:00:00Z', '2026-06-11T20:12:00Z', 'BREAK', 'BAD', [1]),
  segment(103, '2026-06-11T20:12:00Z', '2026-06-11T20:25:00Z', 'NORMAL', 'UNSURE'),
  segment(104, '2026-06-11T20:25:00Z', '2026-06-11T20:40:00Z', 'BREAK', null, [2]),
]
const systemSegments = [
  segment(201, '2026-06-11T19:50:00Z', '2026-06-11T20:02:00Z', 'NORMAL', null),
  segment(202, '2026-06-11T20:02:00Z', '2026-06-11T20:16:00Z', 'DATA_GAP', 'GOOD'),
  segment(203, '2026-06-11T20:16:00Z', '2026-06-11T20:30:00Z', 'INSUFFICIENT_HISTORY', 'UNSURE'),
  segment(204, '2026-06-11T20:30:00Z', '2026-06-11T20:40:00Z', 'BREAK', 'BAD', [1]),
]

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce', colorScheme: 'dark' })
})

async function mockApi(page: Page, status: AnalysisState = 'COMPLETE', withSystemSegments = false, ruleMode: 'locked' | 'draft' | 'blank' = 'locked') {
  const segments = withSystemSegments ? systemSegments : regularSegments
  const draft = { ...version, version_number: 1, status: 'DRAFT', groups: ruleMode === 'blank' ? [] : version.groups }
  await page.route('**/api/**', async (route) => {
    const request = route.request()
    const url = new URL(request.url())
    const routePath = url.pathname
    const fulfill = (body: unknown, responseStatus = 200) => route.fulfill({ status: responseStatus, contentType: 'application/json', body: JSON.stringify(body) })
    if (routePath.endsWith('/machine-catalog')) return fulfill({ items: [machine], source_sync_warning: null })
    if (routePath.endsWith('/machines')) return fulfill([machine])
    if (routePath.includes('/machines/1/tags')) return fulfill({ items: [{ key: 'temperature', display_name: 'Motor Temperature', raw_data_type: 'Double', data_kind: 'numeric', units: '°F' }, { key: 'motor_running', display_name: 'Motor Running', raw_data_type: 'Boolean', data_kind: 'boolean' }], limit: 25, offset: 0, has_more: false })
    if (routePath.endsWith('/rule-sets') && request.method() === 'POST') return fulfill({ rule_set_id: 5, version: draft }, 201)
    if (routePath.endsWith('/rule-sets')) return fulfill(ruleMode === 'blank' ? [] : [{ id: 5, machine_id: 1, name: 'Press operating envelope', archived: false, versions: [ruleMode === 'draft' ? draft : version] }])
    if (routePath === '/api/rule-versions/10') return fulfill(ruleMode === 'draft' ? draft : version)
    if (routePath.includes('/rule-versions/10/classifications')) return fulfill([{ id: 4, name: 'Confirmed process stop', active: true }])
    if (routePath === '/api/analyses') return fulfill([analysis(status)])
    if (routePath === '/api/analyses/20') return fulfill({ ...analysis(status), job: { state: status } })
    if (routePath.endsWith('/analyses/20/timeline')) return fulfill({ analysis: analysis(status), segments, conditions: [{ id: 1, tag_id: 'temperature', display_name: 'Motor Temperature', raw_data_type: 'Double', data_kind: 'numeric', operator: 'ABOVE_MAXIMUM', maximum: '250', duration_minutes: 5, group_id: 7, group_operator: 'AND' }, { id: 2, tag_id: 'motor_running', display_name: 'Motor Running', raw_data_type: 'Boolean', data_kind: 'boolean', operator: 'EQUALS', comparison_value: false, duration_minutes: 2, group_id: 8, group_operator: 'OR' }], condition_intervals: [{ id: 1, condition_id: 1, start_utc: '2026-06-11T19:50:00Z', end_utc: '2026-06-11T20:40:00Z', state: 'ACTIVE' }, { id: 2, condition_id: 2, start_utc: '2026-06-11T19:50:00Z', end_utc: '2026-06-11T20:40:00Z', state: 'PENDING' }], boundaries: [] })
    if (routePath.includes('/analyses/20/minutes/')) return fulfill({ analysis_id: 20, minute_utc: '2026-06-11T20:05:00Z', segment: segments[1], conditions: { 1: { condition_id: 1, tag_id: 'temperature', display_name: 'Motor Temperature', value: '263.4', operator: 'ABOVE_MAXIMUM', maximum: '250', duration_minutes: 5, raw_matched: true, pending_progress: { current: 5, required: 5 }, qualified_active: true, lane_state: 'ACTIVE', source: { quality: 'Good', status_code: '0x00000000', error_text: null } }, 2: { condition_id: 2, tag_id: 'motor_running', display_name: 'Motor Running', value: false, operator: 'EQUALS', comparison_value: false, duration_minutes: 2, raw_matched: true, pending_progress: { current: 1, required: 2 }, qualified_active: false, lane_state: 'PENDING', source: { quality: 'Uncertain', status_code: '0x40000000', error_text: 'Late source timestamp' } } }, groups: { 7: true, 8: false }, root_expression_result: true, active_condition_ids: [1], missing_tag_ids: [], training_eligible: true, training_ineligibility_reason: null })
    if (routePath.includes('/analyses/20/trends')) return fulfill({ lookback_minutes: 15, series: [{ tag_id: 'temperature', display_name: 'Motor Temperature', data_type: 'numeric', units: '°F', points: [{ minute_utc: '2026-06-11T19:55:00Z', value: '244', missing: false }, { minute_utc: '2026-06-11T20:05:00Z', value: '263.4', missing: false }] }, { tag_id: 'pressure', display_name: 'Hydraulic Pressure', data_type: 'numeric', units: 'psi', points: [{ minute_utc: '2026-06-11T19:55:00Z', value: '1980', missing: false }, { minute_utc: '2026-06-11T20:05:00Z', value: '2120', missing: false }] }, { tag_id: 'motor_running', display_name: 'Motor Running', data_type: 'boolean', points: [{ minute_utc: '2026-06-11T19:55:00Z', value: true, missing: false }, { minute_utc: '2026-06-11T20:05:00Z', value: false, missing: false }] }] })
    if (routePath.includes('/rule-versions/10') && request.method() === 'PUT') return fulfill(draft)
    return fulfill({})
  })
}

async function capture(page: Page, testInfo: TestInfo, name: string) {
  const directory = path.resolve(process.cwd(), '../docs/screenshots/visual')
  mkdirSync(directory, { recursive: true })
  await page.screenshot({ path: path.join(directory, testInfo.project.name + '-' + name + '.png'), animations: 'disabled' })
}

async function openSavedAnalysis(page: Page) {
  await page.goto('/')
  await page.getByLabel('Timeline machine').selectOption('1')
  await page.getByLabel('Load saved analysis').selectOption('20')
}

test('empty timeline', async ({ page }, testInfo) => {
  await mockApi(page)
  await page.goto('/')
  await expect(page.getByRole('heading', { name: 'No analysis selected' })).toBeVisible()
  await capture(page, testInfo, 'empty-timeline')
})

test('populated timeline', async ({ page }, testInfo) => {
  await mockApi(page)
  await openSavedAnalysis(page)
  await expect(page.getByRole('img', { name: /Scrollable primary/ })).toBeVisible()
  await page.getByRole('img', { name: /Scrollable primary/ }).scrollIntoViewIfNeeded()
  await capture(page, testInfo, 'populated-timeline')
})

test('data gap and insufficient history patterns', async ({ page }, testInfo) => {
  await mockApi(page, 'COMPLETE', true)
  await openSavedAnalysis(page)
  await expect(page.getByRole('button', { name: /Data Gap/ })).toBeVisible()
  await page.getByRole('img', { name: /Scrollable primary/ }).scrollIntoViewIfNeeded()
  await capture(page, testInfo, 'system-segments')
})

test('segment detail drawer', async ({ page }, testInfo) => {
  await mockApi(page)
  await openSavedAnalysis(page)
  await page.getByRole('button', { name: /Bad.*BREAK/ }).click()
  await expect(page.getByRole('complementary', { name: 'Segment detail' })).toBeVisible()
  await capture(page, testInfo, 'segment-detail-drawer')
})

test('rule builder with multiple groups', async ({ page }, testInfo) => {
  await mockApi(page, 'COMPLETE', false, 'draft')
  await page.goto('/')
  await page.getByRole('button', { name: 'Rule Builder' }).click()
  await page.getByLabel('Machine').selectOption('1')
  await page.getByRole('button', { name: /v1 · DRAFT/ }).click()
  await expect(page.getByRole('heading', { name: 'Group 2' })).toBeVisible()
  await page.evaluate(() => { document.body.style.zoom = '0.78' })
  await capture(page, testInfo, 'rule-builder-groups')
})

test('rule validation errors', async ({ page }, testInfo) => {
  await mockApi(page, 'COMPLETE', false, 'blank')
  await page.goto('/')
  await page.getByRole('button', { name: 'Rule Builder' }).click()
  await page.getByLabel('Machine').selectOption('1')
  await page.getByLabel('Definition name').fill('Invalid draft demonstration')
  await page.getByRole('button', { name: 'Create Draft' }).click()
  await page.getByRole('button', { name: 'Save Draft' }).click()
  const error = page.getByRole('alert')
  await expect(error).toContainText('selected tag')
  await error.scrollIntoViewIfNeeded()
  await capture(page, testInfo, 'validation-errors')
})

test('analysis loading state', async ({ page }, testInfo) => {
  await mockApi(page, 'RUNNING')
  await openSavedAnalysis(page)
  await expect(page.getByRole('status', { name: 'Generating historical timeline' })).toBeVisible()
  await capture(page, testInfo, 'analysis-loading')
})

test('analysis failed state', async ({ page }, testInfo) => {
  await mockApi(page, 'FAILED')
  await openSavedAnalysis(page)
  await expect(page.getByRole('alert')).toContainText('source query timed out')
  await capture(page, testInfo, 'analysis-failed')
})
