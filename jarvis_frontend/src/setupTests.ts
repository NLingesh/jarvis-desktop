import '@testing-library/jest-dom';

// jsdom cannot create real WebGL contexts (the `canvas` npm package is not
// installed), so three.js logs a pair of *expected* console errors whenever a
// VoiceOrb mounts during tests. Silence exactly those two messages so test
// output stays readable without hiding real application errors.
const originalError = console.error;
beforeAll(() => {
  console.error = (...args: unknown[]) => {
    const first = typeof args[0] === 'string' ? args[0] : '';
    if (
      first.includes('HTMLCanvasElement.prototype.getContext') ||
      first.includes('Error creating WebGL context')
    ) {
      return;
    }
    originalError(...args);
  };
});

afterAll(() => {
  console.error = originalError;
});
