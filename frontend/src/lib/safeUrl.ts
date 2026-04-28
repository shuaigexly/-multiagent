export function getSafeExternalUrl(value: string | null | undefined): string {
  const raw = (value || '').trim();
  if (!raw) return '';

  try {
    const parsed = new URL(raw);
    return parsed.protocol === 'http:' || parsed.protocol === 'https:' ? parsed.href : '';
  } catch {
    return '';
  }
}
