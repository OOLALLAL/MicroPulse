from collections import deque
from websocket import WebSocketApp
import pandas as pd
import json
import time
import os

class MicroPulseIndicators:
    def __init__(self):
        self.mid_price: float = 0.0
        self.obi: float = 0.0

        self.cum_buy_vol: float = 0.0
        self.cum_sell_vol: float = 0.0
        self.cvd: float = 0.0

        self.window_sec: float = 10.0
        self.price_buffer = deque()  # (time, mid_price)
        self.trade_buffer = deque()  # (time, side, quantity)

        self.wall_factor: float = 8.0
        self.wall_drop_ratio: float = 0.3
        self.bid_walls = {}
        self.ask_walls = {}
        self.last_wall_event = None

        self.trade_quantity: float = 0.01
        self.position = {} # {ts: {price: p, quantity: q}}

        self.transaction = []

    def _update_position(self, ts, price, side: float):
        self.position[ts] = {
            'price': price,
            'quantity': self.trade_quantity * side,
        }

    def _trim_buffers(self, ts):

        cutoff = ts - self.window_sec

        while self.price_buffer and self.price_buffer[0][0] < cutoff:
            self.price_buffer.popleft()

        while self.trade_buffer and self.trade_buffer[0][0] < cutoff:
            self.trade_buffer.popleft()

    def _update_transaction(self, ts, price, current_ts, mid, quantity, reason):
        side = "long" if quantity > 0 else "short"
        direction = 1 if quantity > 0 else -1
        pnl_ratio = direction * (mid - price) / price

        self.transaction.append(
            {
                "entry_ts": ts,
                "entry_price": price,
                "exit_ts": current_ts,
                "exit_price": mid,
                "quantity": quantity,
                "side": side,
                "pnl_ratio": pnl_ratio,
                "exit_reason": reason,
            }
        )

    def _log_transactions(self):
        if not self.transaction:
            return
        df = pd.DataFrame(self.transaction)
        df.to_csv(
            "transaction.csv",
            mode="a",
            header=not os.path.exists("transaction.csv"),
            index=False,
        )

    def _check_wall_removal(self, ts, bids, asks):
        bid_map = {float(p): float(s) for p, s in bids}
        ask_map = {float(p): float(s) for p, s in asks}

        for price, info in list(self.bid_walls.items()):
            wall_size = float(info["size"])
            bid_size = bid_map.get(price, 0.0)

            if bid_size < wall_size * self.wall_drop_ratio:
                self.last_wall_event = {
                    "side": "bid",
                    "price": price,
                    "old_size": wall_size,
                    "new_size": bid_size,
                    "removed_ts": ts,
                }
                del self.bid_walls[price]
        for price, info in list(self.ask_walls.items()):
            wall_size = float(info["size"])
            ask_size = ask_map.get(price, 0.0)

            if ask_size < wall_size * self.wall_drop_ratio:
                self.last_wall_event = {
                    "side": "ask",
                    "price": price,
                    "old_size": wall_size,
                    "new_size": ask_size,
                    "removed_ts": ts,
                }
                del self.ask_walls[price]

    def _update_walls(self, ts, bids, asks):

        avg_bid_size = sum(float(size) for price, size in bids) / len(bids)
        avg_ask_size = sum(float(size) for price, size in asks) / len(asks)

        for price, size in bids:
            price = float(price)
            size = float(size)
            if size > avg_bid_size * self.wall_factor:
                if price not in self.bid_walls:
                    self.bid_walls[price] = {
                        "size": size,
                        "created_ts": ts
                    }
        for price, size in asks:
            price = float(price)
            size = float(size)
            if size > avg_ask_size * self.wall_factor:
                if price not in self.ask_walls:
                    self.ask_walls[price] = {
                        "size": size,
                        "created_ts": ts
                    }
        self._check_wall_removal(ts, bids, asks)

    def get_mid_price(self, bids, asks) -> None:
        ts = time.time()
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])

        self.mid_price = (best_bid + best_ask) / 2

        self.price_buffer.append((ts, self.mid_price))
        self._trim_buffers(ts)

        self._update_walls(ts, bids, asks)

    def get_obi(self, bids, asks) -> None:
        total_bid = sum(float(bid[1]) for bid in bids)
        total_ask = sum(float(ask[1]) for ask in asks)

        if total_bid + total_ask == 0:
            self.obi = 0.0
        else:
            self.obi = (total_bid - total_ask) / (total_bid + total_ask)

    def get_volume_delta(self, data) -> None:
        ts = time.time()
        qty = float(data.get("q"))
        buyer_is_maker = data.get("m")

        if buyer_is_maker == True:  # buyer is maker(=seller is taker)
            self.cum_sell_vol += qty
            side = "sell"

        else:  # buyer is taker(=seller is maker)
            self.cum_buy_vol += qty
            side = "buy"

        self.trade_buffer.append((ts, side, qty))
        self._trim_buffers(ts)

        self.cvd = self.cum_buy_vol - self.cum_sell_vol

    def get_window_stats(self):

        if not self.price_buffer:
            return None

        mids = [m for _, m in self.price_buffer]
        mid_start = self.price_buffer[0][1]
        mid_high = max(mids)
        mid_low = min(mids)

        spike_up = (mid_high - mid_start) / mid_start
        spike_down = (mid_start - mid_low) / mid_start

        window_buy_qty = sum(q for _, side, q in self.trade_buffer if side == "buy")
        window_sell_qty = sum(q for _, side, q in self.trade_buffer if side == "sell")
        window_cvd = window_buy_qty - window_sell_qty

        window_trade_count = len(self.trade_buffer)
        if window_trade_count > 0:
            trades_per_sec = window_trade_count / self.window_sec
            avg_trade_size = sum(q for _, _, q in self.trade_buffer) / window_trade_count
        else:
            trades_per_sec = 0
            avg_trade_size = 0

        return {
            "mid": self.mid_price,
            "obi": self.obi,
            "spike_up": spike_up,
            "spike_down": spike_down,
            "window_buy_qty": window_buy_qty,
            "window_sell_qty": window_sell_qty,
            "window_cvd": window_cvd,
            "cvd": self.cvd,
            "window_trade_count": window_trade_count,
            "trades_per_sec": trades_per_sec,
            "avg_trade_size": avg_trade_size,
            "last_wall_event": self.last_wall_event,
            "position": self.position,
        }


ind = MicroPulseIndicators()
STREAM_URL = (
    "wss://fstream.binance.com/stream?"
    "streams=btcusdt@depth5@100ms/btcusdt@trade"
)

def check_entry(stats):
    wall = stats["last_wall_event"]
    if wall is None:
        return
    side = wall["side"]
    mid = stats["mid"]
    spike_up = stats["spike_up"]
    spike_down = stats["spike_down"]
    window_cvd = stats["window_cvd"]
    obi = stats["obi"]

    MIN_SPIKE = 0.0005
    MIN_CVD = 0.1

    if side == "ask":
        if spike_up > MIN_SPIKE and window_cvd < -MIN_CVD:
            print(
                f"[SIGNAL SHORT] mid={mid:.2f}, spike_up={spike_up:.4%}, "
                f"win_cvd={window_cvd:.4f}, obi={obi:.3f}, wall={wall}"
            )
            ind._update_position(time.time(), mid, -1)

    elif side == "bid":
        if spike_down > MIN_SPIKE and window_cvd > MIN_CVD:
            print(
                f"[SIGNAL LONG] mid={mid:.2f}, spike_dn={spike_down:.4%}, "
                f"win_cvd={window_cvd:.4f}, obi={obi:.3f}, wall={wall}"
            )
            ind._update_position(time.time(), mid, 1)
    ind.last_wall_event = None

def check_exit(stats):
    mid = stats["mid"]
    pos = ind.position
    if not pos:
        return
    current_ts = time.time()
    TP = 0.0008
    SL = 0.0005

    for ts, trade in list(pos.items()):
        price = trade["price"]
        quantity = trade["quantity"]

        if current_ts - ts > 15:
            ind._update_transaction(ts, price, current_ts, mid, quantity, "time_stop")
            pos.pop(ts)
            continue

        direction = quantity / abs(quantity)
        position_return = direction * (mid - price)/price

        if position_return >= TP:
            reason = "tp"
        elif position_return < -SL:
            reason = "sl"
        if reason is not None:
            ind._update_transaction(ts, price, current_ts, mid, quantity, reason)
            pos.pop(ts)

        # more strategy

def on_message(ws, message):
    msg = json.loads(message)
    stream = msg.get("stream", "")
    data = msg.get("data", {})
    if data.get("e") == "depthUpdate":
        bids = data["b"]
        asks = data["a"]
        ind.get_mid_price(bids, asks)
        ind.get_obi(bids, asks)
    else:
        if data.get("X") == "MARKET":
            ind.get_volume_delta(data)

    stats = ind.get_window_stats()

    if stats is not None:
        print(
            f"mid={stats['mid']:.2f}, "
            f"obi={stats['obi']:.3f}, "
            f"spk_up={stats['spike_up']:.4f}, "
            f"spk_dn={stats['spike_down']:.4f}, "
            f"buy10s={stats['window_buy_qty']:.4f}, "
            f"sell10s={stats['window_sell_qty']:.4f}, "
            f"delta10s={stats['window_cvd']:.4f}, "
            f"cvd={stats['cvd']:.4f}, "
            f"window_trade_count={stats['window_trade_count']:.4f}, "
            f"trades_per_sec={stats['trades_per_sec']:.4f}, "
            f"avg_trade_size={stats['avg_trade_size']:.4f}, "
            f"removed_wall={stats['last_wall_event']}"
        )
        check_entry(stats)
        check_exit(stats)



def on_error(ws, error):
    print("Error: ", error)


def on_close(ws, close_status_code, close_msg):
    ind._log_transactions()
    print("WebSocket closed ", close_status_code, close_msg)


def on_open(ws):
    print("WebSocket connected to Binance future BTCUSDT stream")


if __name__ == "__main__":
    ws = WebSocketApp(
        STREAM_URL,
        on_open=on_open,
        on_message=on_message,
        on_error=on_error,
        on_close=on_close,
    )
    ws.run_forever()