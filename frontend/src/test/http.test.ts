import { describe, expect, it, afterEach } from 'vitest';
import type { InternalAxiosRequestConfig } from 'axios';
import { API_KEY_STORAGE_KEY, attachRuntimeApiKeyHeader, getRuntimeApiKey } from '../services/http';

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
});
