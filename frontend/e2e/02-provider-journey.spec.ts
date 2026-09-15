// Provider journey: configure a provider with an unsupported setting, see run
// validation block it with a link to the cause, fix it as a new version and
// reach a valid run setup. No run is started (it would call a paid API), and
// the credential value never reaches the browser (see fixtures.leakGuard).

import { expect, selectDemoProject, selectOptionMatching, test } from './fixtures'

test('unsupported parameter is caught before enqueue and fixed as a new version', async ({ page }) => {
  await selectDemoProject(page)
  await page.goto('/providers?new=1')

  await page.getByLabel('Adapter').selectOption({ label: 'Anthropic' })
  await page.getByLabel('Name').fill('Claude candidate')
  await page.getByLabel('Model').fill('claude-sonnet-5')

  // Pasting a secret is refused client-side.
  await page.getByLabel('Credential reference').fill('sk-ant-live-0123456789abcdef0123')
  await page.getByRole('button', { name: 'Save configuration' }).click()
  await expect(page.getByText(/looks like a secret value/)).toBeVisible()

  await page.getByLabel('Credential reference').fill('EVALAI_E2E_SECRET')
  await page.getByLabel('Parameters (JSON object)').fill('{"seed": 7}')
  await page.getByRole('button', { name: 'Save configuration' }).click()
  await expect(page.getByRole('heading', { name: 'Claude candidate · v1' })).toBeVisible()
  await expect(page.getByText('Set in environment').first()).toBeVisible()

  await page.goto('/runs/new')
  await selectOptionMatching(page.getByLabel('Scenario'), /support-routing-regression v1/)
  await expect(page.getByLabel('Dataset version')).not.toHaveValue('')
  await selectOptionMatching(page.getByLabel('Candidate', { exact: true }), /Claude candidate v1/)

  const errors = page.getByTestId('run-errors')
  await expect(errors).toContainText("parameter 'seed' is unsupported")
  await expect(page.getByTestId('start-run')).toBeDisabled()
  await errors.getByRole('button', { name: 'Go to control' }).first().click()
  await expect(page.getByLabel('Candidate', { exact: true })).toBeFocused()

  await errors.getByRole('link', { name: 'Edit provider as new version' }).click()
  await expect(page.getByText('Saving creates version 2')).toBeVisible()
  await page.getByLabel('Parameters (JSON object)').fill('')
  await page.getByRole('button', { name: 'Save new version' }).click()
  await expect(page.getByRole('heading', { name: 'Claude candidate · v2' })).toBeVisible()

  await page.goto('/runs/new')
  await selectOptionMatching(page.getByLabel('Scenario'), /support-routing-regression v1/)
  await selectOptionMatching(page.getByLabel('Candidate', { exact: true }), /Claude candidate v2/)
  await expect(page.getByTestId('run-valid')).toBeVisible()
  await expect(page.getByTestId('planned-trials')).toContainText('24 × 1 × 5 = 120')
  await expect(page.getByTestId('start-run')).toBeEnabled()
  // Resolved configuration shows the credential by name only.
  await expect(page.locator('#setup-resolved')).toContainText('EVALAI_E2E_SECRET')
})
