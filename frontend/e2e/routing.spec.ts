import { expect, test } from '@playwright/test';
import type { Page } from '@playwright/test';
import type { TripRequest } from '../src/types/routing';
import { SEVERE_LOAD_RULE, buildTripPlan } from './fixtures/tripPlan';

interface PlanApiMock {
  requests: TripRequest[];
}

/** Scripts POST /api/plan/ from the fixture and blocks map tiles, so the test is fully offline. */
async function mockPlanApi(page: Page): Promise<PlanApiMock> {
  const mock: PlanApiMock = { requests: [] };
  await page.route('**/api/plan/', async (route) => {
    const body = route.request().postDataJSON() as TripRequest;
    mock.requests.push(body);
    await route.fulfill({ json: buildTripPlan(body) });
  });
  await page.route('https://tile.openstreetmap.org/**', (route) => route.abort());
  return mock;
}

async function planTrip(page: Page, loadWeightLbs: number): Promise<void> {
  await page.getByLabel('Origin', { exact: true }).fill('Dallas, TX');
  await page.getByLabel('Destination', { exact: true }).fill('Chicago, IL');
  await page.getByLabel('Departure', { exact: true }).fill('2026-11-10T08:00');
  await page.getByLabel('Load weight (lb)', { exact: true }).fill(String(loadWeightLbs));
  await page.getByRole('radio', { name: '25 mi' }).click();
  await page.getByRole('button', { name: 'Analyze routes' }).click();
}

function routeCards(page: Page) {
  return page.getByRole('region', { name: 'Route options' }).getByRole('listitem');
}

test.beforeEach(async ({ page }) => {
  await page.goto('/');
});

test('submits the trip inputs and renders three ranked routes', async ({ page }) => {
  const api = await mockPlanApi(page);
  await planTrip(page, 28_000);

  await expect(routeCards(page)).toHaveCount(3);
  expect(api.requests).toHaveLength(1);
  expect(api.requests[0]).toEqual({
    origin: 'Dallas, TX',
    destination: 'Chicago, IL',
    departure_time: '2026-11-10T14:00:00.000Z',
    load_weight_lbs: 28_000,
    interval_miles: 25,
    demo_storm: false,
  });

  const cards = routeCards(page);
  await expect(cards.nth(0)).toContainText('I-35, I-44');
  await expect(cards.nth(0)).toContainText('Recommended');
  await expect(cards.nth(1)).toContainText('US-75, US-69');
  await expect(cards.nth(2)).toContainText('I-30, I-55');
  await expect(cards.nth(1)).toContainText('Avoided: 480.0 High miles');

  const mapSummary = page.getByRole('table', { name: 'Route summaries on map' });
  await expect(mapSummary.getByRole('row')).toHaveCount(4);
  await expect(mapSummary).toContainText('#1 I-35, I-44');

  const checkpoints = page.getByRole('table', { name: 'Checkpoints' }).getByRole('row');
  await expect(checkpoints).toHaveCount(6);
  await expect(checkpoints.nth(1)).toContainText('Tue 08:00');
});

test('a heavy load escalates wind risk, changes the recommendation and explains why', async ({ page }) => {
  await mockPlanApi(page);

  await planTrip(page, 28_000);
  const notes = page.getByRole('region', { name: 'Dispatcher notes' });
  await expect(notes).toContainText('No Severe or No Travel checkpoints on this route for a 28,000 lb load.');
  await expect(routeCards(page).nth(0)).toContainText('I-35, I-44');

  await planTrip(page, 42_000);
  await expect(routeCards(page).nth(0)).toContainText('US-75, US-69');
  const i35Card = routeCards(page).nth(2);
  await expect(i35Card).toContainText('I-35, I-44');
  await expect(i35Card).toContainText('1 Severe or No Travel checkpoint, 1 raised by load weight');

  await i35Card.getByRole('button').click();
  await expect(notes).toContainText('1 checkpoint at Severe or No Travel.');
  await expect(notes).toContainText('1 is raised by the 42,000 lb load.');
  await expect(notes).toContainText('Load rule');
  await expect(notes).toContainText(SEVERE_LOAD_RULE);
  await expect(notes).toContainText('At or under 40,000 lb this wind is High.');

  const escalatedRow = page.getByRole('table', { name: 'Checkpoints' }).getByRole('row').filter({ hasText: '500.0' });
  await expect(escalatedRow).toContainText('Severe');
  await expect(escalatedRow).toContainText('load');
});

test('the 0-48 h forecast slider updates the heatmap readout without calling the API', async ({ page }) => {
  const api = await mockPlanApi(page);
  await planTrip(page, 28_000);
  await expect(routeCards(page)).toHaveCount(3);

  const slider = page.getByRole('slider', { name: 'Forecast hour offset from departure' });
  const offset = page.getByTestId('forecast-offset');
  const peakWind = page.getByTestId('peak-wind');
  const elevated = page.getByTestId('elevated-points');

  await expect(slider).toHaveAttribute('min', '0');
  await expect(slider).toHaveAttribute('max', '48');
  await expect(offset).toHaveText('+0h 00m');
  await expect(peakWind).toHaveText('20 mph');
  await expect(elevated).toHaveText('0 / 6');

  await slider.fill('24');
  await expect(offset).toHaveText('+24h 00m');
  await expect(peakWind).toHaveText('44 mph');
  await expect(elevated).toHaveText('5 / 6');

  await slider.fill('48');
  await expect(offset).toHaveText('+48h 00m');
  await expect(peakWind).toHaveText('68 mph');

  await slider.fill('0');
  await page.getByRole('button', { name: 'Play' }).click();
  await expect(offset).not.toHaveText('+0h 00m');
  await page.getByRole('button', { name: 'Pause' }).click();

  expect(api.requests).toHaveLength(1);
});

test('backend errors are shown to the dispatcher as reported', async ({ page }) => {
  await page.route('**/api/plan/', (route) =>
    route.fulfill({ status: 422, json: { detail: "No location found for 'Nowhereville'", code: 'geocoding_failed' } }),
  );
  await page.getByLabel('Origin', { exact: true }).fill('Nowhereville');
  await page.getByRole('button', { name: 'Analyze routes' }).click();

  await expect(page.getByRole('alert')).toHaveText("No location found for 'Nowhereville'");
  await expect(routeCards(page)).toHaveCount(0);
});
