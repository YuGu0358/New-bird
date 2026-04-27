import { MessagesSquare, Sparkles, Users } from 'lucide-react';
import { SectionHeader } from '../components/primitives.jsx';

const PERSONAS = [
  { id: 'buffett', name: 'Warren Buffett', style: '价值 / 护城河 / 长期', social: 0.05, fundamentals: 0.9 },
  { id: 'graham', name: 'Benjamin Graham', style: '严格价值 / margin of safety', social: 0, fundamentals: 1.0 },
  { id: 'lynch', name: 'Peter Lynch', style: '"买你懂的" / 草根成长', social: 0.5, fundamentals: 0.6 },
  { id: 'soros', name: 'George Soros', style: '反身性 / 宏观 / 趋势', social: 0.7, fundamentals: 0.4 },
  { id: 'burry', name: 'Michael Burry', style: '反向 / 泡沫识别', social: 0.6, fundamentals: 0.7 },
  { id: 'sentinel', name: 'Trading Raven Sentinel', style: '舆情合成 / 多源融合(我们独有)', social: 0.8, fundamentals: 0.5, ours: true },
];

export default function IntelligencePage() {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h-page">AI Council</h1>
          <p className="text-body-sm text-steel-200 mt-1">5 大师 + 1 Sentinel · 投资风格化分析(P7,即将上线)</p>
        </div>
        <span className="pill-warn">Coming in P7</span>
      </div>

      <div className="card">
        <SectionHeader title="即将上线的能力" />
        <div className="grid grid-cols-3 gap-4 text-body-sm">
          <FeatureBlock icon={MessagesSquare} title="单 persona 分析">
            选 agent + 输入 symbol + 提问 → LLM 风格化输出 verdict/confidence/key_factors
          </FeatureBlock>
          <FeatureBlock icon={Users} title="Council 多 agent 圆桌">
            一次同时让 N 个 persona 分析同一 symbol,看分歧 / 共识
          </FeatureBlock>
          <FeatureBlock icon={Sparkles} title="历史回看">
            每次分析持久化,可滚回看 "Buffett 在 6 个月前对 NVDA 的判断"
          </FeatureBlock>
        </div>
      </div>

      <div className="card">
        <SectionHeader title="Personas" subtitle="风格 + 各源数据权重" />
        <table className="tbl">
          <thead>
            <tr>
              <th>ID</th>
              <th>名字</th>
              <th>风格</th>
              <th className="tbl-num">Social weight</th>
              <th className="tbl-num">Fundamentals weight</th>
            </tr>
          </thead>
          <tbody>
            {PERSONAS.map((p) => (
              <tr key={p.id} className={p.ours ? 'bg-social-tint' : ''}>
                <td className="font-mono text-accent-silver">{p.id}</td>
                <td className="font-medium text-steel-50">
                  {p.name}
                  {p.ours && <span className="ml-2 pill-social">独家</span>}
                </td>
                <td className="text-steel-200">{p.style}</td>
                <td className="tbl-num">{p.social.toFixed(2)}</td>
                <td className="tbl-num">{p.fundamentals.toFixed(2)}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="card-dense bg-ink-900 border-dashed">
        <div className="text-caption text-steel-200 mb-1">实现路径(P7 已规划)</div>
        <ol className="text-body-sm text-steel-100 list-decimal list-inside space-y-1">
          <li>Persona 数据模型 + 6 个内置 persona 的 system prompt</li>
          <li>上下文打包器(price + 基本面 + 新闻 + 社媒 + 持仓)</li>
          <li>LLM provider router(OpenAI 主 / Claude / DeepSeek 备份)</li>
          <li>4 个 API:GET /api/agents/personas · POST /api/agents/analyze · POST /api/agents/council · GET /api/agents/history</li>
          <li>DB:agent_analysis 表持久化每次分析</li>
        </ol>
      </div>
    </div>
  );
}

function FeatureBlock({ icon: Icon, title, children }) {
  return (
    <div className="card-dense">
      <Icon size={18} className="text-steel-500 mb-2" strokeWidth={1.75} />
      <div className="text-body font-semibold text-steel-50 mb-1">{title}</div>
      <div className="text-body-sm text-steel-100">{children}</div>
    </div>
  );
}
