// Optional integrations: plugins without their packages show as unavailable,
// and a Promptfoo result file imports with upstream verdicts and provenance.

import { fileURLToPath } from 'node:url'
import { expect, selectDemoProject, test } from './fixtures'

const PROMPTFOO_FIXTURE = fileURLToPath(new URL('../../fixtures/integrations/promptfoo/results.json', import.meta.url))

test('import Promptfoo results and inspect upstream verdicts', async ({ page }) => {
  await selectDemoProject(page)
  await page.goto('/settings')
  const plugins = page.getByTestId('integrations')
  await expect(plugins).toContainText('Promptfoo')
  await expect(plugins).toContainText('Inspect AI')
  await expect(plugins).toContainText('Ragas')
  await expect(plugins).toContainText('run unavailable') // inspect_ai is not installed
  await expect(plugins).toContainText('grade unavailable') // ragas is not installed

  await page.getByLabel('Format').selectOption('promptfoo')
  await page.locator('#external-file').setInputFiles(PROMPTFOO_FIXTURE)
  await page.getByRole('button', { name: 'Import results' }).click()
  await expect(page).toHaveURL(/\/external\/[0-9a-f-]+$/)
  await expect(page.getByRole('heading', { level: 1, name: 'Promptfoo results' })).toBeVisible()

  const summary = page.getByTestId('external-summary')
  await expect(summary).toContainText('Upstream pass')
  const table = page.getByTestId('external-results')
  await expect(table.locator('tbody tr')).toHaveCount(3)
  await expect(table).toContainText('not-icontains')
  await expect(table).toContainText('Synthetic provider error')
  await expect(page.getByRole('columnheader', { name: 'Scores (not probabilities)' })).toBeVisible()

  await page.getByLabel('Filter by status').selectOption('fail')
  await expect(table.locator('tbody tr')).toHaveCount(1)
  await expect(table).toContainText('PF-02')

  await page.goto('/settings')
  await expect(page.getByTestId('external-imports')).toContainText('results.json')
})
