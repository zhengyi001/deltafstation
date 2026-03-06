"""
引擎快照 - SimulationEngine 与 StrategyEngine 共用。

对外：inject_strategy_id, build_state_from_engine, restore_engine_from_state
内部：_ts_str, _parse_dt_like, _order_seq_from_id
"""
from typing import Any, Optional
from datetime import datetime
import re


def inject_strategy_id(state: dict, strategy_id: Optional[str]) -> None:
    """为 state 中的 trades 和 orders 注入 strategy_id（仅当该项为空时），便于交易数据与策略关联。"""
    sid = strategy_id if strategy_id else "manual"
    for item in (state.get("trades") or []) + (state.get("orders") or []):
        if not (item.get("strategy_id") or "").strip():
            item["strategy_id"] = sid


def _ts_str(ts: Any) -> str:
    return ts.isoformat() if hasattr(ts, "isoformat") else str(ts)


def build_state_from_engine(eng) -> dict:
    """从 trade engine 构建 state 字典（资金、持仓、成交、订单、冻结）。"""
    pos = {
        s: {"quantity": p["quantity"], "avg_price": p["avg_price"]}
        for s, p in eng.position_manager.positions.items()
    }
    trades = [
        {
            "symbol": t["symbol"],
            "action": t["type"],
            "quantity": abs(t["quantity"]),
            "price": t["price"],
            "timestamp": _ts_str(t.get("timestamp")),
            "order_id": t.get("order_id"),
            "commission": t.get("commission", 0),
            **({"strategy_id": t["strategy_id"]} if t.get("strategy_id") else {}),
        }
        for t in eng.trades
    ]
    orders = []
    frozen = 0.0
    for o in eng.order_manager.get_order_history():
        orders.append(
            {
                "id": o["id"],
                "symbol": o["symbol"],
                "action": "buy" if o["quantity"] > 0 else "sell",
                "quantity": abs(o["quantity"]),
                "price": o["price"],
                "status": o["status"],
                "type": o["order_type"],
                "time": _ts_str(o.get("created_at")),
                **({"strategy_id": o["strategy_id"]} if o.get("strategy_id") else {}),
            }
        )
        if o.get("status") == "pending" and o.get("quantity", 0) > 0 and o.get("price"):
            frozen += o["quantity"] * o["price"]
    return {
        "current_capital": eng.cash,
        "positions": pos,
        "trades": trades,
        "orders": orders,
        "frozen_capital": frozen,
    }


def _parse_dt_like(value: Any) -> datetime:
    """将字符串/时间对象转为 datetime，失败回退到当前时间。"""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value)
        except Exception:
            return datetime.now()
    return datetime.now()


def _order_seq_from_id(order_id: Any) -> int:
    """从订单 id 提取数值序号，支持 ORD_000123 或整数 id。"""
    if order_id is None:
        return 0
    if isinstance(order_id, int):
        return max(0, order_id)
    if isinstance(order_id, str):
        m = re.search(r"(\d+)$", order_id)
        return int(m.group(1)) if m else 0
    return 0


def restore_engine_from_state(eng, state: dict) -> None:
    """用 state 快照还原 trade engine 的资金/持仓/成交/订单/订单号。"""
    if not eng or not state:
        return

    # 资金
    if state.get("current_capital") is not None:
        eng.cash = float(state["current_capital"])

    # 持仓
    for sym, p in (state.get("positions") or {}).items():
        eng.position_manager.positions[sym] = {
            "quantity": p.get("quantity", 0),
            "avg_price": p.get("avg_price", 0.0),
        }

    # 历史成交
    eng.trades = []
    for t in (state.get("trades") or []):
        action = t.get("action", "buy")
        qty = int(t.get("quantity", 0) or 0)
        signed_qty = qty if action == "buy" else -qty
        eng.trades.append(
            {
                "symbol": t.get("symbol"),
                "type": action,
                "quantity": signed_qty,
                "price": float(t.get("price", 0) or 0),
                "timestamp": t.get("timestamp"),
                "order_id": t.get("order_id"),
                "commission": float(t.get("commission", 0) or 0),
                **({"strategy_id": sid} if (sid := (t.get("strategy_id") or "").strip()) else {}),
            }
        )

    # 订单 + order_counter（引擎生成新单时须基于 order_counter 自增，否则重启后 id 会从 1 重编）
    om = eng.order_manager
    om.orders = {}
    max_seq = 0  # 初始 0，下面循环中按历史订单 id 推成最大值，最后赋给 om.order_counter
    for o in (state.get("orders") or []):
        oid = o.get("id")
        if not oid:
            continue
        action = o.get("action", "buy")
        qty = int(o.get("quantity", 0) or 0)
        signed_qty = qty if action == "buy" else -qty
        created_at = _parse_dt_like(o.get("time"))
        om.orders[oid] = {
            "id": oid,
            "symbol": o.get("symbol"),
            "quantity": signed_qty,
            "order_type": o.get("type", "limit"),
            "price": float(o.get("price", 0) or 0),
            "stop_price": None,
            "status": o.get("status", "pending"),
            "created_at": created_at,
            "updated_at": created_at,
            **({"strategy_id": sid} if (sid := (o.get("strategy_id") or "").strip()) else {}),
        }
        max_seq = max(max_seq, _order_seq_from_id(oid))

    om.order_counter = max_seq
