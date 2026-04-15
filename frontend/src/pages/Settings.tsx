import { useEffect, useState } from 'react';
import { Loader2, CheckCircle2, XCircle } from 'lucide-react';
import { getConfig, saveConfigs, testFeishu, testLLM, type ConfigMap, type ConnectionTestResult } from '../services/config';
import { Button } from '@/components/ui/button';
import { Input } from '@/components/ui/input';
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select';

type SaveSection = 'llm' | 'feishu' | null;

function getErr(e: unknown, fb: string) {
  if (typeof e === 'object' && e !== null && 'response' in e) {
    const r = (e as { response?: { data?: unknown } }).response;
    if (typeof r?.data === 'string' && r.data) return r.data;
    if (typeof r?.data === 'object' && r.data !== null && 'detail' in r.data) {
      const d = (r.data as { detail?: string }).detail;
      if (d) return d;
    }
  }
  return e instanceof Error && e.message ? e.message : fb;
}

export default function Settings() {
  const [config, setConfig] = useState<ConfigMap | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState<SaveSection>(null);
  const [testingLLM, setTestingLLM] = useState(false);
  const [testingFeishu, setTestingFeishu] = useState(false);
  const [llmProvider, setLlmProvider] = useState('openai_compatible');
  const [llmApiKey, setLlmApiKey] = useState('');
  const [llmBaseUrl, setLlmBaseUrl] = useState('https://api.openai.com/v1');
  const [llmModel, setLlmModel] = useState('gpt-4o-mini');
  const [feishuRegion, setFeishuRegion] = useState('cn');
  const [feishuAppId, setFeishuAppId] = useState('');
  const [feishuAppSecret, setFeishuAppSecret] = useState('');
  const [llmTest, setLlmTest] = useState<ConnectionTestResult | null>(null);
  const [feishuTest, setFeishuTest] = useState<ConnectionTestResult | null>(null);

  const load = async () => {
    const d = await getConfig(); setConfig(d);
    setLlmProvider(d.llm_provider?.value || 'openai_compatible');
    setLlmBaseUrl(d.llm_base_url?.value || 'https://api.openai.com/v1');
    setLlmModel(d.llm_model?.value || 'gpt-4o-mini');
    setFeishuRegion(d.feishu_region?.value || 'cn');
    setFeishuAppId(d.feishu_app_id?.value || '');
  };

  useEffect(() => { load().catch(e => setError(getErr(e, '加载失败'))).finally(() => setLoading(false)); }, []);

  const saveLLM = async () => {
    setSaving('llm'); setError(null); setLlmTest(null);
    try {
      const c = [{ key: 'llm_provider', value: llmProvider.trim() }, { key: 'llm_base_url', value: llmBaseUrl.trim() }, { key: 'llm_model', value: llmModel.trim() }];
      if (llmApiKey.trim()) c.unshift({ key: 'llm_api_key', value: llmApiKey.trim() });
      await saveConfigs(c); setLlmApiKey(''); await load();
      setLlmTest({ ok: true, message: '已保存' });
    } catch (e) { setError(getErr(e, '保存失败')); } finally { setSaving(null); }
  };

  const saveFeishu = async () => {
    setSaving('feishu'); setError(null); setFeishuTest(null);
    try {
      const c: { key: string; value: string | null }[] = [{ key: 'feishu_region', value: feishuRegion.trim() }, { key: 'feishu_app_id', value: feishuAppId.trim() || null }];
      if (feishuAppSecret.trim()) c.push({ key: 'feishu_app_secret', value: feishuAppSecret.trim() });
      await saveConfigs(c); setFeishuAppSecret(''); await load();
      setFeishuTest({ ok: true, message: '已保存' });
    } catch (e) { setError(getErr(e, '保存失败')); } finally { setSaving(null); }
  };

  const doTestLLM = async () => {
    setTestingLLM(true); setLlmTest(null);
    try { setLlmTest(await testLLM(llmApiKey.trim(), llmBaseUrl.trim(), llmModel.trim())); }
    catch (e) { setLlmTest({ ok: false, message: getErr(e, '测试失败') }); }
    finally { setTestingLLM(false); }
  };

  const doTestFeishu = async () => {
    setTestingFeishu(true); setFeishuTest(null);
    try { setFeishuTest(await testFeishu(feishuAppId.trim(), feishuAppSecret.trim(), feishuRegion)); }
    catch (e) { setFeishuTest({ ok: false, message: getErr(e, '测试失败') }); }
    finally { setTestingFeishu(false); }
  };

  if (loading) return (
    <div className="flex items-center justify-center min-h-[60vh] gap-2 text-sm text-muted-foreground">
      <Loader2 className="h-4 w-4 animate-spin" />加载中...
    </div>
  );

  const llmOk = Boolean(config?.llm_api_key?.set);
  const feishuOk = Boolean(config?.feishu_app_id?.set && config?.feishu_app_secret?.set);

  return (
    <div className="max-w-4xl mx-auto px-5 py-6 space-y-5">
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div>
          <h1 className="text-xl font-semibold text-foreground">设置</h1>
          <p className="mt-1 text-sm text-muted-foreground">管理 LLM 与飞书凭证</p>
        </div>
        <div className="flex gap-2">
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${llmOk ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'}`}>
            {llmOk ? 'LLM ✓' : 'LLM 未配置'}
          </span>
          <span className={`rounded px-2 py-0.5 text-xs font-medium ${feishuOk ? 'bg-success/10 text-success' : 'bg-warning/10 text-warning'}`}>
            {feishuOk ? '飞书 ✓' : '飞书未配置'}
          </span>
        </div>
      </div>

      {error && <div className="rounded-md bg-destructive/10 px-3 py-2 text-sm text-destructive">{error}</div>}

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* LLM */}
        <div className="space-y-4 rounded-xl border border-border bg-card p-5 shadow-sm">
          <div className="text-sm font-semibold text-foreground">LLM 配置</div>
          <div>
            <label className="mb-1 block text-xs font-medium text-foreground">Provider</label>
            <Select value={llmProvider} onValueChange={setLlmProvider}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="openai_compatible">openai_compatible</SelectItem>
                <SelectItem value="feishu_aily">feishu_aily</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-foreground">API Key</label>
            <Input className="h-9" type="password" value={llmApiKey} onChange={e => setLlmApiKey(e.target.value)} placeholder={config?.llm_api_key?.value || '输入 API Key'} />
            <p className="text-[11px] text-muted-foreground mt-0.5">留空则保持不变</p>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-foreground">Base URL</label>
            <Input className="h-9" value={llmBaseUrl} onChange={e => setLlmBaseUrl(e.target.value)} />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-foreground">Model</label>
            <Input className="h-9" value={llmModel} onChange={e => setLlmModel(e.target.value)} />
          </div>
          <div className="flex items-center gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={doTestLLM} disabled={testingLLM}>
              {testingLLM ? <Loader2 className="h-3 w-3 animate-spin" /> : null}测试
            </Button>
            <Button size="sm" onClick={saveLLM} disabled={saving === 'llm'}>
              {saving === 'llm' ? <Loader2 className="h-3 w-3 animate-spin" /> : null}保存
            </Button>
            {llmTest && (
              <span className={`text-xs flex items-center gap-1 ${llmTest.ok ? 'text-success' : 'text-destructive'}`}>
                {llmTest.ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}{llmTest.message}
              </span>
            )}
          </div>
        </div>

        {/* Feishu */}
        <div className="space-y-4 rounded-xl border border-border bg-card p-5 shadow-sm">
          <div className="text-sm font-semibold text-foreground">飞书配置</div>
          <div>
            <label className="mb-1 block text-xs font-medium text-foreground">Region</label>
            <Select value={feishuRegion} onValueChange={setFeishuRegion}>
              <SelectTrigger className="h-9"><SelectValue /></SelectTrigger>
              <SelectContent>
                <SelectItem value="cn">飞书中国版</SelectItem>
                <SelectItem value="intl">Lark 国际版</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-foreground">App ID</label>
            <Input className="h-9" value={feishuAppId} onChange={e => setFeishuAppId(e.target.value)} placeholder="cli_xxx" />
          </div>
          <div>
            <label className="mb-1 block text-xs font-medium text-foreground">App Secret</label>
            <Input className="h-9" type="password" value={feishuAppSecret} onChange={e => setFeishuAppSecret(e.target.value)} placeholder={config?.feishu_app_secret?.value || '输入 App Secret'} />
            <p className="text-[11px] text-muted-foreground mt-0.5">留空则保持不变</p>
          </div>
          <div className="flex items-center gap-2 pt-1">
            <Button variant="outline" size="sm" onClick={doTestFeishu} disabled={testingFeishu}>
              {testingFeishu ? <Loader2 className="h-3 w-3 animate-spin" /> : null}测试
            </Button>
            <Button size="sm" onClick={saveFeishu} disabled={saving === 'feishu'}>
              {saving === 'feishu' ? <Loader2 className="h-3 w-3 animate-spin" /> : null}保存
            </Button>
            {feishuTest && (
              <span className={`text-xs flex items-center gap-1 ${feishuTest.ok ? 'text-success' : 'text-destructive'}`}>
                {feishuTest.ok ? <CheckCircle2 className="h-3 w-3" /> : <XCircle className="h-3 w-3" />}{feishuTest.message}
              </span>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}
