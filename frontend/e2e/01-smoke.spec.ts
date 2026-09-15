import { expect, selectDemoProject, test } from './fixtures'

const SCREENS: [string, string][] = [
  ['/', 'Overview'],
  ['/scenarios', 'Scenarios'],
  ['/scenarios/new', 'New scenario'],
  ['/datasets', 'Datasets'],
  ['/runs', 'Runs'],
  ['/runs/new', 'Run setup'],
  ['/triage', 'Triage'],
  ['/probability', 'Probability Lab'],
  ['/compare', 'Compare'],
  ['/providers', 'Providers'],
  ['/settings', 'Settings'],
]

test.beforeEach(async ({ page }) => {
  await selectDemoProject(page)
})

for (const [path, title] of SCREENS) {
  test(`${title} renders without an error state`, async ({ page }) => {
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await page.goto(path)
    await expect(page.getByRole('heading', { level: 1, name: title })).toBeVisible()
    await expect(page.getByTestId('demo-banner')).toBeVisible()
    await expect(page.locator('[data-state="error"]')).toHaveCount(0)
    await expect(page.getByTestId('worker-status')).toContainText('running')
    expect(errors).toEqual([])
  })
}

test('detail screens open from their lists', async ({ page }) => {
  await page.goto('/datasets')
  await page.getByRole('link', { name: 'memory-triage-demo' }).click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('memory-triage-demo')
  await expect(page.getByRole('button', { name: 'M03' })).toBeVisible()

  await page.goto('/scenarios')
  await page.getByRole('link', { name: 'memoryai-lifecycle' }).first().click()
  await expect(page.getByRole('heading', { level: 1 })).toContainText('memoryai-lifecycle')

  await page.goto('/runs')
  await page.getByRole('link', { name: 'Demo · memory-triage' }).click()
  await expect(page.getByTestId('results-matrix')).toBeVisible()
})

test('demo counts come from stored grades', async ({ page }) => {
  await page.goto('/runs')
  await page.getByRole('link', { name: 'Demo · memory-triage' }).click()
  const row = (id: string) => page.getByTestId(`case-row-${id}`)
  await expect(row('M03')).toContainText('18 / 20')
  await expect(row('M06')).toContainText('16 / 20')
  await expect(row('M05')).toContainText('0 / 20')
  await expect(row('M03')).toContainText('20 / 20')
  await expect(page.getByTestId('representation-definition')).toContainText('Raw text')
})
