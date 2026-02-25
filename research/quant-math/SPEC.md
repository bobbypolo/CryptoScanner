# Quant Math Specification

## 30-Day Rolling Pearson Correlation

### Formula
```
r = Cov(X, Y) / (σ_X · σ_Y)
```

### Pandas Implementation
```python
asset_returns.rolling(window=30, min_periods=20).corr(btc_returns)
```

### Key Details
- Both Series must be aligned on the same DatetimeIndex
- First (window - 1) rows will be NaN
- `min_periods=20` allows partial windows (minimum 20 of 30 days)
- Range: [-1.0, 1.0]

---

## Beta Calculation

### Formula
```
β = Cov(R_asset, R_btc) / Var(R_btc)
```

### Pandas Implementation
```python
rolling_cov = asset_returns.rolling(30, min_periods=20).cov(btc_returns)
rolling_var = btc_returns.rolling(30, min_periods=20).var()
rolling_var = rolling_var.replace(0, np.nan)  # Guard: zero variance → NaN
rolling_beta = rolling_cov / rolling_var
```

### Relationship to Correlation
```
β = r · (σ_asset / σ_btc)
```

---

## Verification Test Cases

### Test A: Asset = 2x BTC
```
Cov(2·R_btc, R_btc) = 2 · Var(R_btc)
β = 2 · Var(R_btc) / Var(R_btc) = 2.0
Correlation = 1.0 (perfect positive)
```

### Test B: Asset = -1x BTC
```
Cov(-R_btc, R_btc) = -Var(R_btc)
β = -Var(R_btc) / Var(R_btc) = -1.0
Correlation = -1.0 (perfect negative)
```

### Test C: Insufficient Data (15 points, window=30)
```
With min_periods=20: all NaN (insufficient observations)
With min_periods=10: valid from day 10 onward
```

---

## Edge Cases

| Case | Result | Guard |
|------|--------|-------|
| BTC variance = 0 | NaN | `var.replace(0, np.nan)` |
| Asset variance = 0 | Beta=0, Corr=NaN | Pandas handles correctly |
| Data < min_periods | NaN | `min_periods` parameter |
| NaN gaps in series | Skipped by rolling | Pandas default behavior |

---

## Half-Kelly Criterion

### Formula
```
f* = (b·p - q) / b
f_half = f* / 2
position = min(f_half, max_fraction)
```

### Parameters
- b = avg_win / |avg_loss|
- p = win_count / total_trades
- q = 1 - p

### Guards
- len(returns) < min_trades → 0.0
- f* <= 0 → 0.0 (no edge)
- f_half > max_fraction → cap at max_fraction
- No wins or no losses → 0.0
