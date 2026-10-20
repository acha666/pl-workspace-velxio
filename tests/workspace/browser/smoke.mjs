import assert from 'node:assert/strict';
import { readFile } from 'node:fs/promises';
import http from 'node:http';
import { once } from 'node:events';
import { chromium, expect } from '@playwright/test';

const template = process.argv[2];
assert.ok(['blink', 'sevenSegment'].includes(template), 'Specify blink or sevenSegment');
// A working sketch for the template, typed into the editor and run.
const source = await readFile(new URL(`fixtures/${template}.ino`, import.meta.url), 'utf8');
const base = '/pl/workspace/test/container/';
const origin = 'http://127.0.0.1:8081';
const api = `${origin}${base}api/pl-workspace`;

// PrairieLearn strips WORKSPACE_BASE_URL before forwarding to the container.
const proxy = http.createServer((incoming, outgoing) => {
  if (!incoming.url.startsWith(base)) {
    outgoing.writeHead(404).end();
    return;
  }
  const upstream = http.request(
    {
      hostname: '127.0.0.1',
      port: 8080,
      path: `/${incoming.url.slice(base.length)}`,
      method: incoming.method,
      headers: { ...incoming.headers, host: '127.0.0.1:8080' },
    },
    (response) => {
      outgoing.writeHead(response.statusCode, response.headers);
      response.pipe(outgoing);
    },
  );
  upstream.on('error', (error) => outgoing.writeHead(502).end(error.message));
  incoming.pipe(upstream);
});
proxy.listen(8081, '127.0.0.1');
await once(proxy, 'listening');

const browser = await chromium.launch({ headless: true });
const context = await browser.newContext({
  viewport: { width: 1440, height: 1000 },
  locale: 'en-US',
});
const failures = [];
let expectingConflict = false;
context.on('page', (page) => {
  page.on('pageerror', (error) => failures.push(error.message));
  page.on('console', (message) => {
    if (message.type() === 'error' && !(expectingConflict && /409/.test(message.text()))) {
      failures.push(`console: ${message.text()}`);
    }
  });
});
context.on('request', (request) => {
  if (/^https?:/.test(request.url()) && new URL(request.url()).origin !== origin) {
    failures.push(`External request: ${request.url()}`);
  }
});
context.on('requestfailed', (request) => {
  if (request.failure()?.errorText !== 'net::ERR_ABORTED') {
    failures.push(`Request failed: ${request.url()} (${request.failure()?.errorText})`);
  }
});
context.on('response', (response) => {
  if (response.status() >= 400 && !(expectingConflict && response.status() === 409)) {
    failures.push(`HTTP ${response.status()}: ${response.url()}`);
  }
});

// The file explorer's save icon is the workspace's only save control and status.
const saveIcon = (page) => page.locator('.file-explorer-save-btn[class*="is-"]');

async function openEditor(page) {
  await page.goto(`${origin}${base}`);
  await expect(page.getByTestId('pl-save-status')).toHaveText('Saved to workspace', {
    timeout: 30_000,
  });
  await expect(saveIcon(page)).toHaveClass(/\bis-saved\b/);
  await expect(page.locator('.pl-save-text')).toHaveText(/^Saved( .+)?$/);
  await expect(page.locator('.monaco-editor .view-lines').first()).toBeVisible({ timeout: 30_000 });
}

async function edit(page, code, expectedStatus = 200) {
  const saved = page.waitForResponse(
    (response) => response.url() === api && response.request().method() === 'PUT',
  );
  // Record every state the save icon passes through during the autosave.
  await saveIcon(page).evaluate((icon) => {
    window.saveIconClasses = [icon.className];
    new MutationObserver(() => window.saveIconClasses.push(icon.className)).observe(icon, {
      attributes: true,
      attributeFilter: ['class'],
    });
  });
  // Exercise Monaco's real change event without browser IME/auto-indent effects.
  await page.evaluate((value) => {
    const model = window.monaco.editor.getModels().find((model) => model.getLanguageId() === 'cpp');
    if (!model) throw new Error('The sketch editor did not load');
    model.setValue(value);
  }, code);
  assert.equal((await saved).status(), expectedStatus);
  await expect(page.getByTestId('pl-save-status')).toHaveText(
    expectedStatus === 200 ? 'Saved to workspace' : 'Save failed',
  );
  if (expectedStatus === 200) {
    // A prompt autosave must not make the icon flash while the student types.
    const classes = await page.evaluate(() => window.saveIconClasses);
    assert.ok(
      classes.every((className) => /\bis-saved\b/.test(className)),
      `The save icon changed during autosave: ${classes.join(', ')}`,
    );
    await expect(page.locator('.pl-save-text')).toHaveText(/^Saved .+$/);
  } else {
    await expect(saveIcon(page)).toHaveClass(/\bis-error\b/);
    await expect(page.locator('.pl-save-text')).toHaveText('Not saved');
  }
}

async function savedCode() {
  const response = await context.request.get(api);
  assert.equal(response.status(), 200);
  const { project } = await response.json();
  return Object.values(project.fileGroups).flat()[0].content;
}

try {
  const page = await context.newPage();
  await openEditor(page);
  await expect(page.locator('.pl-workspace-status')).toHaveCount(0);

  // The AGPL source offer lives in the Help menu.
  await page.getByRole('button', { name: 'Help', exact: true }).click();
  const sourceLink = page.getByRole('menuitem', { name: 'Source & licenses' });
  const sourceArchive = await context.request.get(await sourceLink.getAttribute('href'));
  assert.equal(sourceArchive.status(), 200);
  assert.deepEqual([...(await sourceArchive.body()).subarray(0, 2)], [0x1f, 0x8b]);
  await page.keyboard.press('Escape');

  await edit(page, source);
  assert.equal(await savedCode(), source);
  await page.reload();
  await expect(page.getByTestId('pl-save-status')).toHaveText('Saved to workspace');
  await expect
    .poll(() =>
      page.evaluate(() =>
        window.monaco?.editor
          .getModels()
          .find((model) => model.getLanguageId() === 'cpp')
          ?.getValue(),
      ),
    )
    .toBe(source);
  assert.equal(await savedCode(), source);

  // Run uses the native compiler, circuit checks and AVR simulation.
  const compilation = page.waitForResponse(
    (response) => response.url().endsWith('/api/compile/start'),
    { timeout: 60_000 },
  );
  await page.locator('.tb-btn-run').click();
  assert.equal((await compilation).status(), 200);
  await expect(page.locator('[title="Running"]').first()).toBeVisible({ timeout: 120_000 });
  if (template === 'blink') {
    const led = page.locator('wokwi-arduino-uno').first();
    for (const on of [true, false, true]) {
      await expect
        .poll(() => led.evaluate((element) => element.led13), { timeout: 10_000, intervals: [50] })
        .toBe(on);
    }
  } else {
    const display = page.locator('wokwi-7segment#display');
    for (const pattern of [0x3f, 0x06, 0x5b]) {
      await expect
        .poll(
          () =>
            display.evaluate((element) =>
              element.values
                .slice(0, 7)
                .reduce((value, segment, index) => value | (segment > 0 ? 1 << index : 0), 0),
            ),
          { timeout: 15_000, intervals: [50] },
        )
        .toBe(pattern);
    }
  }

  const stale = await context.newPage();
  await openEditor(stale);
  const winningCode = `${source}\n// Saved from the first tab.\n`;
  await edit(page, winningCode);
  expectingConflict = true;
  const localCode = `${source}\n// Recover this unsaved edit.\n`;
  await edit(stale, localCode, 409);
  assert.equal(await savedCode(), winningCode);
  const download = stale.waitForEvent('download');
  await stale.getByRole('button', { name: 'Export local project' }).click();
  const recovered = JSON.parse(await readFile(await (await download).path(), 'utf8'));
  assert.equal(Object.values(recovered.fileGroups).flat()[0].content, localCode);
  assert.deepEqual(failures, [], 'Browser errors or asset requests escaped the workspace');
  console.log(
    `${template}: prefixed assets, save/reload, compile/simulation, conflict/recovery passed`,
  );
} catch (error) {
  console.error('Browser diagnostics:', failures);
  for (const page of context.pages()) {
    console.error((await page.locator('body').innerText()).slice(-6000));
  }
  throw error;
} finally {
  await browser.close();
  proxy.closeAllConnections();
  await new Promise((resolve) => proxy.close(resolve));
}
