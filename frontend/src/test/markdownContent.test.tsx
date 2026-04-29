// @vitest-environment jsdom

import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { MarkdownContent } from '../components/MarkdownContent';

describe('MarkdownContent', () => {
  it('sanitizes links and avoids remote image loads', () => {
    render(
      <MarkdownContent
        content={[
          '[safe](https://example.com/report?x=1)',
          '[bad](javascript:alert(1))',
          '![tracker](https://tracker.example/pixel.png)',
          '<img src="https://tracker.example/html.png" />',
        ].join('\n\n')}
      />,
    );

    const safeLink = screen.getByRole('link', { name: 'safe' });
    expect(safeLink.getAttribute('href')).toBe('https://example.com/report?x=1');
    expect(safeLink.getAttribute('target')).toBe('_blank');
    expect(safeLink.getAttribute('rel')).toContain('noopener');

    expect(screen.queryByRole('link', { name: 'bad' })).toBeNull();
    expect(screen.getByText('bad')).toBeTruthy();
    expect(screen.getByText('[tracker]')).toBeTruthy();
    expect(document.querySelector('img')).toBeNull();
  });
});
