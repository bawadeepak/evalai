import { test as base, expect, type Locator, type Page } from '@playwright/test'

/** selectOption() only takes exact labels; pick the first option whose text matches a pattern. */
export async function selectOptionMatching(select: Locator, pattern: RegExp) {
  await expect.poll(async () => (await select.locator('option').allTextContents()).some((t) => pattern.test(t))).toBe(true)
  const label = (await select.locator('option').allTextContents()).find((t) => pattern.test(t))!
  await select.selectOption({ label })
}

/** Must match eval_triage.testing.e2e_server.SENTINEL_SECRET (placed in EVALAI_E2E_SECRET). */
export const SENTINEL = 'sk-evalai-E2E-SENTINEL-3b1f6c0a-never-in-browser'

export const test = base.extend<{ leakGuard: void }>({
  // Every test asserts that no request or response carries the sentinel secret.
  leakGuard: [
    async ({ page }, use) => {
      const leaks: string[] = []
      page.on('request', (request) => {
        if ((request.postData() ?? '').includes(SENTINEL) || request.url().includes(SENTINEL)) leaks.push(`request ${request.url()}`)
      })
      page.on('response', async (response) => {
        try {
          const type = response.headers()['content-type'] ?? ''
          if (!type.includes('json') && !type.includes('text') && !type.includes('event-stream')) return
          if ((await response.text()).includes(SENTINEL)) leaks.push(`response ${response.url()}`)
        } catch {
          /* streamed or aborted responses cannot be read */
        }
      })
      await use()
      expect(leaks, 'a credential value reached the browser').toEqual([])
    },
    { auto: true },
  ],
})

export { expect }

export async function selectDemoProject(page: Page) {
  await page.goto('/')
  const select = page.getByLabel('Project', { exact: true })
  await expect(select.locator('option').first()).toBeAttached()
  // Below 768 px the selector lives in the collapsed navigation.
  const collapsed = !(await select.isVisible())
  if (collapsed) await page.getByRole('button', { name: 'Open navigation' }).click()
  const options = await select.locator('option').allTextContents()
  const demo = options.find((o) => o.includes('(demo)'))
  if (demo) await select.selectOption({ label: demo })
  if (collapsed) await page.getByRole('button', { name: 'Close navigation' }).click()
}

export async function setReviewer(page: Page, name = 'E2E Reviewer') {
  await page.goto('/settings')
  await page.getByLabel('Reviewer name').fill(name)
  await page.getByRole('button', { name: 'Save' }).click()
}
