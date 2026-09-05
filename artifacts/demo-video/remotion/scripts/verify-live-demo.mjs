import {mkdir, writeFile} from 'node:fs/promises';
import path from 'node:path';

import {chromium} from 'playwright-core';

import {authenticatePublisher} from './publisher-auth.mjs';

const requireEnvironment = (name) => {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required for live demo verification`);
  }
  return value;
};

const baseUrl = requireEnvironment('DEVNEPAL_DEMO_URL').replace(/\/$/, '');
const bravePath =
  process.env.BRAVE_PATH || '/Applications/Brave Browser.app/Contents/MacOS/Brave Browser';
const projectSlug = 'sewa-portal-accessibility-remediation';
const expectedIssueTitle = process.env.EXPECTED_SYNCED_ISSUE_TITLE?.trim() || '';
const outputDirectory = path.resolve(
  process.env.DEVNEPAL_VALIDATION_OUTPUT || '/tmp/devnepal-live-playwright',
);
const desktop = {width: 1440, height: 900};
const mobile = {width: 390, height: 844};

await mkdir(outputDirectory, {recursive: true});
const browser = await chromium.launch({executablePath: bravePath, headless: true});

try {
  const publisherState = await authenticatePublisher(browser, baseUrl, desktop);
  const context = await browser.newContext({viewport: desktop, storageState: publisherState});
  await context.tracing.start({screenshots: true, snapshots: true, sources: true});
  const page = await context.newPage();

  const createResponse = await page.goto(`${baseUrl}/en/authoring/create/`, {
    waitUntil: 'domcontentloaded',
  });
  if (!createResponse?.ok()) {
    throw new Error(`Create-project screen returned ${createResponse?.status() ?? 'no response'}`);
  }
  await page.getByRole('button', {name: 'Fill demo details'}).click();
  await page.getByText('Demo details added. Review every field before saving.').waitFor();
  const repositoryValue = await page.locator('input[name="repository_url"]').inputValue();
  const demoIntent = await page.locator('input[name="demo_fill"]').inputValue();
  if (
    repositoryValue !== 'https://github.com/voidash/civic-help-directory' ||
    demoIntent !== 'civic-help-directory'
  ) {
    throw new Error('Demo fill did not select the canonical Civic Help Directory repository');
  }
  await page.screenshot({path: path.join(outputDirectory, '01-filled-project.png'), fullPage: true});

  await Promise.all([
    page.waitForURL(`**/en/authoring/${projectSlug}/`),
    page.getByRole('button', {name: 'Save draft and continue'}).click(),
  ]);
  await page.getByRole('heading', {name: 'voidash/civic-help-directory'}).waitFor();
  await page.getByRole('button', {name: 'Refresh GitHub activity'}).waitFor();
  if (await page.getByRole('link', {name: 'Connect repository'}).count()) {
    throw new Error('Canonical project still asks the publisher to connect the repository');
  }
  const workspaceText = await page.locator('main').innerText();
  for (const required of ['Open issues', 'Open pull requests', 'Repository contributors']) {
    if (!workspaceText.includes(required)) {
      throw new Error(`Publisher workspace is missing ${required}`);
    }
  }
  await page.screenshot({path: path.join(outputDirectory, '02-connected-workspace.png'), fullPage: true});

  const publicResponse = await page.goto(`${baseUrl}/en/projects/${projectSlug}/`, {
    waitUntil: 'domcontentloaded',
  });
  if (!publicResponse?.ok()) {
    throw new Error(`Public project screen returned ${publicResponse?.status() ?? 'no response'}`);
  }
  await page.getByRole('heading', {name: 'Open issues from GitHub'}).waitFor();
  await page.getByRole('heading', {name: 'People working on this repository'}).waitFor();
  await page.getByRole('heading', {name: 'Open pull requests'}).waitFor();
  const issueLinks = page.locator(`a[href^="/en/projects/${projectSlug}/issues/"]`);
  const issueCount = await issueLinks.count();
  if (issueCount < 1) {
    throw new Error('Public project has no synchronized GitHub issue links');
  }
  if (expectedIssueTitle) {
    await page.getByRole('link', {name: new RegExp(expectedIssueTitle)}).first().waitFor();
  }
  const contributorLinks = page.locator('a[href^="/en/github/people/"]');
  const contributorCount = await contributorLinks.count();
  if (contributorCount < 1) {
    throw new Error('Public project has no synchronized GitHub contributor profiles');
  }
  const profileUrl = await contributorLinks.first().getAttribute('href');
  const pullRequestCount = await page.locator('a[href*="github.com/voidash/civic-help-directory/pull/"]').count();
  if (pullRequestCount < 1) {
    throw new Error('Public project has no synchronized GitHub pull request links');
  }
  await page.screenshot({path: path.join(outputDirectory, '03-public-project.png'), fullPage: true});

  await issueLinks.first().click();
  await page.waitForLoadState('domcontentloaded');
  await page.getByRole('link', {name: 'Start contributing on GitHub'}).waitFor();
  if (!page.url().includes(`/en/projects/${projectSlug}/issues/`)) {
    throw new Error(`Issue hand-off opened an unexpected URL: ${page.url()}`);
  }
  await page.screenshot({path: path.join(outputDirectory, '04-issue-handoff.png'), fullPage: true});

  await context.tracing.stop({path: path.join(outputDirectory, 'desktop-flow-trace.zip')});
  await context.close();

  const mobileContext = await browser.newContext({viewport: mobile});
  const mobilePage = await mobileContext.newPage();
  const mobileResponse = await mobilePage.goto(`${baseUrl}/en/projects/${projectSlug}/`, {
    waitUntil: 'domcontentloaded',
  });
  if (!mobileResponse?.ok()) {
    throw new Error(`Mobile project screen returned ${mobileResponse?.status() ?? 'no response'}`);
  }
  const overflow = await mobilePage.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  if (overflow > 1) {
    throw new Error(`Mobile project screen overflows horizontally by ${overflow}px`);
  }
  await mobilePage.getByRole('heading', {name: 'Open issues from GitHub'}).waitFor();
  await mobilePage.screenshot({
    path: path.join(outputDirectory, '05-mobile-public-project.png'),
    fullPage: true,
  });
  await mobileContext.close();

  const report = {
    baseUrl,
    projectSlug,
    canonicalRepository: repositoryValue,
    issueLinks: issueCount,
    expectedIssueTitle: expectedIssueTitle || null,
    pullRequestLinks: pullRequestCount,
    contributorProfiles: contributorCount,
    firstContributorProfile: profileUrl,
    mobileHorizontalOverflowPixels: overflow,
    passed: true,
  };
  await writeFile(
    path.join(outputDirectory, 'report.json'),
    `${JSON.stringify(report, null, 2)}\n`,
    'utf8',
  );
  console.log(JSON.stringify(report));
} finally {
  await browser.close();
}
