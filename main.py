#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
ETF holdings → leaders screener (GitHub / local)

Ensures USER_REQUIRED_ETFS are always in the scan universe
(even if they were omitted from an older ETF_LIST).
"""

import csv
import datetime
import io
import itertools
import sys
import time
import warnings

import requests

warnings.simplefilter(action="ignore", category=FutureWarning)

try:
    from playwright.sync_api import sync_playwright
    import yfinance as yf
    import pandas as pd
except ImportError:
    print("缺少套件，請先安裝必要套件")
    sys.exit(1)

# ---- Must-scan list (your paste; duplicates removed) ----
USER_REQUIRED_ETFS = [
    "AMLP", "BIZD", "BLOK", "DIA", "DRIV", "ESPO", "EUFN", "FDN", "FFTY",
    "FINX", "FXI", "FXY", "GDX", "GLD", "GRID", "HACK", "IAI", "IBB",
    "ICLN", "IDRV", "IEF", "IGV", "IHF", "IHI", "IPAY", "ITB", "IWM",
    "IXP", "IYT", "IYZ", "JETS", "KBWB", "KIE", "KRE", "MOO", "MSOS",
    "OIH", "ONLN", "PAVE", "PBJ", "PEJ", "QQQ", "QQQE", "REM", "RSP",
    "SHY", "SKYY", "SLV", "SMH", "SOXX", "SPXU", "SPY", "SQQQ", "TAN",
    "TLT", "UUP", "VNQ", "VOX", "XAR", "XBI", "XHB", "XHS", "XLB",
    "XLC", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLY", "XME",
    "XOP", "XPH", "XRT", "XSD",
]

# Broader library (kept) + required always merged in
ETF_LIST_BASE = [
    "SPY", "QQQ", "IWM", "DIA", "DXY", "RSP", "QQQE", "SQQQ", "SPXU", "FFTY",
    "SMH", "SOXX", "XSD", "IGV", "PSJ", "SKYY", "CLOU", "FDN", "BUG", "HACK",
    "CIBR", "IBUY", "BOTZ", "ROBO", "ARKK", "SOCL", "FINX", "IPAY", "BLOK", "CNRG",
    "IYZ", "PRNT", "XBI", "IBB", "IHI", "IHF", "XPH", "XLV", "XHE", "ARKG",
    "XLF", "KRE", "KBE", "KIE", "IAI", "XLE", "XOP", "OIH", "XES", "FCG",
    "CRAK", "TAN", "ICLN", "PBW", "XLI", "ITA", "PPA", "IYT", "JETS", "PAVE",
    "XRT", "ITB", "XHB", "XLY", "PEJ", "ESPO", "HERO", "MSOS", "MJ", "BETZ",
    "DRIV", "KARS", "BATT", "XLP", "PBJ", "XLB", "XME", "SLX", "COPX", "MOO",
    "PICK", "WOOD", "URA", "GDX", "GDXJ", "REMX", "SIL", "XLU", "VNQ", "REET",
    "SRVR", "INDS", "TLT", "IEF", "SHY", "BND", "LQD", "HYG", "JNK", "MUB",
    "UUP", "FXE", "FXB", "FXY", "GLD", "SLV", "CORN", "WEAT", "SOYB", "DBA",
    "DBC", "GCC", "UNG", "EWJ", "EWG", "EWU", "EWA", "EWC", "FXI", "GREK",
    # previously missing from scan (required)
    "VOX", "EUFN", "KBWB", "BIZD", "AMLP", "ONLN", "IXP", "XLC", "XHS",
    "GRID", "IDRV", "XAR", "REM", "XLK",
]

ETF_LIST = sorted(set(ETF_LIST_BASE) | set(USER_REQUIRED_ETFS))


def assert_required_covered() -> None:
    missing = sorted(set(USER_REQUIRED_ETFS) - set(ETF_LIST))
    if missing:
        raise RuntimeError(f"Required ETFs not in ETF_LIST: {missing}")
    print(f"Universe: {len(ETF_LIST)} ETFs | required covered: {len(USER_REQUIRED_ETFS)}")
    print("Required:", ", ".join(sorted(USER_REQUIRED_ETFS)))


def get_spy_holdings():
    try:
        url = (
            "https://www.ssga.com/us/en/intermediary/etfs/library-content/"
            "products/fund-data/etfs/us/holdings-daily-us-en-spy.csv"
        )
        res = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=15)
        lines = res.text.splitlines()
        header_idx = next(
            i for i, line in enumerate(lines) if "Ticker" in line or "Identifier" in line
        )
        df = pd.read_csv(io.StringIO("\n".join(lines[header_idx:])))
        return [
            s
            for s in df[df.columns[0]].dropna().tolist()
            if isinstance(s, str) and 1 <= len(s.strip()) <= 5 and s.strip().isalpha()
        ]
    except Exception as e:
        print(f"⚠️ 抓取 SPY 官方 CSV 失敗: {e}")
        return []


def scrape_etf_holdings(page, etf_symbol):
    if etf_symbol == "SPY":
        spy_symbols = get_spy_holdings()
        if spy_symbols:
            return spy_symbols

    url = (
        "https://www.schwab.wallst.com/schwab/Prospect/research/etfs/"
        f"schwabETF/index.asp?type=holdings&symbol={etf_symbol}"
    )
    all_symbols = []
    try:
        page.goto(url, wait_until="load", timeout=60000)
        time.sleep(2)
        try:
            btn = page.locator("a:text-is('60')").first
            if btn.is_visible(timeout=3000):
                btn.click()
                time.sleep(2)
        except Exception:
            pass

        while True:
            try:
                page.wait_for_selector("td", timeout=10000)
            except Exception:
                break

            for row in page.locator("tr").all():
                try:
                    cells = row.locator("td")
                    if cells.count() > 0:
                        txt = cells.first.inner_text().strip()
                        if txt and txt.isupper() and 1 <= len(txt) <= 5:
                            all_symbols.append(txt)
                except Exception:
                    continue

            next_link = page.locator("a:has-text('Next')").filter(has_text="Next").first
            if (
                next_link.count() > 0
                and next_link.is_visible()
                and not next_link.evaluate("el => el.classList.contains('disabled')")
            ):
                next_link.click()
                time.sleep(2)
            else:
                break
    except Exception as e:
        print(f"❌ 抓取 {etf_symbol} 失敗: {e}")
    return list(set(all_symbols))


def analyze_holdings(etf_symbol, symbols):
    if not symbols:
        return []
    cleaned = [s.replace("/", "-").replace(".", "-") for s in symbols]
    results = []
    for i in range(0, len(cleaned), 15):
        batch = cleaned[i : i + 15]
        try:
            data = yf.download(
                batch,
                period="max",
                interval="1d",
                group_by="ticker",
                progress=False,
                threads=True,
            )
            if data is None or data.empty:
                continue
            for symbol in batch:
                try:
                    df = data if len(batch) == 1 else data[symbol]
                    close = df["Close"].dropna()
                    if len(close) < 200:
                        continue
                    price, ath = close.iloc[-1], close.max()
                    ema9 = close.ewm(span=9, adjust=False).mean().iloc[-1]
                    ema50 = close.ewm(span=50, adjust=False).mean().iloc[-1]
                    ema200 = close.ewm(span=200, adjust=False).mean().iloc[-1]
                    if (
                        price > ema200
                        and ema50 > ema200
                        and price >= ath * 0.93
                        and price > ema9
                    ):
                        results.append(symbol)
                except Exception:
                    continue
        except Exception:
            continue
    return sorted(list(set(results)))


if __name__ == "__main__":
    assert_required_covered()
    final_results = []
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page(user_agent="Mozilla/5.0")
        for etf in ETF_LIST:
            print(f"🚀 掃描中: {etf}")
            symbols = scrape_etf_holdings(page, etf)
            print(f"   holdings: {len(symbols)}")
            leaders = analyze_holdings(etf, symbols)
            final_results.append({"etf": etf, "leaders": leaders})
        browser.close()

    final_results.sort(key=lambda x: x["etf"])
    headers = [entry["etf"] for entry in final_results]
    columns = [entry["leaders"] for entry in final_results]
    rows = list(itertools.zip_longest(*columns, fillvalue=""))

    file_name = f"ETF_Leaders_{datetime.datetime.now().strftime('%Y%m%d')}.csv"
    with open(file_name, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(headers)
        writer.writerows(rows)
    print(f"✅ 完成！產出檔案: {file_name}")
    print(f"CSV 欄位數（ETF 數）: {len(headers)}")
