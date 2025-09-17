# app.py — TSX scanner robuste (sans read_html), avec diagnostics immédiats
import io, re, time, csv
from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

# ----------------------------- CONFIG -----------------------------
st.set_page_config(page_title="TSX — 3 Rouges + 1 Vert (Heikin-Ashi)", layout="wide")
st.title("🇨🇦 S&P/TSX — Détection 3 rouges puis 1 vert (Heikin-Ashi)")

# Affiche une bannière de diagnostic dès le départ
st.info("App chargée. Si rien ne s'affiche ensuite, ouvre le volet 'Journaux' plus bas.")

if "logs" not in st.session_state:
    st.session_state.logs = []
def log(msg: str) -> None:
    st.session_state.logs.append(msg)

# ----------------------------- HELPERS -----------------------------
def _normalize_tsx(symbols: List[str]) -> List[str]:
    out = []
    for s in symbols:
        s = str(s).strip().upper().replace(" ", "")
        if not s or s in {"NAN", "NONE"}:
            continue
        s = re.sub(r"^[A-Z]+:", "", s)             # TSX:RY -> RY
        s = re.sub(r"[:\.](CN|XTSE|TSE)$", "", s)  # :CN/.CN/.XTSE etc.
        s = s.replace(".UN", "-UN").replace(".U", "-U")
        if not s.endswith(".TO"):
            s = f"{s}.TO"
        if re.fullmatch(r"[A-Z0-9\-\.]{1,12}\.TO", s):
            out.append(s)
    return sorted(set(out))

def _http_get(url: str, timeout: int = 15) -> requests.Response:
    headers = {
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"),
        "Accept-Language": "en,fr;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    resp = requests.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp

def _read_blackrock_xic_tickers() -> Optional[List[str]]:
    """
    Lit le CSV holdings XIC (BlackRock) SANS read_html:
    - détecte la ligne d'entête
    - sniff du délimiteur
    - retourne une liste normalisée .TO
    """
    url = (
        "https://www.blackrock.com/ca/investors/en/products/239837/"
        "ishares-sptsx-capped-composite-index-etf/1464253357814.ajax"
        "?dataType=fund&fileName=XIC_holdings&fileType=csv"
    )
    try:
        r = _http_get(url, timeout=15)  # timeout court pour éviter une longue attente
        text = r.content.decode("utf-8-sig", errors="replace")
        lines = text.splitlines()
        header_idx = None
        header_candidates = {"ticker", "symbol", "holding ticker", "holding symbol"}
        for i, line in enumerate(lines[:200]):
            if any(h in line.lower() for h in header_candidates):
                header_idx = i
                break
        if header_idx is None:
            for i, line in enumerate(lines[:300]):
                if line.count(",") >= 3 or line.count(";") >= 3 or line.count("\t") >= 3:
                    header_idx = i
                    break
        if header_idx is None:
            log("[XIC CSV] entête introuvable")
            return None

        body_text = "\n".join(lines[header_idx:])
        try:
            dialect = csv.Sniffer().sniff("\n".join(body_text.splitlines()[:2]))
            sep = dialect.delimiter
        except Exception:
            sep = ","

        df = pd.read_csv(io.StringIO(body_text), sep=sep, engine="python")
        col = None
        for c in df.columns:
            if str(c).strip().lower() in {"ticker", "symbol", "holding ticker", "holding symbol"}:
                col = c
                break
        if col is None:
            log("[XIC CSV] colonne ticker/symbol introuvable")
            return None

        syms = df[col].dropna().astype(str).tolist()
        norm = _normalize_tsx(syms)
        if len(norm) >= 150:
            return norm
        log(f"[XIC CSV] trop peu de tickers ({len(norm)})")
        return None
    except Exception as e:
        log(f"[XIC CSV] {type(e).__name__}: {e}")
        return None

@st.cache_data(ttl=24*60*60)
def get_tsx_universe() -> List[str]:
    # 1) BlackRock XIC
    tickers = _read_blackrock_xic_tickers()
    if tickers:
        st.caption("✅ Univers via BlackRock XIC (CSV holdings).")
        return tickers

    # 2) Repli codé en dur : TSX-60
    tsx60 = [
        "RY.TO","TD.TO","BNS.TO","BMO.TO","CM.TO","NA.TO","MFC.TO","SLF.TO","GWO.TO","IFC.TO",
        "CNQ.TO","SU.TO","ENB.TO","TRP.TO","TOU.TO","CVE.TO","IMO.TO","POU.TO","ARX.TO","PPL.TO",
        "AEM.TO","ABX.TO","FNV.TO","NEM.TO","WPM.TO","NGD.TO",
        "BCE.TO","T.TO","QBR-B.TO",
        "CP.TO","CNR.TO","WSP.TO","CAE.TO","TFII.TO","ATD.TO","MG.TO",
        "SHOP.TO","GIB-A.TO","OTEX.TO","DSG.TO","CSU.TO","BB.TO","KXS.TO",
        "CPX.TO","BAM.TO","BN.TO","BIP-UN.TO","BEPC.TO","BEP-UN.TO",
        "DOL.TO","L.TO","WN.TO","ATZ.TO","TRI.TO","QSR.TO","EMP-A.TO","CTC-A.TO",
    ]
    st.info("ℹ️ Univers Composite indisponible — repli **S&P/TSX 60** (liste interne).")
    return sorted(set(tsx60))

@st.cache_data
def download_data(ticker: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    try:
        df = yf.download(
            ticker, period=period, interval="1d",
            progress=False, auto_adjust=False, group_by="column", threads=True
        )
    except Exception as e:
        log(f"[yfinance] {ticker}: {type(e).__name__}: {e}")
        return None

    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.dropna(subset=["Open", "High", "Low", "Close"])
    return df if not df.empty else None

def compute_heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    ha = pd.DataFrame(index=df.index)
    ha["Close"] = (df["Open"] + df["High"] + df["Low"] + df["Close"]) / 4
    ha_open = [(df["Open"].iloc[0] + df["Close"].iloc[0]) / 2]
    for i in range(1, len(df)):
        ha_open.append((ha_open[i-1] + ha["Close"].iloc[i-1]) / 2)
    ha["Open"] = ha_open
    ha["High"] = pd.concat([df["High"], ha["Open"], ha["Close"]], axis=1).max(axis=1)
    ha["Low"] = pd.concat([df["Low"], ha["Open"], ha["Close"]], axis=1).min(axis=1)
    return ha

def match_pattern_last4(ha: pd.DataFrame) -> bool:
    if len(ha) < 4:
        return False
    reds = ha.iloc[-4:-1]
    green = ha.iloc[-1]
    return (reds["Close"] < reds["Open"]).sum() == 3 and (green["Close"] > green["Open"]) and (green["Close"] > reds.iloc[-1]["Close"])

# ----------------------------- UI -----------------------------
st.sidebar.header("Configuration")
limit_n = st.sidebar.slider("Limiter le nombre de tickers", 20, 400, 200, step=10)
cooldown = st.sidebar.slider("Pause entre requêtes (s)", 0.0, 0.5, 0.05, step=0.05)
period = st.sidebar.selectbox("Période de téléchargement", ["1mo", "2mo", "3mo", "6mo"], index=2)

# Option upload CSV locale (aucun appel réseau)
uploaded = None
up = st.sidebar.file_uploader("CSV custom (colonne 'Symbol' / 'Ticker' ex.: RY, ENB, XRE.UN)", type=["csv"])
if up is not None:
    try:
        udf = pd.read_csv(up)
        col = next((c for c in ["Symbol", "Ticker", "Ticker symbol", "Symbole"] if c in udf.columns), None)
        if col:
            uploaded = _normalize_tsx(udf[col].dropna().astype(str).tolist())
            st.sidebar.success(f"{len(uploaded)} tickers chargés.")
        else:
            st.sidebar.error("Colonne introuvable. Utilise 'Symbol' ou 'Ticker'.")
    except Exception as e:
        st.sidebar.error(f"Lecture CSV: {type(e).__name__}: {e}")

go_scan = st.sidebar.button("🚦 Lancer l’analyse")

if go_scan:
    with st.status("Préparation de l’univers…", expanded=True) as status:
        if uploaded:
            tickers = uploaded
            st.write(f"Univers = CSV upload ({len(tickers)} tickers)")
        else:
            tickers = get_tsx_universe()
            st.write(f"Univers = {len(tickers)} tickers")

        tickers = tickers[:limit_n]
        status.update(label="Scan en cours…", state="running")

    detected: List[str] = []
    prog = st.progress(0, text="Analyse des tickers…")
    total = len(tickers)
    for i, ticker in enumerate(tickers, 1):
        df = download_data(ticker, period=period)
        if df is not None:
            ha = compute_heikin_ashi(df)
            if match_pattern_last4(ha):
                detected.append(ticker)
        prog.progress(i / total, text=f"Scanné: {ticker}")
        if cooldown:
            time.sleep(cooldown)

    st.write("---")
    if detected:
        st.success(f"🎯 {len(detected)} signal(s) détecté(s) !")
        st.dataframe(pd.DataFrame(detected, columns=["Ticker"]), use_container_width=True)
        choice = st.selectbox("📌 Afficher :", detected)
        if choice:
            df_sel = download_data(choice, period=max(period, "3mo"))
            if df_sel is not None:
                ha_sel = compute_heikin_ashi(df_sel)
                fig = go.Figure([go.Candlestick(
                    x=ha_sel.index, open=ha_sel["Open"], high=ha_sel["High"],
                    low=ha_sel["Low"], close=ha_sel["Close"],
                    increasing_line_color="green", decreasing_line_color="red"
                )])
                fig.update_layout(title=f"Heikin-Ashi: {choice}", xaxis_title="Date", yaxis_title="Prix")
                st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Aucun signal trouvé.")

with st.expander("Journaux (fetch, erreurs réseau, etc.)", expanded=True):
    if st.session_state.logs:
        st.code("\n".join(st.session_state.logs))
    else:
        st.caption("Aucun log pour l’instant.")
