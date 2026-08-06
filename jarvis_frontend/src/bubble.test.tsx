import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import BubbleApp from './bubble';

describe('BubbleApp', () => {
  it('renders orb container', () => {
    const { container } = render(<BubbleApp />);
    expect(container.querySelector('.bubble-container')).toBeInTheDocument();
  });

  it('has correct aria-label on bubble container', () => {
    const { container } = render(<BubbleApp />);
    const bubble = container.querySelector('.bubble-container');
    expect(bubble).toHaveAttribute('aria-label', 'JARVIS voice assistant bubble');
    expect(bubble).toHaveAttribute('role', 'button');
  });

  it('has tabIndex for keyboard accessibility', () => {
    const { container } = render(<BubbleApp />);
    const bubble = container.querySelector('.bubble-container');
    expect(bubble).toHaveAttribute('tabindex', '0');
  });
});
