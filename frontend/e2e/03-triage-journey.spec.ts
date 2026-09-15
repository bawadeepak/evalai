// demo → M05 → confirm → promote → rerun → compare → export → import into a new project.

import { expect, selectDemoProject, selectOptionMatching, setReviewer, test } from './fixtures'

test('triage a stable failure through promotion, rerun, comparison and exchange', async ({ page }) => {
  test.setTimeout(180_000)
  await setReviewer(page)
  await selectDemoProject(page)

  await page.goto('/runs')
  await page.getByRole('link', { name: 'Demo · memory-triage' }).click()
  const memoryRunUrl = page.url()
  const memoryRunId = memoryRunUrl.split('/runs/')[1]!.split('?')[0]!
  await page.locator('.page-header').getByRole('link', { name: 'Triage' }).click()

  // Critical failure first; evidence shows 0 / 20 and no fabricated confidence.
  const first = page.locator('.queue-item').first()
  await expect(first).toContainText('M05')
  await expect(first).toContainText('critical failure')
  await first.click()
  await expect(page.getByRole('heading', { name: 'M05 · candidate' })).toBeVisible()
  await expect(page.getByTestId('prediction-unavailable')).toContainText('Unavailable')
  await expect(page.locator('#evidence-title')).toBeVisible()
  for (const tab of ['Output diff', 'Trace', 'Memory state', 'Grades', 'Attempts', 'Overview']) {
    await page.getByRole('tab', { name: tab }).click()
    await expect(page.getByRole('tab', { name: tab })).toHaveAttribute('aria-selected', 'true')
  }

  const review = page.getByTestId('review-panel')
  await review.getByRole('radio', { name: 'Confirm failure' }).click()
  await review.getByRole('button', { name: 'Record review' }).click()
  await expect(page.getByTestId('review-history')).toContainText('confirm failure by E2E Reviewer')
  await expect(page.getByTestId('adjudicated')).toContainText('human review')

  const promote = page.getByTestId('promote')
  await expect(promote).toBeVisible()
  await promote.getByRole('button', { name: 'Create regression version' }).click()
  await expect(promote.getByRole('status')).toContainText('Created')
  await promote.getByRole('link', { name: 'Rerun it' }).click()

  await expect(page.getByRole('heading', { level: 1, name: 'Run setup' })).toBeVisible()
  await expect(page.getByLabel('Dataset version')).toHaveValue(/.+/)
  await selectOptionMatching(page.getByLabel('Baseline (optional)'), /MemoryAI baseline v1 \(demo\)/)
  await selectOptionMatching(page.getByLabel('Candidate', { exact: true }), /MemoryAI candidate v2 \(demo\)/)
  await page.getByLabel('Repeats per case').fill('2')
  await expect(page.getByTestId('run-valid')).toBeVisible()
  await expect(page.getByTestId('planned-trials')).toContainText('1 × 2 × 2 = 4')
  await page.getByTestId('start-run').dblclick() // idempotency: one run
  await expect(page).toHaveURL(/\/runs\/[0-9a-f-]+$/)
  const rerunId = page.url().split('/runs/')[1]!
  await expect(page.locator('.page-header')).toContainText(/Completed/, { timeout: 60_000 })

  // The rerun is listed alongside the original, which stays unchanged.
  await page.goto('/runs')
  await expect(page.locator(`a[href="/runs/${rerunId}"]`)).toBeVisible()
  await expect(page.locator(`a[href="/runs/${memoryRunId}"]`)).toBeVisible()

  // Compare the original demo candidate with the rerun candidate.
  await page.goto(`/compare?baseline=${memoryRunId}&baseline_key=candidate&candidate=${rerunId}&candidate_key=candidate`)
  const comparison = page.getByTestId('comparison')
  await expect(comparison).toBeVisible()
  const order = await comparison.locator('h2').allTextContents()
  expect(order[0]).toContain('Compatibility')
  await expect(page.getByTestId('gate-banner')).toHaveAttribute('data-verdict', /ready|blocked|inconclusive/)
  await page.getByRole('button', { name: 'Save comparison' }).click()
  const [evidence] = await Promise.all([page.waitForEvent('download'), page.getByRole('button', { name: 'Export decision evidence' }).click()])
  expect(evidence.suggestedFilename()).toMatch(/^comparison-.*\.json$/)

  // Export the project, then import it as a new project.
  await page.goto('/settings')
  await page.getByRole('button', { name: 'Create export' }).click()
  const exportsList = page.getByTestId('exports')
  const downloadButton = exportsList.getByRole('button', { name: 'Download' }).first()
  await expect(downloadButton).toBeVisible({ timeout: 60_000 })
  const [archive] = await Promise.all([page.waitForEvent('download'), downloadButton.click()])
  const archivePath = await archive.path()
  await page.getByLabel('Archive (.zip)').setInputFiles(archivePath)
  await expect(page.getByText('Archive is valid')).toBeVisible()
  await page.getByLabel('Name for the imported project (optional)').fill('Imported demo copy')
  await page.getByRole('button', { name: 'Import as new project' }).click()
  const status = page.getByTestId('import-status')
  await expect(status).toContainText(/succeeded|completed/, { timeout: 60_000 })
  await status.getByRole('button', { name: 'Switch to the imported project' }).click()
  const project = page.getByLabel('Project', { exact: true })
  await expect(project).toHaveValue(/.+/)
  await expect(project.locator('option:checked')).toContainText('Imported demo copy')
})
