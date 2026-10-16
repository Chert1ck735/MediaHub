import { test, expect, type Page } from '@playwright/test';

const names = ['Администрация Красноярска', 'Культура Красноярья', 'Спорт нашего города'];
const titles = ['Новый сквер открылся в Советском районе', 'Программа городских событий на неделю', 'Обновляем общественные пространства', 'Встреча с жителями: отвечаем на вопросы', 'Фестиваль семейного творчества', 'Как будет работать транспорт в выходные'];
const pubs = names.map((name, i) => ({ id: `public-${i}`, name, links: [{ id: `link-${i}`, title: name, url: '', social_network_code: 'vk' }] }));
const publication = (day: number, n: number, total: number) => ({
  id: `pub-${day}-${n}`, post_id: `post-${day}-${n}`, title: `${titles[n % titles.length]}${n > 5 ? ` · ${n + 1}` : ''}`,
  date: `2026-09-${String(day).padStart(2, '0')}`, start_time: `${String(2 + (n % 12)).padStart(2, '0')}:00`, end_time: '14:00',
  description: 'Тестовая публикация для проверки календаря', status: day > 7 ? 'scheduled' : 'published', platforms: [names[n % 3]],
  origin: 'manual', draft: '', tone: '', post_type: '', publication_ids: [`pub-${day}-${n}`],
  public_social_link_ids: [`link-${n % 3}`], publication_urls: ['https://vk.com/wall-1_2'], day_total: total,
});

async function fixture(page: Page, theme = 'light-blue') {
  await page.clock.setFixedTime(new Date('2026-09-07T05:00:00Z'));
  await page.addInitScript(({ theme }) => {
    localStorage.setItem('protechno_jwt', 'fixture-token');
    localStorage.setItem('protechno_session', 'Тихон');
    localStorage.setItem('protechno_theme', theme);
  }, { theme });
  await page.route('**/api/**', async route => {
    const url = new URL(route.request().url());
    const path = url.pathname;
    let data: unknown = [];
    if (path === '/api/auth/me') data = { id: 'user', name: 'Тихон', email: 'fixture@example.test', role: 'admin' };
    else if (path === '/api/analytics/publics') data = pubs;
    else if (path === '/api/vk/default-public') data = { public_social_link_id: 'link-0' };
    else if (path === '/api/analytics/classification/queue') data = null;
    else if (path === '/api/report/preview') data = { top_posts: [], all_posts: [], points: [], total_posts: 0 };
    else if (path === '/api/analytics/summary') data = {
      generated_at: '2026-09-07T05:00:00Z', source_label: 'Все сообщества', total_comment_count: 12840,
      classified_comment_count: 11260, appeal_count: 2384, pain_count: 24, platforms: ['vk'], top_pains: [],
      category_breakdown: [], sentiment_breakdown: {}, message_type_breakdown: {}, relevance_breakdown: {},
      sla: { answered: 1642, median_hours: 4.2 },
    };
    else if (path === '/api/calendar/') {
      const from = url.searchParams.get('date_from')!;
      if (url.searchParams.has('per_day')) {
        data = from.startsWith('2026-08-30') ? [1, 2, 4, 7, 8, 9, 11, 14, 16, 18, 21, 23, 25, 28].flatMap(day => Array.from({ length: 3 }, (_, n) => publication(day, n, day === 7 ? 121 : 8))) : [];
      } else {
        expect(url.searchParams.get('timezone_name')).toBe('Asia/Krasnoyarsk');
        expect(from.endsWith('17:00:00.000Z')).toBeTruthy();
        const day = new Date(new Date(from).getTime() + 7 * 3600000).getUTCDate();
        const offset = Number(url.searchParams.get('offset'));
        const total = day === 7 ? 121 : 0;
        const filter = url.searchParams.get('public_social_link_ids');
        data = Array.from({ length: Math.max(0, Math.min(50, total - offset)) }, (_, i) => publication(day, offset + i, total))
          .map(item => filter ? { ...item, public_social_link_ids: [filter], platforms: [names[1]] } : item);
      }
    } else if (path.startsWith('/api/calendar/post-')) {
      data = { ...publication(7, 0, 121), id: 'post-7-0', public_social_link_ids: ['link-0', 'link-1'], platforms: names.slice(0, 2) };
    }
    await route.fulfill({ json: data });
  });
}

test('calendar loads bounded previews, pages all day entries, and uses local time', async ({ page }) => {
  await fixture(page);
  const errors: string[] = [];
  page.on('pageerror', error => (errors.push(error.message), console.error(error.message)));
  const requests: string[] = [];
  page.on('request', r => requests.push(r.url()));
  await page.goto('/calendar');
  await expect(page.locator('.agenda-count')).toHaveText('121');
  await expect(page.locator('.day-event')).toHaveCount(10);
  await expect(page.locator('.month-grid .day-cell')).toHaveCount(42);
  await expect(page.locator('.calendar-summary strong').first()).toHaveText('225');
  await page.screenshot({ path: 'test-results/calendar-light.png', fullPage: true });
  await page.getByRole('button', { name: /Показать ещё/ }).click();
  await expect(page.locator('.day-event')).toHaveCount(50);
  await page.getByRole('button', { name: /Показать ещё/ }).click();
  await expect(page.locator('.day-event')).toHaveCount(100);
  await page.getByRole('button', { name: /Показать ещё/ }).click();
  await expect(page.locator('.day-event')).toHaveCount(121);
  await expect(page.getByRole('button', { name: /Показать ещё/ })).toHaveCount(0);
  expect(requests.some(url => url.includes('/api/posts'))).toBeFalsy();
  expect(requests.some(url => url.includes('/api/analytics/summary'))).toBeFalsy();
  expect(errors).toEqual([]);
});

test('filters, empty days, direct month navigation and week view', async ({ page }) => {
  await fixture(page);
  await page.goto('/calendar');
  await expect(page.locator('.agenda-count')).toHaveText('121');
  await page.locator('.calendar-source-picker summary').click();
  await page.getByRole('searchbox', { name: 'Поиск сообщества' }).fill('Культура');
  await page.getByRole('checkbox', { name: names[1] }).check();
  await expect(page.locator('.agenda-event-source').first()).toHaveText(names[1]);
  await page.locator('.calendar-source-picker summary').click();
  await page.getByRole('button', { name: 'Неделя', exact: true }).click();
  await expect(page.locator('.week-grid .day-cell')).toHaveCount(7);
  await page.getByRole('button', { name: '8 сентября, публикаций: 8', exact: true }).click();
  await expect(page.getByText('Здесь пока свободно')).toBeVisible();
  await page.getByLabel('Перейти к месяцу').fill('2026-01');
  await expect(page.locator('.calendar-jump input')).toHaveValue('2026-01');
  await page.getByRole('button', { name: 'Месяц', exact: true }).click();
  await page.getByRole('button', { name: 'Следующий период' }).click();
  await expect(page.locator('.calendar-title')).toHaveText('февраль 2026 г.');
});

test('both themes and narrow screens keep the calendar usable', async ({ page }) => {
  await fixture(page, 'dark-red');
  await page.goto('/calendar');
  await expect(page.locator('.agenda-count')).toHaveText('121');
  await page.screenshot({ path: 'test-results/calendar-dark.png', fullPage: true });
  for (const width of [768, 390]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(page.locator('.app-sidebar')).toHaveCSS('width', width === 390 ? '52px' : '66px');
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBeTruthy();
    expect((await page.locator('.calendar-grid-panel').boundingBox())!.width).toBeGreaterThan(280);
    await expect(page.locator('.month-grid .day-cell')).toHaveCount(42);
    await page.screenshot({ path: `test-results/calendar-${width}.png`, fullPage: true });
  }
});

test('overview and content screens render without errors', async ({ page }) => {
  await fixture(page);
  const errors: string[] = [];
  page.on('pageerror', error => (errors.push(error.message), console.error(error.message)));
  await page.goto('/');
  await expect(page.getByRole('heading', { name: 'Всё важное — в поле зрения' })).toBeVisible();
  await expect(page.locator('.home-funnel-value').first()).toHaveText('12 840');
  await expect(page.locator('.home-workspace')).toHaveCSS('opacity', '1');
  await expect(page.locator('.home-hero-title')).toHaveCSS('opacity', '1');
  await page.screenshot({ path: 'test-results/home-light.png', fullPage: true });
  await page.getByRole('button', { name: 'Переключить тему' }).click();
  await expect(page.locator('.page')).toHaveClass(/theme-dark-red/);
  await page.screenshot({ path: 'test-results/home-dark.png', fullPage: true });
  await page.goto('/content');
  await expect(page.getByRole('heading', { name: 'Студия контента' })).toBeVisible();
  await page.screenshot({ path: 'test-results/content.png', fullPage: true });
  expect(errors).toEqual([]);
});

test('calendar failures have a retry action rather than pretending history is empty', async ({ page }) => {
  await fixture(page);
  await page.route('**/api/calendar/**', route => route.fulfill({ status: 503, json: { detail: 'Тестовая ошибка' } }));
  await page.goto('/calendar');
  await expect(page.getByText('Не удалось загрузить календарь.', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Повторить', exact: true }).first()).toBeVisible();
});


test('editing loads every target and deleting addresses the post identity', async ({ page }) => {
  await fixture(page);
  await page.goto('/calendar');
  await page.getByRole('button', { name: 'Изменить пост', exact: true }).first().click();
  await expect(page.getByRole('heading', { name: 'Редактирование публикации' })).toBeVisible();
  await expect(page.locator('.modal input[type=checkbox]:checked')).toHaveCount(2);
  await page.locator('.modal .close').click();
  await page.getByRole('button', { name: /^Удалить пост:/ }).first().click();
  const deleted = page.waitForRequest(request => request.method() === 'DELETE');
  await page.getByRole('button', { name: 'Да, удалить', exact: true }).click();
  expect(new URL((await deleted).url()).pathname).toBe('/api/calendar/post-7-0');
});

test('capture analytics workspace', async ({ page }) => {
  await fixture(page);
  await page.goto('/analytics');
  await page.waitForTimeout(700);
  await page.screenshot({ path: 'test-results/analytics-light.png', fullPage: true });
});
