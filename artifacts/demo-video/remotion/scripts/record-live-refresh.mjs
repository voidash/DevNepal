import {copyFile, mkdir, rm} from 'node:fs/promises';
import path from 'node:path';

import {chromium} from 'playwright-core';

const BASE_URL = process.env.DEVNEPAL_DEMO_URL || 'http://127.0.0.1:9997';
const BRAVE_PATH =
  process.env.BRAVE_PATH ||
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const VIDEO_SIZE = {width: 1440, height: 900};
const outputDirectory = path.resolve('../sources');
const publicVideoDirectory = path.resolve('public/videos');
const rawDirectory = path.resolve('../.live-refresh-recording');
const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

await mkdir(outputDirectory, {recursive: true});
await mkdir(publicVideoDirectory, {recursive: true});
await rm(rawDirectory, {recursive: true, force: true});
await mkdir(rawDirectory, {recursive: true});

const browser = await chromium.launch({executablePath: BRAVE_PATH, headless: true});
const loginContext = await browser.newContext({viewport: VIDEO_SIZE});
const loginPage = await loginContext.newPage();
await loginPage.goto(`${BASE_URL}/en/accounts/login/`, {waitUntil: 'networkidle'});
await loginPage.locator('input[name="username"]').fill('demo-doit-publisher');
await loginPage.locator('input[name="password"]').fill('DevNepal!2026');
await Promise.all([
  loginPage.waitForURL('**/en/authoring/'),
  loginPage.getByRole('button', {name: 'Sign in'}).click(),
]);
const publisherState = await loginContext.storageState();
await loginContext.close();

const context = await browser.newContext({
  viewport: VIDEO_SIZE,
  storageState: publisherState,
  recordVideo: {dir: rawDirectory, size: VIDEO_SIZE},
});
const page = await context.newPage();
const video = page.video();

try {
  await page.goto(
    `${BASE_URL}/en/authoring/sewa-portal-accessibility-remediation/`,
    {waitUntil: 'networkidle'},
  );
  const refresh = page.getByRole('button', {name: 'Refresh GitHub activity'});
  await refresh.scrollIntoViewIfNeeded();
  await pause(5000);
  await Promise.all([
    page.waitForURL('**/en/authoring/sewa-portal-accessibility-remediation/'),
    refresh.click(),
  ]);
  await page.waitForLoadState('networkidle');
  await page.getByText(/GitHub activity refreshed:/).waitFor();
  await pause(9000);
} catch (error) {
  throw new Error('Failed to record the publisher GitHub refresh', {cause: error});
} finally {
  await context.close();
}

if (!video) {
  throw new Error('Brave did not create a video stream for the live refresh');
}
const sourcePath = path.join(outputDirectory, '06-live-github-refresh.webm');
await video.saveAs(sourcePath);
await copyFile(sourcePath, path.join(publicVideoDirectory, '06-live-github-refresh.webm'));
await browser.close();
await rm(rawDirectory, {recursive: true, force: true});
