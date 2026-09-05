import {mkdir} from 'node:fs/promises';
import path from 'node:path';

import {chromium} from 'playwright-core';

const BASE_URL = process.env.DEVNEPAL_DEMO_URL || 'http://127.0.0.1:9997';
const BRAVE_PATH =
  process.env.BRAVE_PATH ||
  '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const outputDirectory = path.resolve('public/long');
const desktop = {width: 1440, height: 900};

await mkdir(outputDirectory, {recursive: true});
const browser = await chromium.launch({executablePath: BRAVE_PATH, headless: true});

const save = async (page, filename) => {
  await page.screenshot({path: path.join(outputDirectory, filename)});
};

const publicContext = await browser.newContext({viewport: desktop});
const publicPage = await publicContext.newPage();
await publicPage.goto(`${BASE_URL}/ne/`, {waitUntil: 'networkidle'});
await save(publicPage, '01-home-ne.png');
await publicPage.goto(`${BASE_URL}/ne/projects/gov/`, {waitUntil: 'networkidle'});
await save(publicPage, '02-project-list-ne.png');
await publicPage.goto(
  `${BASE_URL}/ne/projects/sewa-portal-accessibility-remediation/`,
  {waitUntil: 'networkidle'},
);
await save(publicPage, '03-project-top-ne.png');
await publicPage.getByRole('heading', {name: /GitHub का खुला/}).scrollIntoViewIfNeeded();
await save(publicPage, '03-project-issues-ne.png');
await publicPage.getByRole('heading', {name: /यस रिपोजिटरीमा/}).scrollIntoViewIfNeeded();
await save(publicPage, '03-project-contributors-ne.png');
await publicPage.goto(
  `${BASE_URL}/ne/projects/sewa-portal-accessibility-remediation/issues/11/`,
  {waitUntil: 'networkidle'},
);
await save(publicPage, '04-issue-devnepal-ne.png');
await publicPage.goto(`${BASE_URL}/ne/github/people/voidash/`, {waitUntil: 'networkidle'});
await save(publicPage, '05-profile-ne.png');
await publicContext.close();

const githubContext = await browser.newContext({viewport: desktop});
const githubPage = await githubContext.newPage();
await githubPage.goto('https://github.com/voidash/civic-help-directory/issues/11', {
  waitUntil: 'domcontentloaded',
});
await githubPage.waitForTimeout(3000);
await save(githubPage, '04-issue-github.png');
await githubPage.goto('https://github.com/voidash/civic-help-directory/issues', {
  waitUntil: 'domcontentloaded',
});
await githubPage.waitForTimeout(2500);
await save(githubPage, '08-github-issues.png');
await githubPage.goto('https://github.com/voidash/civic-help-directory/pulls', {
  waitUntil: 'domcontentloaded',
});
await githubPage.waitForTimeout(2500);
await save(githubPage, '08-github-prs.png');
await githubContext.close();

const loginContext = await browser.newContext({viewport: desktop});
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

const publisherContext = await browser.newContext({viewport: desktop, storageState: publisherState});
const publisherPage = await publisherContext.newPage();
await publisherPage.goto(`${BASE_URL}/en/authoring/`, {waitUntil: 'networkidle'});
await save(publisherPage, '06-authoring-dashboard.png');
await publisherPage.goto(`${BASE_URL}/en/authoring/create/`, {waitUntil: 'networkidle'});
await publisherPage.getByRole('button', {name: 'Fill demo details'}).click();
await save(publisherPage, '06-create-filled-top.png');
await publisherPage.locator('input[name="repository_url"]').scrollIntoViewIfNeeded();
await save(publisherPage, '06-create-filled-repository.png');
await publisherPage.goto(
  `${BASE_URL}/en/authoring/sewa-portal-accessibility-remediation/`,
  {waitUntil: 'networkidle'},
);
await save(publisherPage, '07-workspace-refreshed.png');
await publisherPage.getByRole('heading', {name: 'Repository contributors'}).scrollIntoViewIfNeeded();
await save(publisherPage, '07-workspace-contributors.png');
await publisherContext.close();

const mobileContext = await browser.newContext({
  viewport: {width: 390, height: 844},
  deviceScaleFactor: 1,
  isMobile: true,
});
const mobilePage = await mobileContext.newPage();
await mobilePage.goto(`${BASE_URL}/ne/`, {waitUntil: 'networkidle'});
await save(mobilePage, '09-mobile-home.png');
await mobilePage.goto(
  `${BASE_URL}/ne/projects/sewa-portal-accessibility-remediation/`,
  {waitUntil: 'networkidle'},
);
await save(mobilePage, '09-mobile-project.png');
await mobilePage.getByRole('heading', {name: /GitHub का खुला/}).scrollIntoViewIfNeeded();
await save(mobilePage, '09-mobile-issues.png');
await mobileContext.close();

await browser.close();
