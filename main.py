import yfinance as yf
import pandas as pd
import datetime
import requests
import os
import sys
from io import StringIO

# ============================================================
# סורק מניות בדפוס "התאוששות אחרי צניחה" (Capitulation Recovery)
#
# מחפש מניות שעברו את כל השלבים הבאים:
# 1. צניחה חדה של מעל 35% ב-6 חודשים אחרונים
# 2. התאוששות ראשונית מהשפל (לפחות 5% מעל התחתית)
# 3. שלב דשדוש (טווח מחירים צר) שהתרחש לפני הפריצה האחרונה
# 4. פריצה מעל תחום הדשדוש בשבועות/חודשים האחרונים
# 5. התקרבות ל-MA150 מלמטה, עם אישור נפח מסחר (RVOL)
# ============================================================

def get_detailed_info(ticker):
    """משיכת חדשות ונתוני אינסיידרים"""
    try:
        stock = yf.Ticker(ticker)
        news_link = f"https://www.google.com/search?q={ticker}+stock+news&tbm=nws"
        news_html = f"<a href='{news_link}' target='_blank' style='text-decoration:none;'>🔍 חדשות</a>"

        insider = stock.insider_transactions
        ins_val = "אין מידע"
        if insider is not None and not insider.empty:
            text = str(insider.iloc[0].get('Text', ''))
            if "Purchase" in text or "Buy" in text:
                ins_val = "<span style='color:#27ae60; font-weight:bold;'>🟢 קנייה</span>"
            elif "Sale" in text or "Sell" in text:
                ins_val = "<span style='color:#e74c3c;'>🔴 מכירה</span>"
            else:
                ins_val = text[:15]
        return news_html, ins_val
    except:
        return "אין חדשות", "אין מידע"


def detect_consolidation(df, lookback=25, gap_days=10, max_range_pct=0.12):
    """
    בודק אם הייתה תקופת דשדוש (טווח מחירים צר) לפני הפריצה האחרונה.
    lookback   - כמה ימי מסחר אחורה בודקים את הדשדוש עצמו
    gap_days   - כמה ימים "משאירים" בסוף כתקופת הפריצה (לא נספרים כדשדוש)
    max_range_pct - טווח מחירים מקסימלי מותר (כאחוז מהשפל) כדי להיחשב דשדוש
    """
    if len(df) < lookback + gap_days:
        return False, None, None

    window = df['Close'].iloc[-(lookback + gap_days):-gap_days]
    if window.empty:
        return False, None, None

    cons_high = float(window.max())
    cons_low = float(window.min())
    range_pct = (cons_high - cons_low) / cons_low
    return (range_pct <= max_range_pct), cons_high, cons_low


def write_github_output(results):
    """כותב את מספר התוצאות ורשימת הטיקרים לשלבים הבאים בריצה (לצורך שליחת מייל)"""
    out_path = os.environ.get("GITHUB_OUTPUT")
    if not out_path:
        return
    tickers_found = [r["טיקר"].replace("<b>", "").replace("</b>", "") for r in results]
    with open(out_path, "a", encoding="utf-8") as f:
        f.write(f"count={len(results)}\n")
        f.write(f"tickers={', '.join(tickers_found)}\n")


def fetch_wiki_tickers(url, column, headers):
    """מושך טבלת מניות מוויקיפדיה ומחפש את הטבלה לפי שם העמודה (ולא לפי מיקום קבוע)"""
    resp = requests.get(url, headers=headers, timeout=30)
    resp.raise_for_status()
    # pandas 3 דורש לעטוף את ה-HTML ב-StringIO
    for table in pd.read_html(StringIO(resp.text)):
        if column in table.columns:
            return table[column].dropna().astype(str).tolist()
    raise ValueError(f"column '{column}' not found at {url}")


def get_tickers():
    headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36'}
    tickers = []
    sources = [
        ('https://en.wikipedia.org/wiki/List_of_S%26P_500_companies', 'Symbol', 'S&P 500'),
        ('https://en.wikipedia.org/wiki/Nasdaq-100', 'Ticker', 'Nasdaq-100'),
    ]
    for url, column, name in sources:
        try:
            lst = fetch_wiki_tickers(url, column, headers)
            print(f"{name}: {len(lst)} tickers")
            tickers.extend(lst)
        except Exception as e:
            print(f"ERROR fetching {name}: {e}")

    tickers = sorted(set(t.replace('.', '-') for t in tickers))
    # אם רשימת המניות לא נמשכה כראוי - להכשיל את הריצה במקום לסרוק רשימה חלקית בשקט
    if len(tickers) < 400:
        print(f"ERROR: only {len(tickers)} tickers fetched - aborting so the failure is visible")
        sys.exit(1)
    return tickers


def run_scanner():
    print("Starting Capitulation Recovery Scan...")
    tickers = get_tickers()
    results = []
    print(f"Scanning {len(tickers)} stocks...")

    for i, ticker in enumerate(tickers):
        try:
            if i % 50 == 0:
                print(f"Progress: {i}/{len(tickers)}")

            df = yf.download(ticker, period="1y", interval="1d", progress=False, timeout=10)
            if df.empty or len(df) < 151:
                continue
            if isinstance(df.columns, pd.MultiIndex):
                df.columns = df.columns.get_level_values(0)

            price = float(df['Close'].iloc[-1])
            ma150 = float(df['Close'].rolling(window=150).mean().iloc[-1])

            # --- תנאי 1: צניחה של מעל 35% ב-6 חודשים ---
            price_6m_ago = float(df['Close'].iloc[-126])
            perf_6m = ((price - price_6m_ago) / price_6m_ago) * 100
            if perf_6m > -35:
                continue

            # --- תנאי 2: התאוששות ראשונית מהשפל של 6 החודשים ---
            low_6m = float(df['Close'].iloc[-126:].min())
            recovery_from_low = ((price - low_6m) / low_6m) * 100
            if recovery_from_low < 5:
                continue  # עדיין קרוב מדי לשפל, אין עדיין סימן להתאוששות אמיתית

            # --- תנאי 3: זיהוי שלב דשדוש לפני הפריצה ---
            is_consolidating, cons_high, cons_low = detect_consolidation(df)
            if not is_consolidating:
                continue

            # --- תנאי 4: פריצה מעל תחום הדשדוש בימים/שבועות האחרונים ---
            recent_high = float(df['Close'].iloc[-10:].max())
            if recent_high <= cons_high * 1.02:
                continue  # עוד לא ממש פרצה מעל הדשדוש

            # --- תנאי 5: התקרבות ל-MA150 מלמטה (עד 8%) ---
            dist_from_below = (ma150 - price) / ma150
            if not (0 <= dist_from_below <= 0.08):
                continue

            # --- RVOL - אישור נפח מסחר ---
            avg_vol = df['Volume'].rolling(window=20).mean().iloc[-1]
            rvol = float(df['Volume'].iloc[-1] / avg_vol) if avg_vol > 0 else 0

            news, insider = get_detailed_info(ticker)
            rvol_str = f"{rvol:.2f}"
            if rvol > 1.5:
                rvol_str = f"<b style='color:#27ae60;'>{rvol:.2f} 🔥</b>"

            results.append({
                "טיקר": f"<b>{ticker}</b>",
                "מחיר": f"{price:.2f}$",
                "צניחה (6 חודשים)": f"{perf_6m:.1f}%",
                "עלייה מהתחתית": f"{recovery_from_low:.1f}%",
                "מרחק מ-MA150": f"{dist_from_below*100:.1f}%",
                "RVOL": rvol_str,
                "אינסיידרים": insider,
                "חדשות": news
            })
        except:
            continue

    # בניית ה-HTML
    if results:
        df_res = pd.DataFrame(results).sort_values(by="RVOL", ascending=False)
        table_html = df_res.to_html(escape=False, index=False)
    else:
        table_html = "<h3 style='text-align:center;'>לא נמצאו מניות שעומדות בכל הקריטריונים כרגע.</h3>"

    full_html = f"""
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <style>
            body {{ font-family: 'Segoe UI', Arial; background: #f4f7f9; padding: 20px; direction: rtl; }}
            .card {{ background: white; padding: 25px; border-radius: 15px; box-shadow: 0 10px 20px rgba(0,0,0,0.05); overflow-x: auto; }}
            h1 {{ color: #1a73e8; text-align: center; }}
            table {{ width: 100%; border-collapse: collapse; margin-top: 20px; }}
            th {{ background: #1a73e8; color: white; padding: 15px; text-align: right; }}
            td {{ padding: 15px; border-bottom: 1px solid #eee; text-align: right; }}
            tr:hover {{ background: #f1f8ff; }}
        </style>
    </head>
    <body>
        <div class="card">
            <h1>💎 סורק התאוששות אחרי צניחה (Capitulation Recovery)</h1>
            <p style="text-align:center; color:#666;">
            מניות שצנחו מעל 35% ב-6 חודשים, עברו שלב דשדוש, פרצו ממנו, ומתקרבות כעת ל-MA150<br>
            נסרקו {len(tickers)} מניות · סריקה אחרונה: {datetime.datetime.now().strftime('%Y-%m-%d %H:%M:%S')} UTC</p>
            {table_html}
        </div>
    </body>
    </html>
    """
    with open("index.html", "w", encoding="utf-8") as f:
        f.write(full_html)

    write_github_output(results)
    print(f"Found {len(results)} matching stocks")


if __name__ == "__main__":
    run_scanner()
