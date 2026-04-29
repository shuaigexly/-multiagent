import { afterEach, describe, expect, it } from 'vitest';
import {
  LLM_CONFIGURED_STORAGE_KEY,
  isStoredLLMConfigured,
  setStoredLLMConfigured,
} from '../services/config';

describe('config local storage cache', () => {
  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'window');
  });

  it('reads and writes the cached LLM configured flag when storage is available', () => {
    const store = new Map<string, string>();
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        localStorage: {
          getItem: (key: string) => store.get(key) ?? null,
          setItem: (key: string, value: string) => store.set(key, value),
        },
      },
    });

    setStoredLLMConfigured(true);

    expect(store.get(LLM_CONFIGURED_STORAGE_KEY)).toBe('true');
    expect(isStoredLLMConfigured()).toBe(true);
  });

  it('treats blocked localStorage as an empty optional cache', () => {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        localStorage: {
          getItem: () => {
            throw new DOMException('blocked', 'SecurityError');
          },
          setItem: () => {
            throw new DOMException('blocked', 'SecurityError');
          },
        },
      },
    });

    expect(() => setStoredLLMConfigured(true)).not.toThrow();
    expect(isStoredLLMConfigured()).toBe(false);
  });
});
