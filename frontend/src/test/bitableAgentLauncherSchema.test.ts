import { describe, expect, it } from 'vitest';
import {
  LAUNCHER_DIMENSIONS,
  LAUNCHER_INITIAL_WORKFLOW_CONTRACT,
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
    expect(LAUNCHER_INITIAL_WORKFLOW_CONTRACT).toEqual({
      responsibilityRole: '系统调度',
      responsibilityOwner: '系统',
      nativeAction: '等待分析完成',
      exceptionStatus: '正常',
      exceptionType: '无',
      exceptionNote: '',
      automationStatus: '未触发',
    });
  });

  it('writes a complete editable workflow contract without readonly automatic fields', () => {
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
      { id: 'fld_role', name: '当前责任角色', property: { options: [{ id: 'opt_role', name: '系统调度' }] } },
      { id: 'fld_owner', name: '当前责任人' },
      { id: 'fld_native_action', name: '当前原生动作', property: { options: [{ id: 'opt_native_action', name: '等待分析完成' }] } },
      { id: 'fld_exception_status', name: '异常状态', property: { options: [{ id: 'opt_exception_status', name: '正常' }] } },
      { id: 'fld_exception_type', name: '异常类型', property: { options: [{ id: 'opt_exception_type', name: '无' }] } },
      { id: 'fld_exception_note', name: '异常说明' },
      { id: 'fld_automation', name: '自动化执行状态', property: { options: [{ id: 'opt_automation', name: '未触发' }] } },
      { id: 'fld_pending_report', name: '待发送汇报' },
      { id: 'fld_pending_task', name: '待创建执行任务' },
      { id: 'fld_pending_review', name: '待安排复核' },
      { id: 'fld_is_approved', name: '是否已拍板' },
      { id: 'fld_pending_approval', name: '待拍板确认' },
      { id: 'fld_is_executed', name: '是否已执行落地' },
      { id: 'fld_pending_execution', name: '待执行确认' },
      { id: 'fld_in_retro', name: '是否进入复盘' },
      { id: 'fld_pending_retro', name: '待复盘确认' },
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
      fld_role: { id: 'opt_role', text: '系统调度' },
      fld_owner: [{ type: 'text', text: '系统' }],
      fld_native_action: { id: 'opt_native_action', text: '等待分析完成' },
      fld_exception_status: { id: 'opt_exception_status', text: '正常' },
      fld_exception_type: { id: 'opt_exception_type', text: '无' },
      fld_exception_note: [{ type: 'text', text: '' }],
      fld_automation: { id: 'opt_automation', text: '未触发' },
      fld_pending_report: false,
      fld_pending_task: false,
      fld_pending_review: false,
      fld_is_approved: false,
      fld_pending_approval: false,
      fld_is_executed: false,
      fld_pending_execution: false,
      fld_in_retro: false,
      fld_pending_retro: false,
    });
    expect(payload).not.toHaveProperty('fld_created_at');
  });

  it('fails fast when the existing Bitable field option is incompatible', () => {
    expect(() =>
      buildLauncherRecordFields(
        [
          { id: 'fld_title', name: '任务标题' },
          { id: 'fld_dimension', name: '分析维度', property: { options: [] } },
        ],
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

  it('fails fast when required launcher fields are missing or blank', () => {
    expect(() =>
      buildLauncherRecordFields([], {
        title: '增长诊断',
        description: '',
        dimension: '综合分析',
        priority: 'P1 高',
        outputPurpose: '经营诊断',
      }),
    ).toThrow('缺少必需字段「任务标题」');

    expect(() =>
      buildLauncherRecordFields([{ id: 'fld_title', name: '任务标题' }], {
        title: '   ',
        description: '',
        dimension: '综合分析',
        priority: 'P1 高',
        outputPurpose: '经营诊断',
      }),
    ).toThrow('任务标题不能为空');
  });
});
