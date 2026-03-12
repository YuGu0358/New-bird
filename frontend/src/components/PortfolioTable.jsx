import React from "react";

function formatCurrency(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "暂无";
  }

  return new Intl.NumberFormat("zh-CN", {
    style: "currency",
    currency: "USD",
    maximumFractionDigits: 2,
  }).format(value);
}

function formatDate(value) {
  if (!value) {
    return "暂无";
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return "暂无";
  }

  return date.toLocaleString("zh-CN", {
    month: "short",
    day: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
}

function SymbolButton({ symbol, selectedSymbol, onSelectSymbol }) {
  const isActive = selectedSymbol === symbol;
  return (
    <button
      type="button"
      className={`symbol-button ${isActive ? "is-active" : ""}`}
      onClick={() => onSelectSymbol(symbol)}
    >
      {symbol}
    </button>
  );
}

export default function PortfolioTable({
  positions,
  trades,
  selectedSymbol,
  onSelectSymbol,
}) {
  return (
    <div className="table-stack">
      <div className="table-shell">
        <div className="table-heading">
          <h3>当前持仓</h3>
          <span>{positions.length}</span>
        </div>

        <table className="positions-table">
          <thead>
            <tr>
              <th>股票</th>
              <th>数量</th>
              <th>成本价</th>
              <th>现价</th>
              <th>市值</th>
              <th>盈亏</th>
            </tr>
          </thead>
          <tbody>
            {positions.length ? (
              positions.map((position) => (
                <tr key={position.symbol}>
                  <td>
                    <SymbolButton
                      symbol={position.symbol}
                      selectedSymbol={selectedSymbol}
                      onSelectSymbol={onSelectSymbol}
                    />
                  </td>
                  <td>{Number(position.qty ?? 0).toFixed(4)}</td>
                  <td>{formatCurrency(Number(position.entry_price ?? 0))}</td>
                  <td>{formatCurrency(Number(position.current_price ?? 0))}</td>
                  <td>{formatCurrency(Number(position.market_value ?? 0))}</td>
                  <td
                    className={
                      Number(position.unrealized_pl ?? 0) >= 0 ? "profit" : "loss"
                    }
                  >
                    {formatCurrency(Number(position.unrealized_pl ?? 0))}
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="empty-row" colSpan="6">
                  当前没有已成交持仓。盘后提交的市价单通常会在下一个交易时段成交。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>

      <div className="table-shell">
        <div className="table-heading">
          <h3>历史成交</h3>
          <span>{trades.length}</span>
        </div>

        <table className="positions-table">
          <thead>
            <tr>
              <th>股票</th>
              <th>数量</th>
              <th>买入价</th>
              <th>卖出价</th>
              <th>净盈亏</th>
              <th>原因</th>
              <th>平仓时间</th>
            </tr>
          </thead>
          <tbody>
            {trades.length ? (
              trades.map((trade) => (
                <tr key={trade.id}>
                  <td>
                    <SymbolButton
                      symbol={trade.symbol}
                      selectedSymbol={selectedSymbol}
                      onSelectSymbol={onSelectSymbol}
                    />
                  </td>
                  <td>{Number(trade.qty ?? 0).toFixed(4)}</td>
                  <td>{formatCurrency(Number(trade.entry_price ?? 0))}</td>
                  <td>{formatCurrency(Number(trade.exit_price ?? 0))}</td>
                  <td
                    className={Number(trade.net_profit ?? 0) >= 0 ? "profit" : "loss"}
                  >
                    {formatCurrency(Number(trade.net_profit ?? 0))}
                  </td>
                  <td>{trade.exit_reason}</td>
                  <td>{formatDate(trade.exit_date)}</td>
                </tr>
              ))
            ) : (
              <tr>
                <td className="empty-row" colSpan="7">
                  策略完成平仓后，历史成交会显示在这里。
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
}
