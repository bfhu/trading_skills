---
name: equity-watchlist-table
description: Build a consolidated stock analysis table that combines live brokerage data (price, 52-week range, P/E, fundamentals), technical indicators (RSI, MACD), and analyst data (consensus rating, price target) into one table. Use this whenever the user wants a screened list or watchlist of stocks with mixed metrics — e.g. "show me S&P 500 stocks near their 52-week low with their P/E and analyst targets", "build a table of these tickers with RSI and price targets", "which stocks are oversold and what do analysts think", "find the next Mag 7 / next trillion-dollar stock", or any request that asks for a single table mixing market data, valuation, technicals, and analyst opinion. Trigger this even when the user only asks for a subset of those columns, because the value of the skill is knowing which source each column must come from and how to keep them consistent.
---

# Equity Watchlist Table

Build a single table for a set of stocks that combines data living in three different
places: the brokerage MCP connectors, computed technical indicators, and web analyst data.
The whole point of this skill is that **no single source has everything**, and naively
mixing sources produces inconsistent, sometimes fabricated-looking results. This skill
encodes which source owns which column and how to keep them clean.

## The source map (most important part)

Each column has exactly one correct source. Do not guess a value from training data — every
number must be pulled live, because prices, ratios, and targets all go stale.

| Column | Source | How |
|--------|--------|-----|
| Last price | Robinhood or IBKR MCP | `get_equity_fundamentals` (RH) or `get_price_snapshot` (IBKR) |
| 52-week high / low | Robinhood MCP | `get_equity_fundamentals` → `high_52_weeks`, `low_52_weeks` |
| P/E, market cap, shares | Robinhood MCP | `get_equity_fundamentals` |
| Company name, sector, industry | Robinhood MCP | `get_equity_fundamentals` → `description`, `sector`, `industry` |
| Forward P/E | Yahoo Finance | `yfinance` `Ticker(sym).info["forwardPE"]` — **not in Robinhood fundamentals** (see "Forward P/E" below) |
| 14-day RSI | Robinhood MCP | `get_equity_technical_indicators`, `type: "rsi"`, `interval: "day"`, `output: "latest"` |
| MACD (12/26/9), daily + weekly | Robinhood MCP | `get_equity_technical_indicators`, `type: "macd"`, `interval: "day"` and `"week"`, `output: "latest"` |
| Analyst rating (Buy/Hold/Sell counts) | Robinhood MCP | `get_equity_analyst_ratings` → `num_buy_ratings`, `num_hold_ratings`, `num_sell_ratings` |
| Price target (mean / low / high) + as-of date | Robinhood MCP | `get_equity_analyst_ratings` → `mean_price_target`, `low_price_target`, `high_price_target`, `updated_at` |
| TTM revenue growth (YoY) | web search | **not in any broker MCP** — see "Revenue growth" below |

The hard rules that come out of this map:

1. **Analyst ratings and price targets ARE available through Robinhood MCP** via
   `get_equity_analyst_ratings` (up to 75 symbols per call, one call for the whole list).
   Use it as the single source for every row. Fall back to the web (see "Analyst data") only
   for a symbol whose `ratings` comes back null, and label those rows with the web source.
2. **RSI and MACD are both native** to `get_equity_technical_indicators` (max 10 symbols per
   call). Don't compute them by hand unless that tool errors; `scripts/compute_macd.py` is
   the fallback. The Robinhood scanner (`FILTER_TYPE_RSI`) is still the right tool for
   *discovering* oversold/overbought names market-wide (Step 1), not for reading RSI on a
   known list.

## Workflow

### Step 1 — Establish the candidate list

If the user gave you explicit tickers, use them. If they asked for a *screen* ("S&P 500
stocks near their 52-week low", "oversold large caps"), you need to discover the candidates:

- For a "near 52-week low" type screen, the cleanest path is a web search for a current
  published list (e.g. a Trefis / Barchart / Finviz "S&P 500 stocks at 52-week low" page),
  then **verify every candidate** with live fundamentals — published lists are a starting
  seed, not ground truth.
- For a "near 52-week high" screen, do the mirror image: web-search a current "S&P 500 stocks
  at 52-week high" list (Trefis / Barchart / Finviz all publish a highs page alongside the
  lows page), then verify each with live fundamentals. See "Near-high mode" below for the
  column sign-flips.
- For RSI / oversold screens, use the Robinhood scanner directly (`create_scan` with
  `FILTER_TYPE_RSI` and a `PREDICATE_LESS_THAN` threshold like 30). The scanner runs against
  the whole market and returns live RSI. For overbought / near-high momentum screens, flip to
  `PREDICATE_GREATER_THAN` with a threshold like 70.
- Reality-check the count. "Near a 52-week low" rarely yields 20 names *exactly at* the low
  (and the same is true near the high). Decide with the user whether "near" means a band (e.g.
  within 10% of the extreme) and sort by distance-from-extreme so the tightest matches sit at
  the top. Be explicit that names toward the bottom of a fixed-length list may be well off the
  extreme.

### Step 2 — Pull fundamentals (price, 52wk, P/E, name, industry)

Call `get_equity_fundamentals` in batches (max 10 symbols per call). This single call gives
you last price, `high_52_weeks` / `low_52_weeks`, `pe_ratio`, `market_cap`, `description`,
`sector`, and `industry`. Compute distance-from-low as `(last - low_52_weeks) / low_52_weeks`.

Round every displayed number sensibly (2 decimals for prices, 1 for P/E and percentages).

### Step 3 — Get RSI

Call `get_equity_technical_indicators` with `type: "rsi"`, `interval: "day"`, `output:
"latest"`, and a `start_time` ~5 months back (enough warm-up for 14 periods). Batches of 10
symbols. RSI is 14-period daily.

### Step 4 — Get MACD, daily and weekly

Call `get_equity_technical_indicators` with `type: "macd"` (defaults 12/26/9) and `output:
"latest"`, twice per batch:

- **Daily**: `interval: "day"`, `start_time` ≥ 9 months back. Short-term momentum.
- **Weekly**: `interval: "week"`, `start_time` ≥ 3 years back (26-week EMA + 9-week signal
  need ~150 bars to settle). Long-term trend; the right one for multi-month/multi-year
  holds. The latest weekly bar is the last *completed* week — state its week-start date.

Each returns `macd`, `signal`, `histogram`. Report the histogram (MACD − signal) for both:
positive = momentum improving, negative = fading. The histogram is in dollars, so compare
**signs and direction across tickers, not magnitudes**. If a user asks for a non-standard
setting (e.g. "20-week MACD"), explain that 12/26/9 on daily and weekly bars is the
convention and use it unless they confirm custom periods.

Fallback if the tool errors: pull OHLCV via `get_equity_historicals` and run
`scripts/compute_macd.py`.

### Step 5 — Get analyst rating and target (Robinhood), TTM revenue growth (web)

Call `get_equity_analyst_ratings` once with the whole list. Derive the rating label from the
counts so every row uses the same rule:

- Buy share = buy / (buy + hold + sell)
- **Strong Buy** if Buy share ≥ 80%; **Buy** if ≥ 60%; otherwise **Hold** if
  (buy + 0.5 × hold) / total ≥ 40%; else **Sell**.
- Show the raw counts next to the label, e.g. `Strong Buy (34/1/0)`.

Use `mean_price_target` as the target and `updated_at` (date only) as its as-of date; write
`n/a` when `updated_at` is missing. TTM revenue growth stays web-sourced — see "Revenue
growth" below.

### Step 5b — Forward P/E

See "Forward P/E" below. Pull it in the same pass as any other Yahoo data; one source for
every row.

### Step 6 — Assemble and caveat

ALWAYS output all 18 columns in this exact order (identity → price/valuation → technicals →
analyst), even if the user only asked for a subset — the full set is the canonical format:

1. Ticker
2. Company name — from fundamentals
3. Industry — from fundamentals
4. Last price — live
5. 52-week low — from fundamentals
6. 52-week high — from fundamentals
7. % above 52-week low — computed: `(last - low_52_weeks) / low_52_weeks`
8. P/E (ttm) — from fundamentals; `n/m` when negative
9. Forward P/E — from Yahoo (see "Forward P/E")
10. 14-day RSI — `get_equity_technical_indicators`
11. MACD daily — histogram, 12/26/9
12. MACD weekly — histogram, 12/26/9, last completed week
13. Analyst rating — label + Buy/Hold/Sell counts, from `get_equity_analyst_ratings`
14. Price target — mean, from `get_equity_analyst_ratings`
15. Implied upside vs. last — computed: `(target - last) / last`
16. Target as-of — `updated_at` date from `get_equity_analyst_ratings`
17. TTM revenue growth (YoY) — single-sourced from the web. This TTM period's revenue vs. the
    year-ago TTM period. See "Revenue growth" below — it is web-sourced, not broker-native.
18. Screen score — only in "Next Mag 7 screen mode"; omit the column otherwise.

Sort by column 7 (% above 52-week low) ascending by default so the tightest matches to a
"near the low" screen sit at the top, unless the user asked for a different sort. Then add
the standard caveats (see "Caveats").

## Analyst data — keep it single-sourced

The biggest failure mode in this whole workflow is analyst data, because every aggregator
reports slightly different consensus numbers (different analyst panels, different update
dates). If you pull CME from one site and ICE from another, the table looks authoritative but
is silently inconsistent.

**Default source: Robinhood `get_equity_analyst_ratings`** for every row (see Step 5). The
rules below apply to the web fallback, used only for symbols where Robinhood returns null
ratings — and when used, mark those rows with the web source name.

Rules:

- **Pick ONE aggregator and use it for every fallback row.** `stockanalysis.com` is a good default
  because it cites S&P Global Market Intelligence + TipRanks and exposes the numbers as plain
  text in search snippets. Others that surface numbers cleanly: TipRanks, Investing.com,
  Public.com, ChartMill, Benzinga.
- **Yahoo Finance is a poor fetch target here** even though it appears in results: its analyst
  ratings/targets are rendered by JavaScript, so a fetch of the raw HTML usually returns the
  surrounding prose but not the numbers. Don't rely on it.
- **`yfinance` reachability depends on the environment** — in some sandboxes Yahoo's API hosts
  aren't on the network allowlist and calls fail to connect; in others (e.g. a Claude Code
  cloud session with open network) it works. Test with one symbol first. Even when it works,
  don't use it for analyst data — it's a scrape and not more accurate than Robinhood.
- **Always note the "as of" date** of the consensus. Targets are slow-moving and frequently
  stale right after an earnings miss — a huge implied upside on a falling stock usually means
  the targets simply haven't been revised down yet, not a guaranteed rebound.
- If two sources disagree materially on a name, show a range and flag it rather than picking
  one silently.

## Revenue growth — column 17

Use **TTM revenue growth, year-over-year**: the trailing-twelve-month revenue for the most
recent four quarters vs. the TTM revenue for the four quarters a year earlier. This is the
right metric because it neutralizes seasonality (your list mixes seasonal retail/apparel with
non-seasonal exchanges and software, so a single-quarter or QoQ number would compare apples to
oranges) and it captures current top-line momentum better than a stale annual figure — exactly
the "is this near-low name recovering or still sliding" question a near-low screen asks.

Sourcing:

- **Not broker-native.** Neither Robinhood nor IBKR MCP returns revenue (Robinhood's
  `get_earnings_results` carries EPS only, not revenue). So this column is web-sourced.
- **Same single-source discipline as analyst data.** Pull the already-computed "TTM revenue
  growth" that aggregators publish (stockanalysis.com / TIKR / Zacks expose it directly) rather
  than reconstructing it from five quarters of raw revenue — reconstruction rarely comes
  through cleanly in a snippet. Anchor every row to the **same** aggregator you'd otherwise use,
  and note the "as of" date.
- If only a most-recent-quarter YoY figure is available for a given name, use it but label it
  as quarterly YoY (not TTM) so the column isn't silently mixing definitions.

**Value-trap caveat (always include for this column).** A high TTM growth figure can be
carrying the weight of one unusually strong quarter that is about to roll out of the trailing
window — the stock can look like it has strong momentum right before the number drops. When a
name's TTM growth looks anomalously high relative to its sector or its own history, flag it
rather than presenting it at face value.


## Near-high mode (52-week high screen)

The near-high table uses the **same 17 columns** as the near-low table — only the screen
direction and a few column interpretations flip. Keep the column set and order identical so
the two tables are directly comparable.

What changes:

- **Screen direction.** Find candidates at/near the 52-week *high* (web list of "stocks at
  52-week high", or scanner with RSI > 70 for overbought momentum).
- **Column 7 becomes "% below 52-week high"**, computed `(high_52_weeks - last) / high_52_weeks`.
  Keep the same column position; just relabel and flip the formula. Sort ascending so names
  closest to the high sit at the top.
- **Implied upside (col 15) is often negative or small.** Names at their highs frequently sit
  at or above the average analyst target, so implied upside can be negative — that's expected,
  not an error. Present it as-is.

What stays the same: all sourcing rules, the single-source discipline for analyst + revenue
columns, MACD computation, and rounding.

Interpretation flips worth noting to the user: near a high, a high RSI signals overbought
momentum (not the oversold capitulation of the low screen), and a stock above its analyst
target may be priced for more than the consensus expects. The TTM-revenue-growth value-trap
caveat still applies and is arguably more relevant here, since high-flying names are more
likely to be riding a strong recent quarter.


## Forward P/E — column 9

Robinhood's `get_equity_fundamentals` returns trailing `pe_ratio` only, and IBKR's snapshot
has no valuation fields, so forward P/E comes from Yahoo: `yfinance.Ticker(sym).info
["forwardPE"]` (price ÷ consensus next-fiscal-year EPS). Pull it for every row from Yahoo —
never mix in a web aggregator's forward P/E for some rows. If Yahoo is unreachable (see the
`yfinance` note in "Analyst data"), web-search one aggregator for all rows and label the
column with that source. Show `n/m` when forward EPS is negative or missing.


## Next Mag 7 screen mode

Use this mode when the user asks to find "the next Mag 7", "the next trillion-dollar
company", or large caps with mega-cap-in-the-making traits. It replaces Step 1 with a
quantitative screen, then runs Steps 2–6 on the top 25 and adds the screen score as
column 18. Sort by screen score descending (not by % above the 52-week low).

### Universe

Start from ~110 US-listed large caps (S&P 500 / Nasdaq-100 leaders plus large ADRs such as
TSM, ASML, ARM, SAP, NVO). **Exclude the current Mag 7** (AAPL, MSFT, GOOGL/GOOG, AMZN, NVDA,
META, TSLA). Keep names with market cap ≥ $100B. The list lives in `UNIVERSE` in
`src/trading_skills/next_mag7.py` (override per run with `--symbols`), and tell the user the
universe is hand-picked, so a fast riser outside it won't appear.

### Score

Run from the repo root:

```bash
uv run python .claude/skills/equity-watchlist-table/scripts/next_mag7_screen.py --top 25
```

Options: `--symbols` (comma-separated universe override), `--min-mcap-b` (default 100),
`--out-dir` (default `sandbox/`). It prints JSON and writes
`sandbox/next_mag7_screen_<YYYY-MM-DD_HHmm>.csv/.json`. It pulls fundamentals and 3-year prices from Yahoo, then scores each
name as a weighted sum of robust z-scores (median/MAD, winsorized at the 5th/95th
percentile, missing values set to the 25th percentile so gaps are penalized, not dropped):

| Trait | Metric | Weight |
|---|---|---|
| Growth at scale | 3-year revenue CAGR | 20% |
| Growth now | Latest revenue growth YoY | 10% |
| Economics | Operating margin | 10% |
| Operating leverage | Change in operating margin over ~3 fiscal years | 10% |
| Capital efficiency | ROIC ≈ EBIT × (1 − tax) ÷ (equity + debt − cash) | 15% |
| Cash generation | Free-cash-flow margin | 15% |
| Reinvestment | R&D ÷ revenue | 5% |
| Leadership | 1-year return minus QQQ | 7.5% |
| Leadership | 3-year return minus QQQ | 7.5% |

The script also outputs EV/Sales and EV/Sales per point of revenue CAGR as a valuation
check; it doesn't feed the score.

### Prices and cross-check

Take live prices for the top 25 from Robinhood
(`get_equity_quotes`, ≤ 20 symbols per call) and verify at least the top 5 on IBKR
(`search_contracts` → `get_price_snapshot`). Flag any gap > 0.5%.

### Interpreting the list for the user

Group the top 25 instead of presenting a flat ranking:

- **Already Mag 7 size** (market cap ≥ $1T): these are the "Mag 10" add-ons, not the next ones.
- **Closest to the original profile at mid size**: high growth at scale, 40%+ operating
  margins, strong free cash flow, and a platform moat.
- **Fast growers not yet profitable on an operating basis**: what the platform names looked
  like early on.
- **Cyclical**: memory, semiconductor equipment and power-build-out names that score well on
  current numbers but aren't platforms. Flag a name whose YoY revenue growth is several
  times its 3-year CAGR as cycle-driven.
- **Slower compounders**: excellent margins but lagging QQQ.

### Screen-specific caveats

- ROIC is noisy for cash-heavy companies (it explodes as invested capital nears zero) and
  for ones with tiny or negative equity. Winsorizing limits the effect on the score, but
  don't present the raw ROIC as accurate.
- Watch for Yahoo currency mismatches on foreign ADRs (e.g. an EV/Sales in the hundreds or
  thousands). Flag and ignore them.
- Annual fundamentals can be up to 12 months old.
- Nobody can predict which company becomes the next Mag 7. The screen produces a shortlist
  for research, not a forecast.


## Caveats to include with every table

- State that prices/RSI are live (give the close date) and analyst + revenue-growth data are
  "as of" their date.
- Note that this is information, not a recommendation — a stock near a 52-week low can be a
  value entry or a falling knife.
- If the list was padded to a fixed length, say that names toward the bottom are progressively
  further from the screen criterion.
- Flag any name whose headline consensus lags recent individual analyst actions.
- Flag any name whose TTM revenue growth looks anomalously high (possible value trap — a strong
  quarter about to roll out of the trailing window).
- Flag stale price targets: any `updated_at` more than ~6 weeks old, or missing. A big implied
  upside on a stale target usually means analysts haven't revised yet.
- Say that MACD histograms are in dollars: compare signs across tickers, not sizes. Give the
  week-start date of the weekly MACD bar.
- Name the source of forward P/E (Yahoo or the fallback aggregator).

## Notes on tool discovery

The broker tools are deferred — call `tool_search` (e.g. "stock fundamentals scanner",
"price history", "analyst ratings", "technical indicators") to load them before use, and don't assume parameter names. The
Robinhood scanner filter vocabulary isn't directly enumerable; filter type names follow the
`FILTER_TYPE_*` pattern and are discovered by trial (`FILTER_TYPE_RSI` is confirmed working).
