import { Code2, Upload, Play, ShieldCheck, Database } from 'lucide-react';
import { SectionHeader } from '../components/primitives.jsx';

export default function CodePage() {
  return (
    <div className="space-y-6">
      <div className="flex items-end justify-between">
        <div>
          <h1 className="h-page">Code Editor</h1>
          <p className="text-body-sm text-steel-200 mt-1">自己写 Python 策略 · 沙箱运行 · 注册到 strategy registry(P9)</p>
        </div>
        <span className="pill-warn">Coming in P9</span>
      </div>

      <div className="card">
        <SectionHeader title="工作流" />
        <div className="grid grid-cols-4 gap-4">
          <Step icon={Code2} num={1} title="写代码">
            浏览器内 Monaco editor,继承 <code className="font-mono text-accent-silver">core.strategy.Strategy</code> ABC
          </Step>
          <Step icon={Upload} num={2} title="上传 + 校验">
            后端 AST 静态扫描 → 检查必要方法 + 拒绝危险 import (os, subprocess, requests)
          </Step>
          <Step icon={Play} num={3} title="沙箱回测">
            一键跑 P3 backtest engine,看是否能正常订阅 universe + 处理 bar
          </Step>
          <Step icon={Database} num={4} title="注册激活">
            通过 sandbox 验证后,代码持久化到 user_strategies 表 + 通过装饰器注入 registry
          </Step>
        </div>
      </div>

      <div className="card">
        <SectionHeader title="安全考虑" />
        <ul className="text-body-sm text-steel-100 space-y-2">
          <li className="flex items-start gap-2">
            <ShieldCheck size={14} className="text-bull mt-0.5 shrink-0" />
            子进程执行 + 资源限制(CPU 时间 / 内存上限 / 文件句柄数)
          </li>
          <li className="flex items-start gap-2">
            <ShieldCheck size={14} className="text-bull mt-0.5 shrink-0" />
            白名单 import:numpy / pandas / 我们自己的 core.* 模块 / 数学库
          </li>
          <li className="flex items-start gap-2">
            <ShieldCheck size={14} className="text-bull mt-0.5 shrink-0" />
            禁止网络 / 文件系统 / 外部进程调用
          </li>
          <li className="flex items-start gap-2">
            <ShieldCheck size={14} className="text-bull mt-0.5 shrink-0" />
            执行超时(默认 60 秒,可在 Settings 配)
          </li>
        </ul>
      </div>

      <div className="card-dense bg-ink-900 border-dashed">
        <div className="text-caption text-steel-200 mb-2">示例代码(P9 编辑器开头会预填)</div>
        <pre className="font-mono text-[12px] text-steel-100 overflow-auto leading-relaxed">{`from core.strategy import Strategy, register_strategy
from app.models import StrategyExecutionParameters


@register_strategy("my_first_strategy")
class MyStrategy(Strategy):
    description = "Buy on -3% drop, sell on +5% gain."

    @classmethod
    def parameters_schema(cls):
        return StrategyExecutionParameters

    def universe(self):
        return list(self.parameters.universe_symbols)

    async def on_start(self, ctx):
        pass

    async def on_periodic_sync(self, ctx, now):
        pass

    async def on_tick(self, ctx, *, symbol, price, previous_close, timestamp=None):
        if previous_close <= 0:
            return
        drop = (price - previous_close) / previous_close
        if drop <= -0.03:
            await ctx.broker.submit_order(
                symbol=symbol, side="buy", notional=1000.0,
            )
`}</pre>
      </div>
    </div>
  );
}

function Step({ icon: Icon, num, title, children }) {
  return (
    <div className="card-dense">
      <div className="flex items-center gap-2 mb-2">
        <span className="w-6 h-6 rounded-full bg-steel-500 text-ink-950 text-caption font-bold flex items-center justify-center">
          {num}
        </span>
        <Icon size={16} className="text-steel-500" strokeWidth={1.75} />
      </div>
      <div className="text-body font-semibold text-steel-50 mb-1">{title}</div>
      <div className="text-body-sm text-steel-100 leading-relaxed">{children}</div>
    </div>
  );
}
