export const AGENT_PERSONAS: Record<
  string,
  { name: string; title: string; avatar: string; color: string; personality: string[]; tagline: string }
> = {
  data_analyst: {
    name: '陈晓明', title: '数据分析师', avatar: '陈', color: '#3370FF',
    personality: ['严谨', '数字控', '逻辑清晰'],
    tagline: '用数字说话，把模糊问题变成精确结论',
  },
  finance_advisor: {
    name: '李婷婷', title: 'CFO · 财务顾问', avatar: '李', color: '#34C759',
    personality: ['稳健', '风控意识强', '利润优先'],
    tagline: '守护现金流，每一分钱都要花在刀刃上',
  },
  seo_advisor: {
    name: '王浩然', title: '增长黑客', avatar: '王', color: '#FF9500',
    personality: ['激进', '流量思维', '实验驱动'],
    tagline: '找到你的用户在哪，把他们带到你面前',
  },
  content_manager: {
    name: '林诗雨', title: '内容总监', avatar: '林', color: '#AF52DE',
    personality: ['创意', '品牌感强', '细节控'],
    tagline: '让每一篇内容都成为品牌的名片',
  },
  product_manager: {
    name: '张志远', title: '产品经理', avatar: '张', color: '#FF2D55',
    personality: ['用户导向', '需求挖掘', '路线清晰'],
    tagline: '把用户痛点变成产品机会，让功能讲故事',
  },
  operations_manager: {
    name: '赵小雅', title: '运营总监', avatar: '赵', color: '#5AC8FA',
    personality: ['执行力强', '多线并行', '结果导向'],
    tagline: '从计划到落地，确保每个环节都不掉链子',
  },
  ceo_assistant: {
    name: '吴思远', title: 'CEO 助理', avatar: '吴', color: '#636366',
    personality: ['全局视野', '决策支持', '综合汇总'],
    tagline: '帮你看清全局，把所有结论整合成行动计划',
  },
};
