import os
import io
import re
import csv
import requests
import pandas as pd
import yfinance as yf

--------------------------------------------------
CONFIG
--------------------------------------------------

WEBHOOK_URL = os.getenv("DISCORD_WEBHOOK_URL")

--------------------------------------------------
HELPERS
--------------------------------------------------

def normalize_tsx(symbols):
out = []

for s in symbols:
    s = str(s).strip().upper().replace(" ", "")

    if not s or s in {"NAN", "NONE"}:
        continue

    s = re.sub(r"^[A-Z]+:", "", s)
    s = re.sub(r"[:\.](CN|XTSE|TSE)$", "", s)

    s = s.replace(".UN", "-UN")
    s = s.replace(".U", "-U")

    if not s.endswith(".TO"):
        s += ".TO"

    out.append(s)

return sorted(set(out))

def get_xic_holdings():

url = (
    "https://www.blackrock.com/ca/investors/en/products/239837/"
    "ishares-sptsx-capped-composite-index-etf/1464253357814.ajax"
    "?dataType=fund&fileName=XIC_holdings&fileType=csv"
)

try:

    r = requests.get(url, timeout=20)
    r.raise_for_status()

    text = r.content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    header_idx = None

    for i, line in enumerate(lines[:200]):
        if "ticker" in line.lower() or "symbol" in line.lower():
            header_idx = i
            break

    if header_idx is None:
        raise Exception("Header introuvable")

    body = "\n".join(lines[header_idx:])

    try:
        dialect = csv.Sniffer().sniff(body[:500])
        sep = dialect.delimiter
    except Exception:
        sep = ","

    df = pd.read_csv(io.StringIO(body), sep=sep)

    col = None

    for c in df.columns:
        if str(c).lower().strip() in [
            "ticker",
            "symbol",
            "holding ticker",
            "holding symbol",
        ]:
            col = c
            break

    if col is None:
        raise Exception("Colonne ticker introuvable")

    symbols = df[col].dropna().tolist()

    return normalize_tsx(symbols)

except Exception as e:

    print(f"Erreur univers XIC: {e}")

    return [
        "RY.TO","TD.TO","BNS.TO","BMO.TO","CM.TO",
        "NA.TO","MFC.TO","SLF.TO","CNQ.TO",
        "SU.TO","ENB.TO","TRP.TO","SHOP.TO",
        "CP.TO","CNR.TO","ATD.TO","WSP.TO"
    ]

def download_data(ticker):

try:

    df = yf.download(
        ticker,
        period="3mo",
        interval="1d",
        progress=False,
        auto_adjust=False
    )

    if df is None or df.empty:
        return None

    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    return df

except Exception as e:

    print(f"{ticker}: {e}")
    return None

def compute_heikin_ashi(df):

ha = pd.DataFrame(index=df.index)

ha["Close"] = (
    df["Open"]
    + df["High"]
    + df["Low"]
    + df["Close"]
) / 4

ha_open = [
    (df["Open"].iloc[0] + df["Close"].iloc[0]) / 2
]

for i in range(1, len(df)):
    ha_open.append(
        (ha_open[i - 1] + ha["Close"].iloc[i - 1]) / 2
    )

ha["Open"] = ha_open

return ha

def match_pattern(ha):

if len(ha) < 4:
    return False

reds = ha.iloc[-4:-1]
green = ha.iloc[-1]

return (
    (reds["Close"] < reds["Open"]).sum() == 3
    and green["Close"] > green["Open"]
    and green["Close"] > reds.iloc[-1]["Close"]
)
--------------------------------------------------
SCAN
--------------------------------------------------

print("Début scan TSX")

tickers = get_xic_holdings()

print(f"{len(tickers)} tickers trouvés")

detected = []

for i, ticker in enumerate(tickers, start=1):

print(f"{i}/{len(tickers)} {ticker}")

df = download_data(ticker)

if df is None:
    continue

ha = compute_heikin_ashi(df)

if match_pattern(ha):
    detected.append(ticker)

print(f"Signaux détectés: {len(detected)}")

--------------------------------------------------
DISCORD
--------------------------------------------------

if detected:

message = (
    "🇨🇦 **TSX Scanner Heikin Ashi**\n\n"
    "Pattern : 🔴🔴🔴🟢\n\n"
    f"Signaux détectés : **{len(detected)}**\n\n"
    + "\n".join(f"• {x}" for x in detected[:50])
)

else:

message = (
    "🇨🇦 **TSX Scanner Heikin Ashi**\n\n"
    "Aucun signal détecté aujourd'hui."
)

print(message)

if WEBHOOK_URL:

response = requests.post(
    WEBHOOK_URL,
    json={"content": message},
    timeout=20
)

print("Discord status:", response.status_code)

else:

print("DISCORD_WEBHOOK_URL absent")
