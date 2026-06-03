
import json
from pathlib import Path
from datetime import datetime

import pandas as pd

from components.benchmark_data import get_benchmark_data


def _parse_txn_dt(ts: str):
	if not ts:
		return None
	try:
		return datetime.fromisoformat(ts.replace("+0000", "+00:00")).replace(tzinfo=None)
	except Exception:
		return None


def main() -> int:
	cache = Path.home() / ".pytr" / "portfolio_cache.json"
	if not cache.exists():
		print(f"Missing cache file: {cache}")
		return 2

	data = json.loads(cache.read_text(encoding="utf-8")).get("data", {})
	transactions = data.get("transactions", [])
	history = data.get("history", [])

	print("transactions:", len(transactions))
	print("history:", len(history))

	BUY_SUBTITLES = {"Kauforder", "Sparplan ausgeführt", "Limit-Buy-Order", "Bonusaktien", "Tausch"}
	SELL_SUBTITLES = {"Verkaufsorder", "Limit-Sell-Order", "Stop-Sell-Order"}

	inv = []
	for txn in transactions:
		subtitle = txn.get("subtitle", "")
		amount = txn.get("amount", 0)
		dt = _parse_txn_dt(txn.get("timestamp", ""))
		if dt is None:
			continue
		try:
			amount_f = float(amount)
		except Exception:
			continue
		if not amount_f:
			continue

		if subtitle in BUY_SUBTITLES:
			inv.append({"dt": dt, "subtitle": subtitle, "amount": abs(amount_f)})
		elif subtitle in SELL_SUBTITLES:
			inv.append({"dt": dt, "subtitle": subtitle, "amount": -abs(amount_f)})

	inv.sort(key=lambda x: x["dt"])
	print("investment txns (buy/sell):", len(inv))

	if not inv:
		print("No buy/sell-like transactions found in cache")
		return 3

	hist = []
	for h in history:
		try:
			dt = datetime.strptime(h["date"], "%Y-%m-%d")
			inv_f = float(h.get("invested", 0) or 0)
			val_f = float(h.get("value", 0) or 0)
		except Exception:
			continue
		hist.append((dt, inv_f, val_f))

	hist.sort(key=lambda x: x[0])
	if not hist:
		print("No history points found in cache")
		return 4

	start = inv[0]["dt"]
	end = hist[-1][0]

	symbol = "URTH"  # MSCI World in this codebase
	df = get_benchmark_data(symbol, start, end)
	if df is None or len(df) == 0:
		print(f"No benchmark data available for {symbol} between {start:%Y-%m-%d} and {end:%Y-%m-%d}")
		return 5

	prices = df.reset_index()
	prices["Date"] = pd.to_datetime(prices["Date"]).dt.tz_localize(None)

	def price_at(dt: datetime):
		target = pd.Timestamp(dt).normalize()
		valid = prices[prices["Date"] <= target]
		if len(valid) == 0:
			return None
		return float(valid.iloc[-1]["Close"])

	# Efficient history lookup (hist is sorted)
	hist_i = 0

	def portfolio_at(dt: datetime):
		nonlocal hist_i
		while hist_i + 1 < len(hist) and hist[hist_i + 1][0] <= dt:
			hist_i += 1
		return hist[hist_i]

	rows = []
	cum_units = 0.0
	cum_invested = 0.0

	for i, t in enumerate(inv, start=1):
		dt = t["dt"]
		amt = float(t["amount"])

		px = price_at(dt)
		units_delta = 0.0
		if px and px > 0:
			if amt > 0:
				units_delta = amt / px
				cum_units += units_delta
				cum_invested += amt
			else:
				if cum_invested > 0:
					sell_ratio = min(1.0, abs(amt) / cum_invested)
					cum_units *= (1 - sell_ratio)
					cum_invested = max(0.0, cum_invested + amt)

		step_px = price_at(dt)
		msci_value = (cum_units * step_px) if (step_px and cum_units > 0) else cum_invested

		ph_dt, _ph_inv, ph_val = portfolio_at(dt)

		rows.append(
			{
				"step": i,
				"date": dt.strftime("%Y-%m-%d"),
				"subtitle": t["subtitle"],
				"amount_eur": round(amt, 2),
				"urth_close": None if px is None else round(px, 6),
				"units_delta": round(units_delta, 10),
				"units_total": round(cum_units, 10),
				"invested_total": round(cum_invested, 2),
				"msci_value_step": round(msci_value, 2),
				"portfolio_value_nearest": round(ph_val, 2),
				"portfolio_date_used": ph_dt.strftime("%Y-%m-%d"),
			}
		)

	out_dir = Path.home() / ".pytr"
	out_dir.mkdir(parents=True, exist_ok=True)

	out_csv = out_dir / "msci_step_by_step.csv"
	pd.DataFrame(rows).to_csv(out_csv, index=False)

	print("Wrote:", out_csv)

	# Print all rows if reasonable, else head/tail but still keep full CSV.
	max_print = 200
	if len(rows) > max_print:
		print(
			f"Too many steps to print fully ({len(rows)}). Showing first/last 75. Full details in: {out_csv}"
		)
		rows_to_print = (
			rows[:75]
			+ [
				{
					"step": "...",
					"date": "...",
					"amount_eur": "...",
					"urth_close": "...",
					"units_delta": "...",
					"units_total": "...",
					"invested_total": "...",
					"msci_value_step": "...",
					"portfolio_value_nearest": "...",
					"portfolio_date_used": "...",
				}
			]
			+ rows[-75:]
		)
	else:
		rows_to_print = rows

	cols = [
		"step",
		"date",
		"amount_eur",
		"urth_close",
		"units_delta",
		"units_total",
		"invested_total",
		"msci_value_step",
		"portfolio_value_nearest",
		"portfolio_date_used",
	]

	header = " | ".join(f"{c:>22}" for c in cols)
	print(header)
	print("-" * len(header))
	for r in rows_to_print:
		print(" | ".join(f"{str(r.get(c, ''))[:22]:>22}" for c in cols))

	last = rows[-1]
	print("---")
	print("Final MSCI step value:", last["msci_value_step"])
	print(
		"Final portfolio value (nearest):",
		last["portfolio_value_nearest"],
		"on",
		last["portfolio_date_used"],
	)

	return 0


if __name__ == "__main__":
	raise SystemExit(main())
