import { describe, expect, it, afterEach } from 'vitest';
import type { InternalAxiosRequestConfig } from 'axios';
import { API_KEY_STORAGE_KEY, attachRuntimeApiKeyHeader, getRuntimeApiKey, setRuntimeApiKey } from '../services/http';

function installWindowWithApiKey(apiKey: string) {
  Object.defineProperty(globalThis, 'window', {
    configurable: true,
    value: {
      localStorage: {
        getItem: (key: string) => (key === API_KEY_STORAGE_KEY ? apiKey : null),
      },
    },
  });
}

describe('http service', () => {
  afterEach(() => {
    Reflect.deleteProperty(globalThis, 'window');
  });

  it('attaches runtime API key when headers is a plain object', () => {
    installWindowWithApiKey('runtime-secret');

    const config = attachRuntimeApiKeyHeader({
      headers: {},
    } as InternalAxiosRequestConfig);

    expect(config.headers.get('X-API-Key')).toBe('runtime-secret');
  });

  it('treats blocked localStorage as no runtime API key', () => {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        localStorage: {
          getItem: () => {
            throw new DOMException('blocked', 'SecurityError');
          },
        },
      },
    });

    expect(getRuntimeApiKey()).toBe('');
  });

  it('reports blocked localStorage writes without throwing', () => {
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        localStorage: {
          setItem: () => {
            throw new DOMException('blocked', 'SecurityError');
          },
          removeItem: () => {
            throw new DOMException('blocked', 'SecurityError');
          },
        },
      },
    });

    expect(setRuntimeApiKey('runtime-secret')).toBe(false);
    expect(setRuntimeApiKey('')).toBe(false);
  });

  it('rejects oversized runtime API keys', () => {
    const oversized = 'x'.repeat(4097);
    Object.defineProperty(globalThis, 'window', {
      configurable: true,
      value: {
        localStorage: {
          getItem: () => oversized,
          setItem: () => {
            throw new Error('setItem should not be called');
          },
          removeItem: () => {
            throw new Error('removeItem should not be called');
          },
        },
      },
    });

    expect(getRuntimeApiKey()).toBe('');
    expect(setRuntimeApiKey(oversized)).toBe(false);
  });
});
