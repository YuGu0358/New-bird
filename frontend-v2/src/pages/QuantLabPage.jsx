import { Calculator, TrendingUp, Activity, Layers } from 'lucide-react';
import { SectionHeader } from '../components/primitives.jsx';

const MODULES = [
  { name: '期权定价', desc: 'Black-Scholes / 二叉树 / 蒙卡 · 欧式/美式期权', icon: TrendingUp },
  { name: '希腊字母', desc: 'Delta / Gamma / Vega / Theta / Rho 实时计算', icon: Activity },
  { name: '债券估值', desc: '到期收益率 / 久期 / 凸性 / 即期利率', icon: Calculator },
  { name: 'VaR / CVaR', desc: '历史模拟 / 蒙卡 / 参数法,可指定置信度', icon: Layers },
  { name: '波动率曲面', desc: '隐含波动率拟合 + 微笑/期限结构', icon: TrendingUp },
  { name: '收益曲线', desc: '插值 / Bootstrap / 远期利率', icon: Activity },
];

export default function QuantLabPage() {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h-page">Quant Lab</h1>
          <p className="text-body-sm text-steel-200 mt-1">QuantLib 集成 · 衍生品定价 + 风险指标 + 收益曲线(P8)</p>
        </div>
        <span className="pill-warn">Coming in P8</span>
      </div>

      <div className="card">
        <SectionHeader title="即将引入的模块" subtitle="基于开源 QuantLib-Python,Fincept Terminal 同款" />
        <div className="grid grid-cols-3 gap-4">
          {MODULES.map(({ name, desc, icon: Icon }) => (
            <div key={name} className="card-dense card-hover">
              <Icon size={20} className="text-steel-500 mb-2" strokeWidth={1.75} />
              <div className="text-body font-semibold text-steel-50 mb-1">{name}</div>
              <div className="text-body-sm text-steel-100 leading-relaxed">{desc}</div>
            </div>
          ))}
        </div>
      </div>

      <div className="card-dense bg-ink-900 border-dashed">
        <div className="text-caption text-steel-200 mb-1">实现路径(P8 已规划)</div>
        <ol className="text-body-sm text-steel-100 list-decimal list-inside space-y-1">
          <li>pip install QuantLib-Python(BSD 开源)</li>
          <li>backend/app/services/quantlib_service.py 包装常用 6-8 个工具</li>
          <li>对应 8 个 API 端点(POST /api/quantlib/option/price 等)</li>
          <li>本页面表单驱动 — 输入参数 → 看结果 + 计算示意图</li>
          <li>Tests: 跟 Hull 教科书 + 已知解析解的对比</li>
        </ol>
      </div>
    </div>
  );
}
