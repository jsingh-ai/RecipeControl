import { expect, test } from '@playwright/test'

test('create rule, analyze, label, reload, detect duplicate, and change timezone', async ({ page }) => {
  let versionStatus = 'DRAFT'
  let classification: { id: number; name: string; active: boolean } | null = null
  let label: any = null
  let analysisCreated = false
  const machine = { id: 1, source_key: 'fixture-line-1', name: 'Fixture Line 1', enabled: true }
  const condition = { id: 1, source_tag_key: 'temperature', source_display_name: 'Temperature', source_data_type: 'numeric', operator: 'ABOVE_MAXIMUM', maximum: '250', duration_minutes: 0 }
  const version = () => ({ id: 10, rule_set_id: 5, version_number: 1, status: versionStatus, root_operator: 'OR', groups: versionStatus === 'LOCKED' ? [{ id: 2, internal_operator: 'OR', conditions: [condition] }] : [] })
  const segment = () => ({ id: 50, analysis_id: 20, start_utc: '2026-06-11T19:50:00Z', end_utc: '2026-06-11T20:20:00Z', system_state: 'BREAK', contributing_condition_ids: [1], quality_label: label?.quality_label ?? null, classification_id: label?.classification_id ?? null, classification_name: classification?.name ?? null, note: label?.note ?? null, active_live: false, training_eligible: Boolean(label) })

  await page.route('**/api/**', async (route) => {
    const request = route.request(); const url = new URL(request.url()); const path = url.pathname
    const fulfill = (body: unknown, status = 200) => route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) })
    if (path.endsWith('/machines')) return fulfill([machine])
    if (path.includes('/machines/1/tags')) return fulfill({ items: [{ key: 'temperature', display_name: 'Temperature', raw_data_type: 'Double', data_kind: 'numeric', units: '°F' }, { key: 'pressure', display_name: 'Pressure', raw_data_type: 'Double', data_kind: 'numeric', units: 'psi' }, { key: 'speed', display_name: 'Speed', raw_data_type: 'Double', data_kind: 'numeric', units: 'ft/min' }, { key: 'alarm_code', display_name: 'Alarm Code', raw_data_type: 'Int32', data_kind: 'numeric' }, { key: 'motor_running', display_name: 'Motor Running', raw_data_type: 'Boolean', data_kind: 'boolean' }], limit: 25, offset: 0, has_more: false })
    if (path.endsWith('/rule-sets') && request.method() === 'POST') return fulfill({ rule_set_id: 5, version: version() }, 201)
    if (path.includes('/rule-versions/10') && request.method() === 'PUT') {
      const payload = JSON.parse(request.postData()!)
      expect(payload.groups).toHaveLength(2)
      expect(payload.groups[0].conditions).toHaveLength(2)
      expect(payload.groups[1].conditions).toHaveLength(2)
      return fulfill({ ...version(), groups: payload.groups })
    }
    if (path.endsWith('/rule-versions/10/lock')) { versionStatus = 'LOCKED'; return fulfill(version()) }
    if (path.endsWith('/rule-sets')) return fulfill([{ id: 5, machine_id: 1, name: 'Fixture grouped rule', archived: false, versions: [version()] }])
    if (path.endsWith('/analyses') && request.method() === 'POST') {
      if (analysisCreated && !JSON.parse(request.postData()!).create_duplicate) return fulfill({ code: 'DUPLICATE_ANALYSIS', message: 'An analysis already exists for this definition and period.', matches: [{ id: 20, status: 'COMPLETE' }] }, 409)
      analysisCreated = true; return fulfill({ id: 20, machine_id: 1, rule_version_id: 10, status: 'COMPLETE', selected_start_utc: '2026-06-11T19:50:00Z', selected_end_utc: '2026-06-23T14:20:00Z', mode: 'HISTORICAL' }, 202)
    }
    if (path.endsWith('/analyses') || path.endsWith('/analyses/')) return fulfill([])
    if (path === '/api/analyses/20') return fulfill({ id: 20, machine_id: 1, rule_version_id: 10, status: 'COMPLETE', selected_start_utc: '2026-06-11T19:50:00Z', selected_end_utc: '2026-06-23T14:20:00Z', mode: 'HISTORICAL', job: { state: 'COMPLETE' } })
    if (path.endsWith('/analyses/20/timeline')) return fulfill({ analysis: { id: 20, machine_id: 1, rule_version_id: 10, status: 'COMPLETE', selected_start_utc: '2026-06-11T19:50:00Z', selected_end_utc: '2026-06-23T14:20:00Z', mode: 'HISTORICAL' }, segments: [segment()], condition_intervals: [{ id: 1, condition_id: 1, start_utc: segment().start_utc, end_utc: segment().end_utc, state: 'ACTIVE' }], boundaries: [{ id: 1, boundary_utc: segment().start_utc, explanation: 'Temperature exceeded 250.', context: {} }] })
    if (path.includes('/analyses/20/minutes/')) return fulfill({ segment: segment(), conditions: {}, active_condition_ids: [1], missing_tag_ids: [], groups: { 2: true }, root_expression_result: true, training_eligible: Boolean(label), training_ineligibility_reason: label ? null : 'A Good or Bad label is required' })
    if (path.includes('/trends')) return fulfill({ lookback_minutes: 15, series: [{ tag_id: 'temperature', display_name: 'Temperature', data_type: 'numeric', units: '°F', points: [{ minute_utc: '2026-06-11T19:50:00Z', value: '260', missing: false }] }] })
    if (path.endsWith('/classifications') && request.method() === 'GET') return fulfill(classification?.active ? [classification] : [])
    if (path.endsWith('/classifications') && request.method() === 'POST') { classification = { id: 9, name: JSON.parse(request.postData()!).name, active: true }; return fulfill(classification, 201) }
    if (path.endsWith('/analyses/20/segments/50') && request.method() === 'PATCH') { label = JSON.parse(request.postData()!); return fulfill(segment()) }
    return fulfill([])
  })

  await page.goto('/')
  await page.getByRole('button', { name: 'Rule Builder' }).click()
  await page.getByLabel('Machine').selectOption('1')
  await page.getByLabel('Definition name').fill('Fixture grouped rule')
  await page.getByRole('button', { name: 'Create Draft' }).click()
  await page.getByRole('combobox', { name: 'Variable 1' }).fill('Temperature')
  await page.getByRole('option', { name: /Temperature/ }).click()
  await page.getByLabel('Operator 1').selectOption('ABOVE_MAXIMUM')
  await page.getByLabel('Maximum').fill('250')
  await page.getByLabel('Activation minutes').fill('5')
  await page.getByRole('button', { name: 'Add Condition' }).click()
  await page.getByRole('combobox', { name: 'Variable 2' }).fill('Pressure')
  await page.getByRole('option', { name: /Pressure/ }).click()
  await page.getByLabel('Operator 2').selectOption('BELOW_MINIMUM')
  await page.getByLabel('Minimum').fill('40')
  await page.getByLabel('Activation minutes').nth(1).fill('2')
  await page.getByRole('button', { name: 'Add Group' }).click()
  await page.getByRole('combobox', { name: 'Variable 1' }).nth(1).fill('Alarm Code')
  await page.getByRole('option', { name: /Alarm Code/ }).click()
  await page.getByLabel('Operator 1').nth(1).selectOption('EQUALS')
  await page.getByLabel('Comparison').fill('12')
  await page.getByRole('button', { name: 'Add Condition' }).nth(1).click()
  await page.getByRole('combobox', { name: 'Variable 2' }).nth(1).fill('Motor Running')
  await page.getByRole('option', { name: /Motor Running/ }).click()
  await page.getByLabel('Operator 2').nth(1).selectOption('EQUALS')
  await page.getByLabel('Comparison').nth(1).selectOption('false')
  await page.getByRole('button', { name: 'Save & Lock Version' }).click()
  await expect(page.getByText(/Version 1 saved/)).toBeVisible()

  await page.getByRole('button', { name: 'Timeline' }).click()
  await page.getByLabel('Timeline machine').selectOption('1')
  await page.getByLabel('Saved rule version').selectOption('10')
  await page.getByRole('button', { name: 'Analyze' }).click()
  await expect(page.getByText('BREAK').first()).toBeVisible()
  await page.getByRole('button', { name: /Unlabeled/ }).first().click()
  await page.getByLabel(/Bad/).check()
  await page.getByLabel('New classification').fill('Roll Change')
  await page.getByRole('button', { name: 'Add' }).click()
  await page.getByLabel('Notes').fill('Confirmed stop at exact point')
  await page.getByRole('button', { name: 'Save segment label' }).click()
  await page.reload()
  await page.getByLabel('Timeline machine').selectOption('1')
  await page.getByLabel('Saved rule version').selectOption('10')
  await page.getByRole('button', { name: 'Analyze' }).click()
  await expect(page.getByRole('dialog', { name: 'Duplicate analysis' })).toBeVisible()
  await expect(page.getByRole('button', { name: 'Open Existing' })).toBeVisible()
  await page.getByRole('button', { name: 'Open Existing' }).click()
  await page.getByRole('button', { name: 'Central' }).click()
  await expect(page.getByRole('button', { name: 'Central' })).toHaveAttribute('aria-pressed', 'true')
})
