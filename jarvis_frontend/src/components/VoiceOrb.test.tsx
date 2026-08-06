import { render } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import VoiceOrb from './VoiceOrb';

describe('VoiceOrb', () => {
  it('renders without crashing in idle state', () => {
    const { container } = render(<VoiceOrb state="idle" analysers={[]} />);
    expect(container.querySelector('.orb-base')).toBeInTheDocument();
    expect(container.querySelector('.orb-fallback')).toBeInTheDocument();
  });

  it('renders without crashing in speaking state', () => {
    const { container } = render(<VoiceOrb state="speaking" analysers={[]} />);
    expect(container.querySelector('.orb-base')).toBeInTheDocument();
  });

  it('renders without crashing in listening state', () => {
    const { container } = render(<VoiceOrb state="listening" analysers={[]} />);
    expect(container.querySelector('.orb-base')).toBeInTheDocument();
  });

  it('renders without crashing in thinking state', () => {
    const { container } = render(<VoiceOrb state="thinking" analysers={[]} />);
    expect(container.querySelector('.orb-base')).toBeInTheDocument();
  });
});
