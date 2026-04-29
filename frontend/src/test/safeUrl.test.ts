import { describe, expect, it } from 'vitest';
import { getSafeExternalUrl } from '../lib/safeUrl';

describe('getSafeExternalUrl', () => {
  it('allows http and https URLs', () => {
    expect(getSafeExternalUrl('https://example.com/path?q=1')).toBe('https://example.com/path?q=1');
    expect(getSafeExternalUrl('http://example.com/path')).toBe('http://example.com/path');
  });

  it('rejects unsafe or malformed URLs', () => {
    expect(getSafeExternalUrl('javascript:alert(1)')).toBe('');
    expect(getSafeExternalUrl('data:text/html,<script>alert(1)</script>')).toBe('');
    expect(getSafeExternalUrl('file:///etc/passwd')).toBe('');
    expect(getSafeExternalUrl('/relative/path')).toBe('');
    expect(getSafeExternalUrl('')).toBe('');
  });

  it('rejects confusing external URLs with credentials, control chars, or excessive length', () => {
    expect(getSafeExternalUrl('https://user:pass@example.com/path')).toBe('');
    expect(getSafeExternalUrl('https://example.com/path\nnext')).toBe('');
    expect(getSafeExternalUrl(`https://example.com/${'x'.repeat(2100)}`)).toBe('');
  });
});
