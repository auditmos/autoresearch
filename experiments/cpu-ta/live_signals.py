"""Live signal monitor — load best strategy from git, detect changes, notify via Telegram."""

import json
import os
import subprocess
import sys
import types
from datetime import date, timedelta

import pandas as pd

ASSETS = ["SPY", "BTC", "ETH"]
LABELS = {1: "LONG 🟢", -1: "SHORT 🔴", 0: "FLAT ⚪"}
STATE_FILE = os.path.expanduser("~/.cache/autoquant/live_signals_state.json")
VERIFY_DAYS = int(os.environ.get("VERIFY_DAYS", "7"))


def find_repo():
    if "REPO_DIR" in os.environ:
        return os.environ["REPO_DIR"]
    if os.path.exists("/repo/.git") or os.path.exists("/repo/results.tsv"):
        return "/repo"
    d = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        if os.path.exists(os.path.join(d, "results.tsv")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


def refresh_all(api_key):
    from prepare import CACHE_DIR, load_asset
    today = date.today()
    assets = {}
    for sym in ASSETS:
        path = os.path.join(CACHE_DIR, f"{sym}.parquet")
        if os.path.exists(path):
            df = pd.read_parquet(path)
            last = df["timestamp"].max().date()
            if last >= today - timedelta(days=1):
                print(f"  {sym}: {len(df)} rows, last={last} (cached)")
                assets[sym] = df
                continue
            os.remove(path)
            print(f"  {sym}: stale ({last}), re-downloading...")
        assets[sym] = load_asset(sym, api_key)
        print(f"  {sym}: {len(assets[sym])} rows, last={assets[sym]['timestamp'].max().date()}")
    return assets


def load_best_strategy(repo):
    tsv = os.path.join(repo, "results.tsv")
    if not os.path.exists(tsv):
        print(f"results.tsv not found at {tsv}"); sys.exit(1)
    df = pd.read_csv(tsv, sep="\t")
    keeps = df[df["status"] == "keep"]
    if keeps.empty:
        print("No 'keep' entries in results.tsv — run at least one experiment first"); sys.exit(1)
    row = keeps.iloc[-1]
    commit = str(row["commit"])
    score = float(row["score"])
    sharpe = float(row["sharpe"]) if "sharpe" in row else 0.0

    code = subprocess.check_output(
        ["git", "-C", repo, "show", f"{commit}:strategy.py"]
    ).decode()
    mod = types.ModuleType("live_strategy")
    exec(code, mod.__dict__)
    return mod.strategy, commit, score, sharpe


def find_notify():
    repo = find_repo()
    for p in [os.environ.get("NOTIFY_SH", ""), "./notify.sh",
               os.path.join(repo, "containers/autoquant/notify.sh")]:
        if p and os.path.exists(p):
            return p
    return None


def notify(msg):
    sh = find_notify()
    if sh:
        subprocess.run([sh, msg], check=False)
    else:
        print(f"[no notify.sh] {msg}")


def load_state():
    if os.path.exists(STATE_FILE):
        with open(STATE_FILE) as f:
            return json.load(f)
    return {}


def save_state(data):
    os.makedirs(os.path.dirname(STATE_FILE), exist_ok=True)
    with open(STATE_FILE, "w") as f:
        json.dump(data, f, indent=2)


# ── Verifier ──────────────────────────────────────────────────────────────────

def record_entries(changes, assets, state):
    """Add pending verification records for newly changed signals."""
    today = date.today().isoformat()
    due = (date.today() + timedelta(days=VERIFY_DAYS)).isoformat()
    pending = state.get("pending", [])
    for sym, old_signal in changes.items():
        new_signal = state.get("signals", {}).get(sym)  # will be set in main before save
        price = float(assets[sym]["close"].iloc[-1])
        pending.append({
            "sym": sym,
            "signal": new_signal,
            "date": today,
            "price": price,
            "due": due,
        })
    state["pending"] = pending


def run_verifications(assets, state):
    """Check pending signals that are past their due date. Notify and remove."""
    today = date.today().isoformat()
    pending = state.get("pending", [])
    still_pending = []
    verdicts = []

    for entry in pending:
        if entry["due"] > today:
            still_pending.append(entry)
            continue

        sym = entry["sym"]
        signal = entry["signal"]
        entry_price = entry["price"]

        if sym not in assets:
            still_pending.append(entry)
            continue

        current_price = float(assets[sym]["close"].iloc[-1])
        ret = (current_price - entry_price) / entry_price

        if signal == 1:    # LONG: good if price rose
            good = ret > 0
            verdict = ("✅" if good else "❌") + f" {ret:+.1%}"
        elif signal == -1:  # SHORT: good if price fell
            good = ret < 0
            verdict = ("✅" if good else "❌") + f" {ret:+.1%} (short)"
        else:               # FLAT: just report what happened
            verdict = f"⚪ sat out {ret:+.1%}"

        verdicts.append(
            f"{sym} {LABELS[signal]} @ {entry_price:,.2f} → {current_price:,.2f}  {verdict}"
            f"  ({entry['date']} +{VERIFY_DAYS}d)"
        )

    state["pending"] = still_pending

    if verdicts:
        msg = f"📋 Signal Verdict (+{VERIFY_DAYS}d)\n" + "\n".join(verdicts)
        print(msg)
        notify(msg)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    api_key = os.environ.get("ALPHA_VANTAGE_API_KEY")
    today = date.today().isoformat()
    repo = find_repo()
    print(f"Repo: {repo}, Date: {today}")

    print("Refreshing data...")
    assets = refresh_all(api_key)

    print("Loading best strategy...")
    strategy_fn, commit, score, sharpe = load_best_strategy(repo)
    print(f"  Commit: {commit[:8]}, Score: {score:.4f}, Sharpe: {sharpe:.4f}")

    current = {}
    for sym, df in assets.items():
        sig = strategy_fn(df)
        current[sym] = int(sig.iloc[-1])

    state = load_state()
    prev = state.get("signals", {})
    changes = {sym: prev.get(sym) for sym in ASSETS if prev.get(sym) != current[sym]}

    # Check past signals before updating state
    run_verifications(assets, state)

    if changes:
        # Update signals in state first so record_entries can read the new values
        state["signals"] = current
        record_entries(changes, assets, state)

        lines = ["⚡ Signal Change"]
        for sym in ASSETS:
            if sym in changes:
                old = changes[sym]
                old_label = LABELS.get(old, f"({old})") if old is not None else "—"
                lines.append(f"{sym}:  {old_label} → {LABELS[current[sym]]}")
            else:
                lines.append(f"{sym}:  {LABELS[current[sym]]} (unchanged)")
        lines.append(f"Strategy: commit {commit[:7]} | Score: {score:.3f}")
        alert = "\n".join(lines)
        print(alert)
        notify(alert)

    if state.get("daily_sent") != today:
        lines = [f"📊 Daily Signals — {today}"]
        for sym in ASSETS:
            lines.append(f"{sym}:  {LABELS[current[sym]]}")
        lines.append(f"Strategy: score {score:.3f} | Sharpe {sharpe:.2f}")
        summary = "\n".join(lines)
        print(summary)
        notify(summary)

    state.update({"date": today, "signals": current, "commit": commit, "daily_sent": today})
    save_state(state)


if __name__ == "__main__":
    main()
