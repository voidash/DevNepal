import {createHmac} from 'node:crypto';

const requireEnvironment = (name) => {
  const value = process.env[name]?.trim();
  if (!value) {
    throw new Error(`${name} is required for the ministry portion of the demo`);
  }
  return value;
};

const totp = (hexSecret) => {
  if (!/^[0-9a-f]+$/i.test(hexSecret) || hexSecret.length % 2 !== 0) {
    throw new Error('DEMO_PUBLISHER_TOTP_SECRET must be the Django OTP device hex key');
  }
  const counter = Math.floor(Date.now() / 1000 / 30);
  const counterBuffer = Buffer.alloc(8);
  counterBuffer.writeBigUInt64BE(BigInt(counter));
  const digest = createHmac('sha1', Buffer.from(hexSecret, 'hex')).update(counterBuffer).digest();
  const offset = digest[digest.length - 1] & 0x0f;
  const binary =
    ((digest[offset] & 0x7f) << 24) |
    ((digest[offset + 1] & 0xff) << 16) |
    ((digest[offset + 2] & 0xff) << 8) |
    (digest[offset + 3] & 0xff);
  return String(binary % 1_000_000).padStart(6, '0');
};

export const authenticatePublisher = async (browser, baseUrl, viewport) => {
  const username = requireEnvironment('DEMO_PUBLISHER_USERNAME');
  const password = requireEnvironment('DEMO_PUBLISHER_PASSWORD');
  const context = await browser.newContext({viewport});
  const page = await context.newPage();

  try {
    const response = await page.goto(`${baseUrl}/en/accounts/login/`, {
      waitUntil: 'domcontentloaded',
    });
    if (!response?.ok()) {
      throw new Error(`Publisher login returned ${response?.status() ?? 'no response'}`);
    }
    await page.locator('input[name="username"]').fill(username);
    await page.locator('input[name="password"]').fill(password);
    await page.getByRole('button', {name: 'Sign in'}).click();
    await page.waitForLoadState('domcontentloaded');

    if (new URL(page.url()).pathname.endsWith('/settings/mfa/')) {
      const secret = requireEnvironment('DEMO_PUBLISHER_TOTP_SECRET');
      const tokenField = page.locator('input[name="token"]');
      if (!(await tokenField.isVisible())) {
        throw new Error(
          'The publisher has no enrolled MFA device; provision one before recording the demo',
        );
      }
      await tokenField.fill(totp(secret));
      await page.getByRole('button', {name: 'Verify code'}).click();
      await page.waitForLoadState('domcontentloaded');
    }

    await page.waitForURL('**/en/authoring/');
    await page.getByRole('link', {name: 'Create project'}).waitFor();
    return await context.storageState();
  } finally {
    await context.close();
  }
};
