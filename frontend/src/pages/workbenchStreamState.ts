export type WorkbenchStep = 'input' | 'planning' | 'confirm' | 'running' | 'done';
export type StreamRecoverStep = 'input' | 'confirm';

export function isTerminalTaskStatus(status: unknown): status is 'done' | 'failed' | 'cancelled' {
  return status === 'done' || status === 'failed' || status === 'cancelled';
}

export function resolveStreamEndState(
  status: unknown,
  recover: StreamRecoverStep,
): { step: WorkbenchStep; error: string | null } {
  if (status === 'done') {
    return { step: 'done', error: null };
  }
  if (status === 'failed') {
    return {
      step: recover,
      error: recover === 'confirm' ? '任务执行失败，请重新确认' : '任务执行失败',
    };
  }
  if (status === 'cancelled') {
    return { step: 'input', error: '任务已取消' };
  }
  if (status === 'timeout') {
    return {
      step: recover,
      error: '实时连接超时，请刷新页面查看最新状态',
    };
  }
  return {
    step: recover,
    error: '实时连接已结束，请刷新页面查看最新状态',
  };
}
