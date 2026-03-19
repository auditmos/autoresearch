"""
strategy.py — BTC daily swing: LSTM + on-chain + macro + FOMC
Agent modifies THIS file. prepare.py is read-only.
"""

import pandas as pd
import numpy as np
import torch
import torch.nn as nn
from datetime import datetime
from pathlib import Path
pd.set_option('future.no_silent_downcasting', True)
from prepare import evaluate, plot_equity

RESULTS_FILE = Path(__file__).parent / "results.tsv"
OPIS = "LSTM_baseline_onchain_tier1_daily"
DEVICE = torch.device("cuda" if torch.cuda.is_available() else "cpu")
LOOKBACK = 60     # 60 daily candles (~2 months context)
SEED = 42

# ATR-based risk management: R:R 1:3
ATR_SL_MULT = 1.5   # stop loss = 1.5 x ATR(14)
ATR_TP_MULT = 4.5   # take profit = 3 x SL = 4.5 x ATR(14)


# ─── Indicators ──────────────────────────────────────────────────

def ema(series, span):
    return series.ewm(span=span, min_periods=span).mean()

def rsi(series, period=14):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)
    ag = gain.ewm(alpha=1/period, min_periods=period).mean()
    al = loss.ewm(alpha=1/period, min_periods=period).mean()
    return 100 - (100 / (1 + ag / al.replace(0, 1e-9)))

def macd(series, fast=12, slow=26, signal=9):
    ef = series.ewm(span=fast, min_periods=fast).mean()
    es = series.ewm(span=slow, min_periods=slow).mean()
    ml = ef - es
    sl = ml.ewm(span=signal, min_periods=signal).mean()
    return {"macd": ml, "signal": sl, "hist": ml - sl}

def atr(df, period=14):
    h, l, c = df["high"], df["low"], df["close"]
    pc = c.shift(1)
    tr = pd.concat([h-l, (h-pc).abs(), (l-pc).abs()], axis=1).max(axis=1)
    return tr.ewm(span=period, min_periods=period).mean()


# ─── LSTM ────────────────────────────────────────────────────────

class SignalLSTM(nn.Module):
    def __init__(self, n_features, hidden=128, n_layers=2, dropout=0.3):
        super().__init__()
        self.input_bn = nn.BatchNorm1d(n_features)
        self.lstm = nn.LSTM(
            input_size=n_features, hidden_size=hidden, num_layers=n_layers,
            batch_first=True, dropout=dropout if n_layers > 1 else 0)
        self.head = nn.Sequential(
            nn.BatchNorm1d(hidden), nn.GELU(), nn.Dropout(0.2),
            nn.Linear(hidden, hidden // 4), nn.GELU(), nn.Dropout(0.1),
            nn.Linear(hidden // 4, 1), nn.Tanh())

    def forward(self, x):
        b, s, f = x.shape
        x = self.input_bn(x.transpose(1, 2)).transpose(1, 2)
        out, _ = self.lstm(x)
        return self.head(out[:, -1, :]).squeeze(-1)


# ─── Features ────────────────────────────────────────────────────

def build_features(df, context):
    """Build feature matrix from BTC OHLCV + context data."""
    close = df["close"]

    features = pd.DataFrame(index=df.index)

    # Price TA
    ema20 = ema(close, 20)
    ema50 = ema(close, 50)
    ema200 = ema(close, 200)
    features["ema20_dist"] = (close - ema20) / close
    features["ema50_dist"] = (close - ema50) / close
    features["ema200_dist"] = (close - ema200) / close

    rsi_val = rsi(close, 14)
    features["rsi_norm"] = (rsi_val - 50) / 50

    macd_data = macd(close)
    features["macd_hist"] = macd_data["hist"] / close

    atr_val = atr(df, 14)
    features["atr_pct"] = atr_val / close

    features["ret_1"] = close.pct_change(1).clip(-0.15, 0.15)
    features["ret_5"] = close.pct_change(5).clip(-0.3, 0.3)
    features["ret_10"] = close.pct_change(10).clip(-0.4, 0.4)
    features["ret_20"] = close.pct_change(20).clip(-0.5, 0.5)

    vol = df["volume"]
    vol_sma = vol.rolling(20).mean()
    features["vol_ratio"] = (vol / vol_sma.replace(0, 1e-9) - 1).clip(-2, 2)
    features["hl_range"] = (df["high"] - df["low"]) / close

    bb_std = close.rolling(20).std()
    features["bb_width"] = (bb_std * 2) / close

    # On-chain features (forward-filled to daily)
    onchain_keys = [k for k in context if k.startswith("onchain_")]
    for key in onchain_keys:
        ctx = context[key]
        if len(ctx) < 10:
            continue
        name = key.replace("onchain_", "")
        vals = ctx["value"].reindex(df.index, method="ffill")
        features[f"oc_{name}"] = vals
        features[f"oc_{name}_chg5"] = vals.pct_change(5).clip(-1, 1)

    # FRED macro features (forward-filled)
    fred_keys = [k for k in context if k.startswith("fred_")]
    for key in fred_keys:
        ctx = context[key]
        if len(ctx) < 10:
            continue
        name = key.replace("fred_", "")
        vals = ctx["value"].reindex(df.index, method="ffill")
        features[f"m_{name}"] = vals
        features[f"m_{name}_chg"] = vals.pct_change(5).clip(-1, 1)

    # Funding rate
    if "funding_rate" in context and len(context["funding_rate"]) > 10:
        fr = context["funding_rate"]["value"].reindex(df.index, method="ffill")
        features["funding_rate"] = fr.clip(-0.01, 0.01) * 100  # scale to ~[-1, 1]

    # FOMC calendar
    if "_fomc" in context:
        fomc = context["_fomc"]
        for col in fomc.columns:
            features[col] = fomc[col].reindex(df.index).fillna(0)

    # Normalize all features to reasonable range
    for col in features.columns:
        s = features[col]
        if s.std() > 0:
            # Z-score with clipping
            features[col] = ((s - s.rolling(60, min_periods=20).mean())
                             / s.rolling(60, min_periods=20).std().replace(0, 1e-9)).clip(-3, 3)

    return features


# ─── Training ────────────────────────────────────────────────────

def make_sequences(X, y, lookback):
    seqs, targets = [], []
    for i in range(lookback, len(X)):
        seqs.append(X[i-lookback:i])
        targets.append(y[i])
    return np.array(seqs, dtype=np.float32), np.array(targets, dtype=np.float32)


def train_lstm(features, targets, lookback=LOOKBACK, n_epochs=300, lr=0.002, seed=SEED):
    torch.manual_seed(seed)
    np.random.seed(seed)

    valid = features.dropna().index.intersection(targets.dropna().index)
    feat_df = features.loc[valid]
    tgt_series = targets.loc[valid]

    X_raw = feat_df.values.astype(np.float32)
    y_raw = tgt_series.values.astype(np.float32)

    yc = np.clip(y_raw, np.percentile(y_raw, 2), np.percentile(y_raw, 98))
    ym = max(abs(yc.max()), abs(yc.min()), 1e-9)
    yn = np.clip(yc / ym, -1, 1)

    X_seq, y_seq = make_sequences(X_raw, yn, lookback)
    if len(X_seq) < 100:
        return None

    Xt = torch.tensor(X_seq, device=DEVICE)
    yt = torch.tensor(y_seq, device=DEVICE)

    model = SignalLSTM(n_features=X_seq.shape[2], hidden=128, n_layers=2, dropout=0.3).to(DEVICE)
    opt = torch.optim.AdamW(model.parameters(), lr=lr, weight_decay=0.02)
    sched = torch.optim.lr_scheduler.CosineAnnealingLR(opt, n_epochs)

    bs = min(256, len(Xt))
    best_loss, patience, no_imp = float("inf"), 30, 0

    model.train()
    for ep in range(n_epochs):
        perm = torch.randperm(len(Xt), device=DEVICE)
        Xs, ys = Xt[perm], yt[perm]
        el, nb = 0.0, 0
        for i in range(0, len(Xt), bs):
            xb, yb = Xs[i:i+bs], ys[i:i+bs]
            pred = model(xb)
            mse = ((pred - yb) ** 2).mean()
            loss = mse - 0.01 * pred.abs().mean()
            opt.zero_grad(); loss.backward()
            torch.nn.utils.clip_grad_norm_(model.parameters(), 1.0)
            opt.step(); el += mse.item(); nb += 1
        sched.step()
        al = el / max(nb, 1)
        if al < best_loss - 1e-6: best_loss, no_imp = al, 0
        else: no_imp += 1
        if no_imp >= patience: break

    model.eval()
    return model, valid, lookback


@torch.no_grad()
def predict_lstm(model_info, features):
    if model_info is None:
        return pd.Series(0.0, index=features.index)

    model, valid_idx, lookback = model_info
    feat_df = features.loc[features.index.isin(valid_idx)].dropna()
    X_raw = feat_df.values.astype(np.float32)
    result = pd.Series(0.0, index=features.index)

    if len(X_raw) <= lookback:
        return result

    seqs, seq_indices = [], []
    for i in range(lookback, len(X_raw)):
        seqs.append(X_raw[i-lookback:i])
        seq_indices.append(feat_df.index[i])

    Xt = torch.tensor(np.array(seqs, dtype=np.float32), device=DEVICE)
    preds = []
    bs = 1024
    for i in range(0, len(Xt), bs):
        pred = model(Xt[i:i+bs]).cpu().numpy()
        preds.append(pred)
    raw = np.concatenate(preds)

    for idx, val in zip(seq_indices, raw):
        result.loc[idx] = val
    return result


# ─── Feature attribution ────────────────────────────────────────

def get_top_features(features, nn_pred, idx, n=3):
    """Simple attribution: features with largest absolute value at given index."""
    if idx not in features.index:
        return []
    row = features.loc[idx].dropna()
    if len(row) == 0:
        return []
    top = row.abs().nlargest(n)
    result = []
    for name, val in top.items():
        direction = "+" if row[name] > 0 else "-"
        result.append(f"{name}({direction}{val:.2f})")
    return result


# ─── ATR stop/target management ─────────────────────────────────

def apply_atr_risk(close, atr_val, signals, sl_mult=ATR_SL_MULT, tp_mult=ATR_TP_MULT):
    """Apply ATR-based SL and TP. R:R = tp_mult/sl_mult."""
    result = signals.copy()
    entry_price = np.nan
    direction = 0
    sl_price = tp_price = np.nan

    for i in range(len(close)):
        pos = result.iloc[i]
        price = close.iloc[i]
        av = atr_val.iloc[i]
        if np.isnan(av):
            continue

        if pos > 0 and direction != 1:
            # New long entry
            entry_price = price
            sl_price = price - sl_mult * av
            tp_price = price + tp_mult * av
            direction = 1
        elif pos < 0 and direction != -1:
            # New short entry
            entry_price = price
            sl_price = price + sl_mult * av
            tp_price = price - tp_mult * av
            direction = -1
        elif pos == 0:
            direction = 0
            continue

        # Check SL/TP
        if direction == 1:
            if price <= sl_price:
                result.iloc[i] = 0
                direction = 0
            elif price >= tp_price:
                result.iloc[i] = 0
                direction = 0
        elif direction == -1:
            if price >= sl_price:
                result.iloc[i] = 0
                direction = 0
            elif price <= tp_price:
                result.iloc[i] = 0
                direction = 0

    return result


# ─── Strategy ────────────────────────────────────────────────────

def strategy(df, context):
    """
    BTC daily swing: LSTM confidence → discrete signals → ATR SL/TP (R:R 1:3).
    Returns (signals, attributions) tuple.
    """
    close = df["close"]
    features = build_features(df, context)

    # Target: forward 5-day return (daily swing horizon)
    fwd_ret = close.pct_change(5).shift(-5)

    # Train on first 80% of data
    te = int(len(df) * 0.8)
    if te < LOOKBACK + 100:
        return pd.Series(0.0, index=df.index), []

    model_info = train_lstm(features.iloc[:te], fwd_ret.iloc[:te],
                            lookback=LOOKBACK, n_epochs=300, lr=0.002, seed=SEED)

    nn_pred = predict_lstm(model_info, features)

    # Discrete signals from LSTM confidence
    signals = pd.Series(0.0, index=df.index)
    signals[nn_pred > 0.30] = 1.0
    signals[nn_pred < -0.30] = -1.0

    # ATR risk management: SL=1.5xATR, TP=4.5xATR (R:R 1:3)
    atr_val = atr(df, period=14)
    signals = apply_atr_risk(close, atr_val, signals,
                             sl_mult=ATR_SL_MULT, tp_mult=ATR_TP_MULT)

    # Feature attributions for signal report
    attributions = []
    for idx in df.index[-30:]:
        sig_val = signals.get(idx, 0)
        top = get_top_features(features, nn_pred, idx)
        attributions.append({
            "date": str(idx.date()) if hasattr(idx, 'date') else str(idx),
            "signal": float(sig_val),
            "top_features": top,
        })

    return signals, attributions


# ─── Runner ──────────────────────────────────────────────────────

if __name__ == "__main__":
    print("=" * 60)
    print(f"AUTOQUANT — BTC Daily Swing (LSTM on {DEVICE})")
    print(f"  Lookback: {LOOKBACK}d, SL: {ATR_SL_MULT}xATR, TP: {ATR_TP_MULT}xATR (R:R 1:3)")
    print("=" * 60 + "\n")

    results = evaluate(strategy)
    score = results.get("score", 0.0)

    print(f"\n{'='*60}\nFINAL SCORE: {score}\n{'='*60}")
    plot_equity(results)

    if not RESULTS_FILE.exists():
        with open(RESULTS_FILE, "w") as f:
            f.write("nr\tdata\tscore\tsharpe_train\tsharpe_val\t"
                    "return_train\treturn_val\tmax_dd_val\ttrades_val\t"
                    "avg_rr\tprofit_factor\topis\n")
    with open(RESULTS_FILE, "r") as f:
        nr = max(len(f.readlines()) - 1, 0) + 1

    t = results.get("train", {})
    v = results.get("val", {})
    row = (f"{nr}\t{datetime.now().strftime('%Y-%m-%d %H:%M')}\t{score:.4f}\t"
           f"{t.get('sharpe', 0):.3f}\t{v.get('sharpe', 0):.3f}\t"
           f"{t.get('total_return', 0):.2%}\t{v.get('total_return', 0):.2%}\t"
           f"{v.get('max_drawdown', 0):.2%}\t{v.get('num_trades', 0)}\t"
           f"{v.get('avg_rr', 0):.2f}\t{v.get('profit_factor', 0):.2f}\t{OPIS}")
    with open(RESULTS_FILE, "a") as f:
        f.write(row + "\n")
    print(f"\nSaved result #{nr} -> {RESULTS_FILE}")
