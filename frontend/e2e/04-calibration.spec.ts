// An invalid calibration split is blocked; a valid fit updates the plots.

import { expect, selectDemoProject, test } from './fixtures'

test('calibration refuses the held-out split and a valid fit updates the plots', async ({ page }) => {
  await selectDemoProject(page)
  await page.goto('/probability')
  // The event is named on the page (the <option> copy in the selector is not "visible").
  await expect(page.locator('strong', { hasText: '“the generated answer is correct”' })).toBeVisible()
  await expect(page.getByTestId('reliability-table')).toBeVisible()
  await expect(page.getByTestId('probability-cards')).toContainText('none — raw scores')

  // Bin drill-down without hover.
  await page.getByTestId('reliability-table').getByRole('button').first().click()
  await expect(page.getByTestId('bin-records')).toBeVisible()

  // Selective prediction: threshold at 1.0 has no accepted predictions.
  await page.getByRole('tab', { name: 'Selective prediction' }).click()
  const thumb = page.getByRole('slider', { name: 'Decision threshold' })
  await thumb.focus()
  await page.keyboard.press('End')
  await expect(page.getByTestId('selective-risk')).toContainText('Unavailable: no accepted predictions')

  await page.getByRole('tab', { name: 'Calibrate' }).click()
  await page.getByLabel('Fit on split').selectOption('test')
  await page.getByRole('button', { name: 'Fit calibrator' }).click()
  await expect(page.getByText('Calibration blocked')).toBeVisible()
  await expect(page.getByText('cannot be fitted on the held-out test split')).toBeVisible()

  await page.getByLabel('Fit on split').selectOption('calibration')
  await page.getByRole('button', { name: 'Fit calibrator' }).click()
  await expect(page.getByTestId('fit-ok')).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('button', { name: 'Calibrated' })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.getByTestId('probability-cards')).toContainText('isotonic v1')
  await expect(page.getByLabel('Calibrator', { exact: true })).not.toHaveValue('')

  await page.getByRole('tab', { name: 'Repeatability' }).click()
  await expect(page.getByTestId('repeatability-table')).toBeVisible()
  await expect(page.getByText('Token log-probabilities unavailable')).toBeVisible()
})
