import { describe, expect, it } from 'vitest';
import {
  LAUNCHER_DIMENSIONS,
  LAUNCHER_OUTPUT_PURPOSES,
  LAUNCHER_TASK_SOURCE,
  buildLauncherRecordFields,
} from '../pages/bitableAgentLauncherSchema';

describe('bitable agent launcher schema', () => {
  it('uses editable values that match the backend Bitable schema', () => {
    expect([...LAUNCHER_DIMENSIONS]).toEqual([
      '综合分析',
      '内容战略',
      '数据复盘',
      '增长优化',
      '产品规划',
      '运营诊断',
    ]);
    expect([...LAUNCHER_OUTPUT_PURPOSES]).toEqual([
      '经营诊断',
      '管理决策',
      '执行跟进',
      '汇报展示',
      '补数核验',
    ]);
    expect(LAUNCHER_TASK_SOURCE).toBe('手工创建');
  });

  it('does not write readonly automatic fields', () => {
    const fields = [
      { id: 'fld_title', name: '任务标题' },
      { id: 'fld_dimension', name: '分析维度', property: { options: [{ id: 'opt_dimension', name: '综合分析' }] } },
      { id: 'fld_priority', name: '优先级', property: { options: [{ id: 'opt_priority', name: 'P1 高' }] } },
      { id: 'fld_purpose', name: '输出目的', property: { options: [{ id: 'opt_purpose', name: '经营诊断' }] } },
      { id: 'fld_background', name: '背景说明' },
      { id: 'fld_status', name: '状态', property: { options: [{ id: 'opt_status', name: '待分析' }] } },
      { id: 'fld_stage', name: '当前阶段' },
      { id: 'fld_progress', name: '进度' },
      { id: 'fld_source', name: '任务来源', property: { options: [{ id: 'opt_source', name: '手工创建' }] } },
      { id: 'fld_created_at', name: '创建时间' },
    ];

    const payload = buildLauncherRecordFields(fields, {
      title: ' 增长诊断 ',
      description: '',
      dimension: '综合分析',
      priority: 'P1 高',
      outputPurpose: '经营诊断',
    });

    expect(payload).toEqual({
      fld_title: [{ type: 'text', text: '增长诊断' }],
      fld_dimension: { id: 'opt_dimension', text: '综合分析' },
      fld_priority: { id: 'opt_priority', text: 'P1 高' },
      fld_purpose: { id: 'opt_purpose', text: '经营诊断' },
      fld_background: [{ type: 'text', text: '用户在 plugin 内提交：增长诊断' }],
      fld_status: { id: 'opt_status', text: '待分析' },
      fld_stage: [{ type: 'text', text: '用户从插件提交' }],
      fld_progress: 0,
      fld_source: { id: 'opt_source', text: '手工创建' },
    });
    expect(payload).not.toHaveProperty('fld_created_at');
  });

  it('fails fast when the existing Bitable field option is incompatible', () => {
    expect(() =>
      buildLauncherRecordFields(
        [{ id: 'fld_dimension', name: '分析维度', property: { options: [] } }],
        {
          title: '增长诊断',
          description: '',
          dimension: '综合分析',
          priority: 'P1 高',
          outputPurpose: '经营诊断',
        },
      ),
    ).toThrow('缺少选项');
  });
});
