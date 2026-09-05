import {mkdir, rm} from 'node:fs/promises';
import path from 'node:path';

import {chromium} from 'playwright-core';

const BASE_URL = process.env.DEVNEPAL_DEMO_URL || 'http://127.0.0.1:9997';
const BRAVE_PATH =
  process.env.BRAVE_PATH ||
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const GITHUB_ISSUE_URL =
  'https://github.com/voidash/civic-help-directory/issues/11';
const VIDEO_SIZE = {width: 1440, height: 900};
const outputDirectory = path.resolve('../sources');
const rawDirectory = path.resolve('../.recordings');

const pause = (milliseconds) => new Promise((resolve) => setTimeout(resolve, milliseconds));

const moveTo = async (page, locator) => {
  await locator.scrollIntoViewIfNeeded();
  await pause(900);
};

const smoothScroll = async (page, pixels) => {
  await page.mouse.wheel(0, pixels);
  await pause(1400);
};

await mkdir(outputDirectory, {recursive: true});
await rm(rawDirectory, {recursive: true, force: true});
await mkdir(rawDirectory, {recursive: true});

const browser = await chromium.launch({
  executablePath: BRAVE_PATH,
  headless: true,
});

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

const record = async ({filename, storageState, action}) => {
  const context = await browser.newContext({
    viewport: VIDEO_SIZE,
    storageState,
    recordVideo: {dir: rawDirectory, size: VIDEO_SIZE},
  });
  const page = await context.newPage();
  const video = page.video();

  try {
    await action(page);
  } catch (error) {
    throw new Error(`Failed to record ${filename}`, {cause: error});
  } finally {
    await context.close();
  }

  if (!video) {
    throw new Error(`Brave did not create a video stream for ${filename}`);
  }
  await video.saveAs(path.join(outputDirectory, filename));
};

await record({
  filename: '01-visitor.webm',
  action: async (page) => {
    await page.goto(`${BASE_URL}/en/`, {waitUntil: 'networkidle'});
    await pause(1800);
    await page.getByRole('link', {name: 'Browse government projects'}).click();
    await page.waitForLoadState('networkidle');
    await pause(1600);
    const project = page.getByRole('link', {name: 'Civic Help Directory'});
    await moveTo(page, project);
    await project.click();
    await page.waitForLoadState('networkidle');
    await pause(2400);
    await smoothScroll(page, 470);
    await pause(1200);
  },
});

await record({
  filename: '02-ministry-create.webm',
  storageState: publisherState,
  action: async (page) => {
    await page.goto(`${BASE_URL}/en/authoring/`, {waitUntil: 'networkidle'});
    await pause(1800);
    await page.getByRole('link', {name: 'Create project'}).click();
    await page.waitForLoadState('networkidle');
    await pause(1600);
    await page.getByRole('button', {name: 'Fill demo details'}).click();
    await pause(2200);
    await moveTo(page, page.locator('input[name="repository_url"]'));
    await pause(1800);
    await smoothScroll(page, 430);
  },
});

await record({
  filename: '03-github-proof.webm',
  action: async (page) => {
    await page.goto('https://github.com/voidash/civic-help-directory/issues', {
      waitUntil: 'domcontentloaded',
    });
    await page.waitForLoadState('networkidle').catch(() => undefined);
    await pause(2500);
    const issue = page.getByRole('link', {
      name: 'Demo: confirm DevNepal GitHub synchronization',
      exact: true,
    });
    await moveTo(page, issue);
    await issue.click();
    await page.waitForURL(GITHUB_ISSUE_URL);
    await page.waitForLoadState('domcontentloaded');
    await pause(2800);
    await smoothScroll(page, 250);
    await pause(1600);
  },
});

await record({
  filename: '04-visitor-issue-profile.webm',
  action: async (page) => {
    await page.goto(
      `${BASE_URL}/en/projects/sewa-portal-accessibility-remediation/`,
      {waitUntil: 'networkidle'},
    );
    await pause(1700);
    const issue = page.getByRole('link', {
      name: '#11 · Demo: confirm DevNepal GitHub synchronization',
    });
    await moveTo(page, issue);
    await pause(1200);
    await issue.click();
    await page.waitForLoadState('networkidle');
    await pause(2300);
    await moveTo(page, page.getByRole('link', {name: 'Start contributing on GitHub'}));
    await pause(1800);
    await page.goBack({waitUntil: 'networkidle'});
    const contributor = page.getByRole('link', {name: /@voidash/});
    await moveTo(page, contributor);
    await contributor.click();
    await page.waitForLoadState('networkidle');
    await pause(2500);
  },
});

await record({
  filename: '05-ministry-activity.webm',
  storageState: publisherState,
  action: async (page) => {
    await page.goto(
      `${BASE_URL}/en/authoring/sewa-portal-accessibility-remediation/`,
      {waitUntil: 'networkidle'},
    );
    await pause(2100);
    const issue = page.getByRole('link', {
      name: '#11 · Demo: confirm DevNepal GitHub synchronization',
    });
    await moveTo(page, issue);
    await pause(1800);
    await moveTo(page, page.getByRole('link', {name: /#10/}));
    await pause(1800);
    await moveTo(page, page.getByRole('link', {name: /@voidash/}));
    await pause(2200);
  },
});

await browser.close();
await rm(rawDirectory, {recursive: true, force: true});

