import { describe, expect, it } from 'vitest';

import { summarizeVoiceToolResults } from './App';

describe('summarizeVoiceToolResults', () => {
  it('renders a verified tool with its single argument', () => {
    const lines = summarizeVoiceToolResults([
      { tool: 'launch_application', args: { app: 'vs code' }, verified: true },
    ]);
    expect(lines).toEqual(['✓ launch_application: vs code']);
  });

  it('joins multiple non-empty arguments', () => {
    const lines = summarizeVoiceToolResults([
      { tool: 'open_folder', args: { path: 'downloads' }, verified: true },
    ]);
    expect(lines).toEqual(['✓ open_folder: downloads']);
  });

  it('omits unverified and unknown tools', () => {
    const lines = summarizeVoiceToolResults([
      { tool: 'open_folder', args: { path: 'x' }, verified: false },
      { tool: 'open_folder', args: { path: 'y' }, verified: true },
      { not: 'a tool' },
    ]);
    expect(lines).toEqual(['✓ open_folder: y']);
  });

  it('returns an empty list for non-array input', () => {
    expect(summarizeVoiceToolResults(null)).toEqual([]);
    expect(summarizeVoiceToolResults({ tool: 'x' })).toEqual([]);
    expect(summarizeVoiceToolResults(undefined)).toEqual([]);
  });

  it('drops a tool with no usable args', () => {
    const lines = summarizeVoiceToolResults([{ tool: 'open_terminal', args: {}, verified: true }]);
    expect(lines).toEqual(['✓ open_terminal']);
  });
});
