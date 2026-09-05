import { render, fireEvent } from '@testing-library/react';
import { readFileSync } from 'node:fs';
import { join } from 'node:path';
import { describe, it, expect, vi } from 'vitest';
import MinimalBubble from './MinimalBubble';
import type { OrbState } from '../orb/OrbEngine';

const BUBBLE_CSS = readFileSync(join(__dirname, 'MinimalBubble.css'), 'utf8');

describe('MinimalBubble', () => {
  it('renders a 72x72 circular launcher with centered JARVIS text', () => {
    const { container } = render(<MinimalBubble state="idle" />);
    const bubble = container.querySelector('.minimal-bubble');
    expect(bubble).toBeInTheDocument();
    expect(bubble).toHaveClass('minimal-bubble-idle');
    const svg = container.querySelector('.minimal-bubble-svg');
    expect(svg).toBeInTheDocument();
    expect(svg).toHaveAttribute('viewBox', '0 0 72 72');
    const circle = container.querySelector('.minimal-bubble-circle');
    expect(circle).toBeInTheDocument();
    expect(circle).toHaveAttribute('cx', '36');
    expect(circle).toHaveAttribute('cy', '36');
    expect(circle).toHaveAttribute('r', '35');
    expect(container.querySelector('.minimal-bubble-text')).toHaveTextContent('JARVIS');
  });

  it('does not render a Three.js canvas', () => {
    const { container } = render(<MinimalBubble state="idle" />);
    expect(container.querySelector('canvas')).not.toBeInTheDocument();
  });

  it('renders the state class for every bubble state', () => {
    const states: OrbState[] = [
      'idle',
      'listening',
      'thinking',
      'speaking',
      'processing',
      'working',
      'notification',
      'panel-open',
      'error',
      'offline',
    ];
    const { container, rerender } = render(<MinimalBubble state={states[0]} />);
    for (const state of states) {
      rerender(<MinimalBubble state={state} />);
      expect(container.querySelector('.minimal-bubble')).toHaveClass(`minimal-bubble-${state}`);
    }
  });

  it('transitions between visual states without remounting the button', () => {
    const onToggle = vi.fn();
    const { container, rerender } = render(<MinimalBubble state="idle" onToggle={onToggle} />);
    const button = container.querySelector('.minimal-bubble-button');
    rerender(<MinimalBubble state="listening" onToggle={onToggle} />);
    expect(container.querySelector('.minimal-bubble-button')).toBe(button);
    rerender(<MinimalBubble state="working" onToggle={onToggle} />);
    expect(container.querySelector('.minimal-bubble')).toHaveClass('minimal-bubble-working');
  });

  it('renders a live audio-level halo ring', () => {
    const { container } = render(<MinimalBubble state="listening" audioLevel={0.5} />);
    expect(container.querySelector('.minimal-bubble-halo')).toBeInTheDocument();
    expect(container.querySelector('.minimal-bubble-halo')).toHaveAttribute('r', '30');
  });

  it('passes a normalized audio level as a CSS variable', () => {
    const { container, rerender } = render(<MinimalBubble state="speaking" audioLevel={1.8} />);
    expect(container.querySelector('.minimal-bubble')).toHaveStyle({
      '--bubble-audio-level': '1',
    });
    rerender(<MinimalBubble state="speaking" audioLevel={-0.5} />);
    expect(container.querySelector('.minimal-bubble')).toHaveStyle({
      '--bubble-audio-level': '0',
    });
  });

  it('calls onToggle exactly once on click', () => {
    const onToggle = vi.fn();
    const { container } = render(<MinimalBubble state="idle" onToggle={onToggle} />);
    const button = container.querySelector('.minimal-bubble-button') as HTMLButtonElement;
    fireEvent.click(button);
    expect(onToggle).toHaveBeenCalledTimes(1);
  });

  it('falls back to window.electronAPI.toggleMainWindow when onToggle is absent', () => {
    const toggle = vi.fn();
    window.electronAPI = { toggleMainWindow: toggle as unknown as ElectronApi['toggleMainWindow'] };
    const { container } = render(<MinimalBubble state="idle" />);
    fireEvent.click(container.querySelector('.minimal-bubble-button') as HTMLButtonElement);
    expect(toggle).toHaveBeenCalledTimes(1);
    delete window.electronAPI;
  });

  it('disables every animation under prefers-reduced-motion', () => {
    expect(BUBBLE_CSS).toMatch(/@media \(prefers-reduced-motion: reduce\)/);
    const block = BUBBLE_CSS.split('@media (prefers-reduced-motion: reduce)')[1] || '';
    expect(block).toMatch(/animation:\s*none\s*!important/);
  });

  it('uses only cheap compositor-friendly animations for state motion', () => {
    // No animated filter/width/height: only opacity, transform, and
    // stroke-dashoffset keyframes are allowed.
    const keyframeBlocks = BUBBLE_CSS.match(/@keyframes[^{]+\{[\s\S]*?\n\}/g) || [];
    expect(keyframeBlocks.length).toBeGreaterThan(0);
    for (const block of keyframeBlocks) {
      const body = block.replace(/@keyframes[^{]+\{/, '');
      expect(body).not.toMatch(/\bfilter\s*:/);
      expect(body).not.toMatch(/\b(width|height|top|left)\s*:/);
    }
  });
});
