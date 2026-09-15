// Keyboard-only triage, and every screen at phone width (375 px) without page-level
// horizontal scrolling; triage becomes Queue / Evidence / Review tabs.

import { expect, selectDemoProject, test } from './fixtures'

async function openDemoTriage(page: import('@playwright/test').Page) {
  await page.goto('/runs')
  await page.getByRole('link', { name: 'Demo · memory-triage' }).click()
  await page.locator('.page-header').getByRole('link', { name: 'Triage' }).click()
  await expect(page.locator('.queue-item').first()).toBeVisible()
}

test('triage works with the keyboard alone', async ({ page }) => {
  await selectDemoProject(page)
  await openDemoTriage(page)
  const items = page.locator('.queue-item')
  const current = page.locator('.queue-item[aria-current="true"]')
  await expect(current).toContainText('M05')

  await page.locator('body').press('j')
  await expect(current).toHaveText(await items.nth(1).textContent() ?? '')
  await page.locator('body').press('k')
  await expect(current).toContainText('M05')

  // Typing in a field never moves the queue.
  await page.getByLabel('Slice (key=value)').focus()
  await page.keyboard.type('j')
  await expect(current).toContainText('M05')
  await page.getByLabel('Slice (key=value)').fill('')

  await page.locator('body').click({ position: { x: 1, y: 1 } })
  await page.keyboard.press('Enter')
  await expect(page.locator('#evidence-title')).toBeFocused()
  await expect(page).toHaveURL(/pane=evidence/)

  // Tabs are reachable and operable from the keyboard.
  const overview = page.getByRole('tab', { name: 'Overview' })
  await overview.focus()
  await page.keyboard.press('ArrowRight')
  await expect(page.getByRole('tab', { name: 'Output diff' })).toHaveAttribute('aria-selected', 'true')

  // Review controls are buttons with visible labels; Space activates the focused one.
  const confirm = page.getByRole('radio', { name: 'Confirm failure' })
  await confirm.focus()
  await page.keyboard.press('Space')
  await expect(confirm).toHaveAttribute('aria-checked', 'true')

  await page.locator('body').click({ position: { x: 1, y: 1 } })
  await page.keyboard.press('Escape')
  await expect(page).toHaveURL(/pane=queue/)
})

const SCREENS = ['/', '/scenarios', '/scenarios/new', '/datasets', '/runs', '/runs/new', '/triage', '/probability', '/compare', '/providers', '/settings']

test.describe('phone width', () => {
  test.use({ viewport: { width: 375, height: 812 } })

  test('every screen fits without page-level horizontal scroll', async ({ page }) => {
    await selectDemoProject(page)
    for (const path of SCREENS) {
      await page.goto(path)
      await expect(page.getByRole('heading', { level: 1 })).toBeVisible()
      const overflow = await page.evaluate(() => document.documentElement.scrollWidth - window.innerWidth)
      expect(overflow, `${path} overflows by ${overflow}px`).toBeLessThanOrEqual(1)
    }
  })

  test('navigation collapses and triage splits into tabs', async ({ page }) => {
    await selectDemoProject(page)
    await page.goto('/runs')
    const nav = page.getByRole('navigation', { name: 'Primary' })
    await expect(nav).toBeHidden()
    await page.getByRole('button', { name: 'Open navigation' }).click()
    await expect(nav).toBeVisible()
    await nav.getByRole('link', { name: 'Runs' }).click()
    await expect(nav).toBeHidden()

    await openDemoTriage(page)
    const queue = page.locator('[data-pane="queue"]')
    const evidence = page.locator('[data-pane="evidence"]')
    const review = page.locator('[data-pane="review"]')
    await expect(queue).toBeVisible()
    await expect(evidence).toBeHidden()
    await page.locator('.queue-item').first().click()
    await expect(evidence).toBeVisible()
    await expect(queue).toBeHidden()
    await page.getByRole('tab', { name: 'Review' }).click()
    await expect(review).toBeVisible()
    await expect(review.getByRole('radio', { name: 'Confirm failure' })).toBeVisible()
  })
})
