#!/usr/bin/env python3
"""NAKAMURA LAB v4.2.1 — acquire real OHLC history; never interpolate unknown prices."""
import datetime as dt
import json
import os
from pathlib import Path
from urllib.request import Request, urlopen

DEST = Path(os.environ.get("NAKAMURA_DATA_FILE", "data/background.json"))
BASE = os.environ.get("NAKAMURA_API_BASE", "https://biquote.io").rstrip("/")
NOW = dt.datetime.now(dt.timezone.utc)


def fetch_json(path):
    req = Request(BASE + path, headers={"User-Agent": "NAKAMURA-LAB/4.2.1", "Accept": "application/json"})
    with urlopen(req, timeout=25) as response:
        return json.load(response)


def parse_utc(value):
    try:
        x = dt.datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        return x.astimezone(dt.timezone.utc) if x.tzinfo else None
    except (ValueError, TypeError, OverflowError):
        return None


def normalize_bars(data, interval):
    if str(data.get("symbol", "")).upper() != "USDJPY" or not isinstance(data.get("bars"), list):
        raise ValueError(f"Invalid {interval} OHLC response")
    out = {}
    step = 60 if interval == "1m" else 3600
    for b in data["bars"]:
        if not isinstance(b, dict) or b.get("isOpen") is not False:
            continue
        t = parse_utc(b.get("openTime"))
        if t is None or t.timestamp() % step != 0 or t + dt.timedelta(seconds=step) > NOW:
            continue
        try:
            prices = {name: float(b[name]) for name in ("open", "high", "low", "close")}
        except (KeyError, TypeError, ValueError):
            continue
        if not all(50 < n < 300 for n in prices.values()):
            continue
        if prices["low"] > min(prices["open"], prices["close"]) or prices["high"] < max(prices["open"], prices["close"]):
            continue
        if prices["high"] < prices["low"]:
            continue
        key = t.isoformat(timespec="seconds").replace("+00:00", "Z")
        out[key] = {"openTime": key, **prices, "tickVolume": int(b.get("tickVolume") or 0)}
    return out


def merge(previous, incoming, keep):
    out = {}
    for row in previous:
        if isinstance(row, dict) and parse_utc(row.get("openTime")):
            out[row["openTime"]] = row
    out.update(incoming)
    return [out[k] for k in sorted(out)[-keep:]]


def stats(bars, step):
    if not bars:
        return {"count": 0, "missingBetweenBars": 0, "largestGapMinutes": None, "lastClosedAt": None}
    times = [parse_utc(b["openTime"]) for b in bars]
    diffs = [int((b - a).total_seconds()) for a, b in zip(times, times[1:])]
    # Market closure also generates gaps; a gap is not automatically a collector failure.
    return {"count": len(times), "missingBetweenBars": sum(max(0, n // step - 1) for n in diffs),
            "largestGapMinutes": round(max(diffs, default=step) / 60, 1),
            "lastClosedAt": bars[-1]["openTime"]}


def main():
    old = {}
    if DEST.exists():
        old = json.loads(DEST.read_text(encoding="utf-8"))
    bars_out = dict(old.get("bars") or {})
    errors = []
    success = 0
    for interval, keep, limit in (("1m", 1440, 300), ("1h", 336, 168)):
        try:
            data = fetch_json(f"/api/USDJPY/ohlc?interval={interval}&limit={limit}")
            got = normalize_bars(data, interval)
            if not got:
                raise ValueError("No valid closed candles")
            bars_out[interval] = merge(bars_out.get(interval, []), got, keep)
            success += 1
            print(f"{interval}: fetched={len(got)}, archived={len(bars_out[interval])}")
        except Exception as exc:
            errors.append(f"{interval}: {type(exc).__name__}: {exc}")
    if success == 0:
        raise RuntimeError("No historical OHLC updated; old archive unchanged. " + "; ".join(errors))
    snapshots = list(old.get("samples") or [])
    try:
        tick = fetch_json("/api/USDJPY?allowStale=true")
        quote_at = parse_utc(tick.get("timestamp"))
        mid = float(tick["mid"])
        if quote_at and 50 < mid < 300:
            stamp = NOW.isoformat(timespec="seconds")
            snapshots.append({"capturedAt": stamp, "quoteAt": tick["timestamp"], "mid": mid,
                              "bid": tick.get("bid"), "ask": tick.get("ask"), "marketState": tick.get("marketState"),
                              "stale": bool(tick.get("stale"))})
    except Exception as exc:
        errors.append(f"tick: {type(exc).__name__}: {exc}")
    snapshots = sorted({x["capturedAt"]: x for x in snapshots if isinstance(x, dict) and x.get("capturedAt")}.values(), key=lambda x: x["capturedAt"])[-2016:]
    payload = {"version": "4.2.1", "updatedAt": NOW.isoformat(timespec="seconds"),
               "status": "partial" if errors else "ok", "errors": errors,
               "source": "biquote OHLC (confirmed candles) + quote snapshots",
               "disclaimer": "Rolling OHLC is not 15-second tick data. Missing bars are not interpolated. Market closures may create gaps.",
               "samples": snapshots, "bars": bars_out,
               "quality": {"1m": stats(bars_out.get("1m", []), 60), "1h": stats(bars_out.get("1h", []), 3600)}}
    DEST.parent.mkdir(parents=True, exist_ok=True)
    DEST.write_text(json.dumps(payload, ensure_ascii=False, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    print(f"Archive saved; errors={errors}")


if __name__ == "__main__":
    main()
