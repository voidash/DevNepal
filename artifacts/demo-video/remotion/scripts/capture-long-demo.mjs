import {mkdir} from 'node:fs/promises';
import path from 'node:path';

import {chromium} from 'playwright-core';

import {authenticatePublisher} from './publisher-auth.mjs';

const requireEnvironment = (name) => {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required; captures must identify the deployed demo explicitly`);
  }
  return value;
};

const BASE_URL = requireEnvironment('DEVNEPAL_DEMO_URL').replace(/\/$/, '');
const ISSUE_NUMBER = process.env.DEMO_ISSUE_NUMBER?.trim() || '7';
const PROJECT_SLUG = 'sewa-portal-accessibility-remediation';
const REPOSITORY = 'voidash/civic-help-directory';
const BRAVE_PATH =
  process.env.BRAVE_PATH ||
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const outputDirectory = path.resolve('public/long');
const desktop = {width: 1440, height: 900};

const gotoChecked = async (page, url, readyLocator, label) => {
  const response = await page.goto(url, {waitUntil: 'domcontentloaded'});
  if (!response || !response.ok()) {
    throw new Error(`${label} returned ${response?.status() ?? 'no response'} at ${url}`);
  }
  await readyLocator.waitFor({state: 'visible'});
};

const assertNoHorizontalOverflow = async (page, label) => {
  const dimensions = await page.evaluate(() => ({
    clientWidth: document.documentElement.clientWidth,
    scrollWidth: document.documentElement.scrollWidth,
  }));
  if (dimensions.scrollWidth > dimensions.clientWidth + 1) {
    throw new Error(
      `${label} overflows horizontally: ${dimensions.scrollWidth}px > ${dimensions.clientWidth}px`,
    );
  }
};

const save = async (page, filename) => {
  await page.screenshot({path: path.join(outputDirectory, filename)});
};

const resetScroll = async (page) => {
  await page.evaluate(() => window.scrollTo({top: 0, left: 0, behavior: 'instant'}));
};

await mkdir(outputDirectory, {recursive: true});
const browser = await chromium.launch({executablePath: BRAVE_PATH, headless: true});

try {
  const publicContext = await browser.newContext({viewport: desktop});
  const publicPage = await publicContext.newPage();

  await gotoChecked(
    publicPage,
    `${BASE_URL}/ne/`,
    publicPage.locator('#hero-heading'),
    'Nepali home',
  );
  await publicPage.getByRole('link', {name: /सरकारी परियोजना/}).first().waitFor();
  if (await publicPage.getByText(/GitHub मा सामेल/).count()) {
    throw new Error('The stripped public home unexpectedly promotes member GitHub OAuth');
  }
  await save(publicPage, '01-home-ne.png');

  await gotoChecked(
    publicPage,
    `${BASE_URL}/ne/projects/gov/`,
    publicPage.locator('main h1'),
    'Government project catalogue',
  );
  await publicPage.getByRole('link', {name: /Civic Help Directory/i}).first().waitFor();
  await resetScroll(publicPage);
  await save(publicPage, '02-project-list-ne.png');

  const projectUrl = `${BASE_URL}/ne/projects/${PROJECT_SLUG}/`;
  await gotoChecked(
    publicPage,
    projectUrl,
    publicPage.locator('#github-issues-heading'),
    'Public project detail',
  );
  const selectedIssue = publicPage.locator(`a[href$="/issues/${ISSUE_NUMBER}/"]`).first();
  await selectedIssue.waitFor({state: 'visible'});
  await publicPage.getByRole('link', {name: /#10/}).first().waitFor();
  await resetScroll(publicPage);
  await save(publicPage, '03-project-top-ne.png');
  await publicPage.locator('#github-issues-heading').scrollIntoViewIfNeeded();
  await save(publicPage, '03-project-issues-ne.png');
  await publicPage.locator('#contributors-heading').scrollIntoViewIfNeeded();
  await save(publicPage, '03-project-contributors-ne.png');

  const issueUrl = `${BASE_URL}/ne/projects/${PROJECT_SLUG}/issues/${ISSUE_NUMBER}/`;
  await gotoChecked(
    publicPage,
    issueUrl,
    publicPage.getByRole('link', {name: /GitHub मा योगदान सुरु/}),
    `DevNepal issue #${ISSUE_NUMBER}`,
  );
  await publicPage.getByText(new RegExp(`#${ISSUE_NUMBER}(?:\\D|$)`)).first().waitFor();
  await resetScroll(publicPage);
  await save(publicPage, '04-issue-devnepal-ne.png');

  await gotoChecked(
    publicPage,
    `${BASE_URL}/ne/github/people/voidash/`,
    publicPage.locator('#profile-heading'),
    'Public GitHub profile',
  );
  await publicPage.locator('#tracked-work-heading').waitFor();
  await resetScroll(publicPage);
  await save(publicPage, '05-profile-ne.png');
  await publicContext.close();

  const githubContext = await browser.newContext({viewport: desktop});
  const githubPage = await githubContext.newPage();
  const githubIssueUrl = `https://github.com/${REPOSITORY}/issues/${ISSUE_NUMBER}`;
  await gotoChecked(githubPage, githubIssueUrl, githubPage.locator('main'), 'Canonical GitHub issue');
  await githubPage.waitForFunction(
    (issueNumber) => document.title.includes(`#${issueNumber}`),
    ISSUE_NUMBER,
  );
  await resetScroll(githubPage);
  await save(githubPage, '04-issue-github.png');

  await gotoChecked(
    githubPage,
    `https://github.com/${REPOSITORY}/issues`,
    githubPage.locator(`a[href="/${REPOSITORY}/issues/${ISSUE_NUMBER}"]`).first(),
    'GitHub issue list',
  );
  await resetScroll(githubPage);
  await save(githubPage, '08-github-issues.png');

  await gotoChecked(
    githubPage,
    `https://github.com/${REPOSITORY}/pulls`,
    githubPage.locator(`a[href="/${REPOSITORY}/pull/10"]`).first(),
    'GitHub pull request list',
  );
  await resetScroll(githubPage);
  await save(githubPage, '08-github-prs.png');
  await githubContext.close();

  const publisherState = await authenticatePublisher(browser, BASE_URL, desktop);

  const publisherContext = await browser.newContext({viewport: desktop, storageState: publisherState});
  const publisherPage = await publisherContext.newPage();
  await gotoChecked(
    publisherPage,
    `${BASE_URL}/en/authoring/`,
    publisherPage.getByRole('link', {name: 'Create project'}),
    'Publisher dashboard',
  );
  await resetScroll(publisherPage);
  await save(publisherPage, '06-authoring-dashboard.png');

  await gotoChecked(
    publisherPage,
    `${BASE_URL}/en/authoring/create/`,
    publisherPage.locator('#fill-demo-details'),
    'Project creation form',
  );
  await publisherPage.locator('#fill-demo-details').click();
  await publisherPage.locator('#demo-fill-status').waitFor({state: 'visible'});
  const repositoryField = publisherPage.locator('input[name="repository_url"]');
  if ((await repositoryField.inputValue()) !== `https://github.com/${REPOSITORY}`) {
    throw new Error('Demo fill did not select the verified civic-help-directory repository');
  }
  await resetScroll(publisherPage);
  await save(publisherPage, '06-create-filled-top.png');
  await repositoryField.scrollIntoViewIfNeeded();
  await save(publisherPage, '06-create-filled-repository.png');

  await gotoChecked(
    publisherPage,
    `${BASE_URL}/en/authoring/${PROJECT_SLUG}/`,
    publisherPage.getByRole('button', {name: 'Refresh GitHub activity'}),
    'Publisher project workspace',
  );
  await publisherPage.locator(`a[href$="/issues/${ISSUE_NUMBER}/"]`).first().waitFor();
  await resetScroll(publisherPage);
  await save(publisherPage, '07-workspace-refreshed.png');
  await publisherPage.locator('[id^="repo-contributors-"]').first().scrollIntoViewIfNeeded();
  await save(publisherPage, '07-workspace-contributors.png');
  await publisherContext.close();

  const mobileContext = await browser.newContext({
    viewport: {width: 390, height: 844},
    deviceScaleFactor: 1,
    isMobile: true,
  });
  const mobilePage = await mobileContext.newPage();
  await gotoChecked(
    mobilePage,
    `${BASE_URL}/ne/`,
    mobilePage.locator('#hero-heading'),
    'Mobile Nepali home',
  );
  await assertNoHorizontalOverflow(mobilePage, 'Mobile Nepali home');
  await resetScroll(mobilePage);
  await save(mobilePage, '09-mobile-home.png');

  await gotoChecked(
    mobilePage,
    projectUrl,
    mobilePage.locator('#github-issues-heading'),
    'Mobile Nepali project',
  );
  await assertNoHorizontalOverflow(mobilePage, 'Mobile Nepali project');
  await resetScroll(mobilePage);
  await save(mobilePage, '09-mobile-project.png');
  await mobilePage.locator('#github-issues-heading').scrollIntoViewIfNeeded();
  await mobilePage.mouse.wheel(0, 120);
  await mobilePage.waitForTimeout(250);
  await mobilePage.locator(`a[href$="/issues/${ISSUE_NUMBER}/"]`).first().waitFor();
  await assertNoHorizontalOverflow(mobilePage, 'Mobile Nepali issue list');
  await save(mobilePage, '09-mobile-issues.png');
  await mobileContext.close();
} finally {
  await browser.close();
}
