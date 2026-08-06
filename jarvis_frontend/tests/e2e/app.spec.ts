import { test, expect } from '@playwright/test';

test.describe('JARVIS Frontend', () => {
  test('loads the main app', async ({ page }) => {
    await page.goto('/');
    await expect(page.locator('.orb-container')).toBeVisible();
    await expect(page.locator('.orb-base')).toBeVisible();
  });

  test('settings button is accessible', async ({ page }) => {
    await page.goto('/');
    const settingsButton = page.locator('.settings-btn');
    await expect(settingsButton).toBeVisible();
    await expect(settingsButton).toHaveAttribute('aria-label', 'Open settings');
  });

  test('text input has proper accessibility attributes', async ({ page }) => {
    await page.goto('/');
    const textInput = page.locator('input[type="text"]');
    await expect(textInput).toBeVisible();
    await expect(textInput).toHaveAttribute('aria-label', 'Type a message');
  });

  test('error banner has role alert', async ({ page }) => {
    await page.goto('/');
    const errorBanner = page.locator('.error-banner');
    // Error banner only appears when there is an error; just verify it has correct role when present
    // by checking the stylesheet or structure
    await expect(errorBanner).toHaveAttribute('role', 'alert');
  });
});
