const MAX_EXTERNAL_URL_LENGTH = 2048;

function hasControlCharacter(value: string): boolean {
  return [...value].some((char) => {
    const code = char.charCodeAt(0);
    return code <= 31 || code === 127;
  });
}

export function getSafeExternalUrl(value: string | null | undefined): string {
  const raw = (value || '').trim();
  if (!raw) return '';
  if (raw.length > MAX_EXTERNAL_URL_LENGTH) return '';
  if (hasControlCharacter(raw)) return '';

  try {
    const parsed = new URL(raw);
    if (parsed.protocol !== 'http:' && parsed.protocol !== 'https:') return '';
    if (parsed.username || parsed.password) return '';
    return parsed.href;
  } catch {
    return '';
  }
}
