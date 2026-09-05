import {copyFile, mkdir, rm} from 'node:fs/promises';
import path from 'node:path';

import {chromium} from 'playwright-core';

import {authenticatePublisher} from './publisher-auth.mjs';

const requireEnvironment = (name) => {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required; live refresh recordings cannot use implicit credentials`);
  }
  return value;
};

const BASE_URL = requireEnvironment('DEVNEPAL_DEMO_URL').replace(/\/$/, '');
const EXPECTED_ISSUE_NUMBER = process.env.EXPECTED_SYNCED_ISSUE_NUMBER?.trim() || '11';
const PROJECT_SLUG = 'sewa-portal-accessibility-remediation';
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

try {
  const publisherState = await authenticatePublisher(browser, BASE_URL, VIDEO_SIZE);

  const context = await browser.newContext({
    viewport: VIDEO_SIZE,
    storageState: publisherState,
    recordVideo: {dir: rawDirectory, size: VIDEO_SIZE},
  });
  const page = await context.newPage();
  const video = page.video();

  try {
    const workspaceUrl = `${BASE_URL}/en/authoring/${PROJECT_SLUG}/`;
    const workspaceResponse = await page.goto(workspaceUrl, {waitUntil: 'domcontentloaded'});
    if (!workspaceResponse?.ok()) {
      throw new Error(`Publisher workspace returned ${workspaceResponse?.status() ?? 'no response'}`);
    }
    const refresh = page.getByRole('button', {name: 'Refresh GitHub activity'});
    await refresh.scrollIntoViewIfNeeded();
    const synchronizedBefore = await page.getByText(/^Last synchronized /).first().textContent();
    await pause(3500);

    const refreshResponsePromise = page.waitForResponse(
      (response) =>
        response.request().method() === 'POST' &&
        response.url().includes(`/github/projects/${PROJECT_SLUG}/repositories/`),
    );
    await refresh.click();
    const refreshResponse = await refreshResponsePromise;
    if (refreshResponse.status() === 429) {
      throw new Error('Live GitHub refresh is cooling down; retry after its Retry-After interval');
    }
    if (refreshResponse.status() < 200 || refreshResponse.status() >= 400) {
      throw new Error(`Live GitHub refresh returned ${refreshResponse.status()}`);
    }
    await page.waitForURL(`**/en/authoring/${PROJECT_SLUG}/`);
    await page.getByText(/GitHub activity refreshed:/).waitFor({state: 'visible'});
    await page.locator(`a[href$="/issues/${EXPECTED_ISSUE_NUMBER}/"]`).first().waitFor();
    const synchronizedAfter = await page.getByText(/^Last synchronized /).first().textContent();
    if (!synchronizedAfter || synchronizedAfter === synchronizedBefore) {
      throw new Error('Refresh completed without a visibly updated synchronization timestamp');
    }
    await pause(6500);
  } catch (error) {
    throw new Error('Failed to record and verify the deployed publisher GitHub refresh', {
      cause: error,
    });
  } finally {
    await context.close();
  }

  if (!video) {
    throw new Error('Brave did not create a video stream for the live refresh');
  }
  const sourcePath = path.join(outputDirectory, '06-live-github-refresh.webm');
  await video.saveAs(sourcePath);
  await copyFile(sourcePath, path.join(publicVideoDirectory, '06-live-github-refresh.webm'));
} finally {
  await browser.close();
  await rm(rawDirectory, {recursive: true, force: true});
}
