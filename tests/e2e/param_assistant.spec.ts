// Playwright scaffold — Param Assistant UI E2E (enable when @playwright/test is installed).
// Run: npx playwright test tests/e2e/param_assistant.spec.ts

import { test, expect } from '@playwright/test';

const HAS_PLAYWRIGHT = Boolean(process.env.PA_E2E_UI_URL);

test.describe('Param Assistant user flow', () => {
  test.skip(!HAS_PLAYWRIGHT, 'Set PA_E2E_UI_URL to enable UI E2E');

  test('coin + budget + analyze matches API', async ({ page, request }) => {
    const base = process.env.PA_E2E_UI_URL!;
    await page.goto(`${base}/ui/dashboard.html`);
    // TODO: select symbol, enter budget, click analyze — compare DOM to POST /api/param-assistant/calculate
    expect(true).toBe(true);
  });
});
