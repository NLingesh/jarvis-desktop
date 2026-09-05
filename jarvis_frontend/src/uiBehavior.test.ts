import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, expect, it } from 'vitest';

const APP_CSS = readFileSync(join(__dirname, 'App.css'), 'utf8');

function ruleFor(selector: string): string {
  const idx = APP_CSS.indexOf(selector);
  if (idx === -1) return '';
  const open = APP_CSS.indexOf('{', idx);
  const close = APP_CSS.indexOf('}', open);
  return APP_CSS.slice(open + 1, close);
}

describe('conversation UI contracts', () => {
  it('keeps long assistant responses scrollable, never clipped', () => {
    expect(ruleFor('.conversation')).toMatch(/overflow-y:\s*auto/);
    // Message text must wrap and grow; no fixed height clipping.
    const msgRule = ruleFor('.conversation-message-text');
    expect(msgRule).not.toMatch(/overflow:\s*hidden/);
    expect(msgRule).not.toMatch(/(^|[^-])height:\s*\d/);
  });

  it('shows transient status without permanent large panels', () => {
    // Mic notice is a small fixed toast, not a panel.
    const notice = ruleFor('.mic-notice');
    expect(notice).toMatch(/position:\s*fixed/);
    expect(notice).toMatch(/max-width:\s*90vw/);
  });

  it('scopes errors so they never cover the conversation', () => {
    const banner = ruleFor('.error-banner');
    expect(banner).toMatch(/position:\s*fixed/);
    expect(banner).toMatch(/z-index:\s*200/);
  });
});
