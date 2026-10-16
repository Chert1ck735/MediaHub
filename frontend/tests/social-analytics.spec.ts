import { test, expect } from '@playwright/test';

test('statistics supports TG/OK and keeps an empty municipality map mounted', async ({ page }) => {
  const errors: string[] = [];
  const analyticsUrls: string[] = [];
  page.on('request', r => { if (r.url().includes('/api/analytics/')) analyticsUrls.push(r.url()); });
  page.on('pageerror', e => errors.push(e.message));
  await page.addInitScript(() => {
    localStorage.setItem('protechno_jwt', 'fixture-token');
    localStorage.setItem('protechno_session', 'Тест');
    class Collection {
      events = { add() {}, remove() {} };
      options = { set() {} };
      add() {} removeAll() {}
    }
    (window as any).mapCreates = 0;
    (window as any).ymaps = {
      ready: (cb: () => void) => cb(),
      Map: class extends Collection {
        geoObjects = new Collection();
        container = { fitToViewport() {} };
        constructor() { super(); (window as any).mapCreates++; }
        getZoom() { return 8; } setCenter() {} destroy() {}
      },
      GeoObjectCollection: Collection, Polygon: Collection, Placemark: Collection,
    };
  });
  const sources = [...Array(239).fill('vk'), 'telegram', 'ok'].map((network, i) => ({
    id: `public-${i}`, name: `${network}-${i}`, links: [{ id: `00000000-0000-0000-0000-${String(i + 1).padStart(12, '0')}`, social_network_code: network, social_network_name: network, url: '' }],
  }));
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    let data: any = [];
    if (url.pathname === '/api/auth/me') data = { id: 'user', name: 'Тест', role: 'admin' };
    if (url.pathname === '/api/analytics/publics') data = sources;
    if (url.pathname === '/api/analytics/classification/queue') data = null;
    if (url.pathname === '/api/analytics/summary') data = { generated_at: '2026-09-16', top_pains: [], category_breakdown: [], sentiment_breakdown: {}, message_type_breakdown: {}, relevance_breakdown: {}, sla: {} };
    if (url.pathname === '/api/report/preview') data = { total_posts: 0, top_posts: [], all_posts: [], points: [] };
    if (url.pathname === '/api/analytics/case-comments') data = [{ id: 'comment', text: 'Нет воды', comment_url: 'https://t.me/test/42?comment=123', author_name: 'Тест' }];
    if (url.pathname === '/api/analytics/pain-map') data = url.searchParams.get('municipality_name') ? [] : [{ lat: 56, lon: 93, name: 'Тест', count: 1, cases: ['Тест'], pains: [], categories: [] }];
    await route.fulfill({ json: data });
  });
  await page.goto('/analytics?view=map&case=Тест');
  await expect(page.locator('.pain-map-canvas')).toBeVisible();
  await expect(page.locator('.analytics-source-chips')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Все источники', exact: true })).toBeVisible();
  await expect.poll(() => page.evaluate(() => (window as any).mapCreates)).toBeGreaterThan(0);
  const creates = await page.evaluate(() => (window as any).mapCreates);
  await expect(page.getByRole('link', { name: 'TG', exact: true })).toHaveAttribute('href', 'https://t.me/test/42?comment=123');
  await page.getByRole('button', { name: /Все муниципалитеты/ }).click();
  await page.getByRole('option').filter({ hasText: 'Ачинский' }).first().click();
  await expect(page.getByRole('status').filter({ hasText: 'Нет обращений' })).toBeVisible();
  await expect(page.locator('.pain-map-canvas')).toBeVisible();
  expect(await page.evaluate(() => (window as any).mapCreates)).toBe(creates);
  await page.getByRole('option').filter({ hasText: 'Ачинский' }).first().click();
  await expect(page.getByRole('status').filter({ hasText: 'Нет обращений' })).toHaveCount(0);
  expect(await page.evaluate(() => (window as any).mapCreates)).toBe(creates);
  await page.getByRole('button', { name: 'Статистика', exact: true }).click();
  const platforms = page.locator('.analytics-platform-select');
  await expect(platforms.locator('option')).toHaveText(['VK', 'TG', 'Одноклассники']);
  const request = page.waitForRequest(r => r.url().includes('/api/report/preview') && r.postDataJSON()?.platform === 'telegram');
  await platforms.selectOption('telegram');
  expect((await request).postDataJSON().public_social_link_id).toBeNull();
  await expect(page.locator('.analytics-source-chips')).toHaveCount(0);
  await expect(page.getByRole('button', { name: 'Все источники', exact: true })).toBeVisible();
  // Явный выбор работает; удаление последней площадки не выбирает все снова.
  await page.getByRole('button', { name: 'Все источники', exact: true }).click();
  await page.locator('.analytics-source-picker-menu button').filter({ hasText: 'telegram-239' }).click();
  await expect(page.locator('.analytics-source-chip')).toHaveCount(1);
  await page.getByRole('button', { name: 'Выбрано площадок: 1', exact: true }).click();
  await page.getByRole('button', { name: 'Убрать telegram-239', exact: true }).click();
  await expect(page.locator('.analytics-source-chips')).toHaveCount(0);
  await platforms.selectOption('vk');
  await expect(page.getByRole('button', { name: 'Все источники', exact: true })).toBeVisible();
  await expect(page.locator('.analytics-source-chips')).toHaveCount(0);
  expect(analyticsUrls.every(url => url.length < 2048)).toBeTruthy();
  expect(analyticsUrls.some(url => url.includes('00000000-0000-0000-0000-000000000000'))).toBeFalsy();
  expect(errors).toEqual([]);
});
