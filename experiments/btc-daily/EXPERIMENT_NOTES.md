# BTC Daily v1 — Notatka z eksperymentu

Data: 2026-03-19
Czas trwania: ~45 min (11:30 → 12:13)
Eksperymenty: 80
Best score: **1.4155** (#70, #73-76)

## Dane

- **Asset:** BTC/USDT daily (ccxt Binance, 1H → resample to daily)
- **Zakres danych:** 2021-06-01 → 2026-03-19 (1753 dni total)
- **Cena BTC:** $36,693 (start) → $70,442 (koniec)
- **Train:** 2022-01-01 → 2025-06-30 (1277 dni)
- **Val:** 2025-07-01 → 2026-03-19 (262 dni)
- **On-chain (bitcoin-data.com, Tier 1, 8 metryk):** MVRV (5191 pkt), MVRV_STH (4824), MVRV_LTH (5532), SOPR_STH (5692), exchange_netflow (5099), NUPL (4824), fear_greed (2932), active_addresses (6275)
- **Macro (FRED, 7 serii):** WALCL (271 pkt, weekly), DFF (1902, daily), T10Y2Y (1301), VIXCLS (1335), DGS10 (1300), BAMLH0A0HYM2 (1362), DTWEXBGS (1298)
- **Funding rate:** Binance Futures, daily avg (1904 dni)
- **FOMC calendar:** 34 dni FOMC w zakresie danych (hardcoded 2022-2026)
- **Features:** ~40 (price TA + on-chain z 5d change + FRED z 5d change + funding rate + FOMC proximity) — rolling z-score normalizacja

## Architektura

- **Model:** LSTM (PyTorch GPU), 2 warstwy, hidden=128, BatchNorm + GELU + Dropout
- **Lookback:** 30 dni (najlepszy wynik, testowane: 20, 25, 30, 35, 45, 60)
- **Target:** 5-day forward return (testowane: 3d, 7d, 10d — gorsze)
- **Training:** AdamW, lr=0.0005 (sweet spot), weight_decay=0.05, CosineAnnealing, patience=30, 300 epok
- **Risk management:** ATR(14) SL=1.5x, TP=4.5x (R:R 1:3)
- **Signal:** LSTM confidence > threshold → long/short, ATR trailing stop
- **Scoring:** 0.25*sharpe + 0.15*sortino + 0.15*(1+max_dd) + 0.10*return + 0.05*win_rate + 0.15*avg_rr_norm + 0.15*pf_norm × trade_penalty(min 15) × consistency

## Best strategy (#70: score 1.4155)

- Val: **+42.0% return**, **-8.17% max DD**, 16 trades, **R:R 2.99**, **PF 3.85**
- Train: ~+800% (sharpe 2.3) — masywny overfitting
- Konfiguracja: LSTM lb30, dropout=0.4, wd=0.05, lr=0.0005, VIX<30 filter

## Co zadziałało

1. **Niższy learning rate (0.0005)** — skok z 0.44 na 0.78 (#24). LR 0.001-0.002 = za wysoki dla daily data.
2. **Weight decay 0.05** — skok z 0.78 na 1.35 (#30). Regularyzacja kluczowa.
3. **Dropout 0.4** — skok z 1.35 na 1.40 (#34). Wyższy dropout = mniej zapamiętywania.
4. **Lookback 30** — optymalny. 20 za mało kontekstu, 45-60 za dużo szumu.
5. **FOMC filter** — poprawa z 0.37 na 0.44 (#17). Model lepiej radzi sobie z FOMC-awareness.
6. **VIX < 30 filter** — drobna poprawa z 1.41 na 1.42 (#70). Unikanie ekstremalnej zmienności.
7. **Confidence threshold 0.01** — niski próg = więcej trade'ów = lepszy trade_penalty.
8. **ATR 1.5x/4.5x SL/TP** — domyślny R:R 1:3 działa dobrze.

## Co NIE zadziałało

1. **Większy LSTM (hidden=256)** — -0.03 score, overfitting (#12)
2. **Mniejszy LSTM (hidden=64, 1 layer)** — -0.03 score, underfitting (#13)
3. **3 warstwy LSTM** — prawie 0 trade'ów (#40)
4. **Forward 3d/7d target** — 0 trade'ów (#42, #43). 5d = sweet spot.
5. **Lookback 20** — 0 trade'ów (#18). Za mało kontekstu.
6. **Lookback 45, 60** — gorsze (#20, baseline). Za dużo szumu.
7. **LR 0.002-0.007** — albo 0 trade'ów albo negatywny score (#23, #26)
8. **LR 0.0003** — gorszy niż 0.0005 (#25)
9. **Batch size 128** — 0 trade'ów (#38)
10. **Patience 50** — 1 trade, overfitting (#44)
11. **Ensemble 3 seeds** — gorszy niż single seed (#57). Na daily data ensemble averaging rozmywa sygnały.
12. **Multi-horizon (3d+5d+10d)** — nie pomógł (#9)
13. **Szersze stopy ATR 2x/6x** — za mało trade'ów (#10)
14. **Dodatkowe filtry (MVRV, funding, F&G, NUPL, exchange netflow, USD index)** — nie zmieniają wyniku (#14-16, #50-51, #54, #66, #74-76). Model sam wyciąga te sygnały z features.

## Plateau i overfitting

- **Score plateau od exp #34 (1.40) do #80 (1.42)** — 46 eksperymentów bez znaczącej poprawy
- **Masywny overfitting:** train +800-950% vs val +42%. Consistency penalty łagodzi ale nie rozwiązuje.
- Equity chart: train 1→9x, val 1→1.4x. Krzywe train piękne, val płaskie z kilkoma skokami.
- Wszystkie filtry (MVRV, funding, NUPL, VIX, yield curve, exchange flow, USD) generują identyczne trade'y — model już odkrył optymalne 16 wejść i żaden filtr nie zmienia decyzji.

## Diagnoza: dlaczego plateau

1. **Za dużo features (~40) na ~1200 dni** — LSTM łatwo zapamiętuje wzorce zamiast uogólniać
2. **Fixed train/val split** — model optymalizuje pod konkretne 262 dni val, nie pod ogólne warunki rynkowe
3. **80/20 wewnętrzny split w strategy.py** — train LSTM na 80% train danych, ale val LSTM predykcje lecą na pełnym zbiorze (w tym na train)
4. **16 trade'ów na val** — za mało do statystycznej pewności. Jeden trade więcej/mniej zmienia score o 0.1-0.3

## Plany na v2 — walka z overfittingiem

### Krytyczne zmiany (prepare.py):
1. **Walk-forward validation** — rolling window: trenuj na 365 dni, predykcja na 30 dni, przesuń o 30 dni. Eliminuje fixed-split bias.
2. **Feature selection** — max 15 features. Usunąć redundantne (np. MVRV + MVRV_STH + MVRV_LTH to 3 kolumny o tej samej informacji). Korelacja z target < 0.05 → wyrzuć.
3. **Dłuższy train period** — TRAIN_START = 2020-01 zamiast 2022-01. Więcej danych = trudniej zapamiętać.
4. **Osobny val hold-out** — train 2020-2024, val 2024-2025, holdout 2025-2026. Scoring na val, holdout do weryfikacji końcowej.

### Zmiany modelu (strategy.py):
5. **Mniejszy LSTM** — hidden=64, 1 warstwa. Mniej parametrów = trudniej overfitować.
6. **Noise injection** — Gaussian noise na features podczas treningu. Wymusza robustność.
7. **Max 10-12 features** — price returns (1d, 5d, 10d), RSI, MACD, ATR, MVRV (1 zbiorcze), funding rate, FOMC proximity, VIX.
8. **Label smoothing** — target = tanh(fwd_ret * k) zamiast surowego return. Zmniejsza wpływ outlierów.

### Sugestie dla agenta:
9. **Nie powtarzaj filtrów** — MVRV/funding/NUPL/F&G/netflow filtry nie działają (exp #14-16, #50-51, #66, #74-76). Model sam wyciąga te informacje z features.
10. **Nie testuj seedów** — zmiana seed nie poprawia score na 1 assecie (exp #19, #46, #53, #65, #78-79).
11. **Focus na architekturę i train procedure**, nie na parametry.

## Kluczowe liczby do zapamiętania

| Metryka | Wartość |
|---------|---------|
| Best score | 1.4155 |
| Val return | +42.0% |
| Val max DD | -8.17% |
| Val trades | 16 |
| Val R:R | 2.99 |
| Val PF | 3.85 |
| Val Sharpe | 2.17 |
| Train Sharpe | 2.30 |
| Overfitting ratio | train 9x vs val 1.4x |
| Sweet spot LR | 0.0005 |
| Sweet spot lookback | 30 days |
| Sweet spot target | 5-day forward return |
| Sweet spot dropout | 0.4 |
| Sweet spot weight_decay | 0.05 |
