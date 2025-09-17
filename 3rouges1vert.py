# app.py  — TSX scanner sans Wikipédia
import io
import re
import time
from typing import List, Optional

import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf


# ----------------------------- CONFIG STREAMLIT -----------------------------
st.set_page_config(page_title="TSX — 3 Rouges + 1 Vert (Heikin-Ashi)", layout="wide")
st.title("🇨🇦 S&P/TSX — Détection 3 chandeliers rouges puis 1 vert (Heikin-Ashi)")

if "logs" not in st.session_state:
    st.session_state.logs = []
def log(msg: str) -> None:
    st.session_state.logs.append(msg)


# ----------------------------- HELPERS HTTP & NORMALISATION -----------------------------
def _http_get(url: str, timeout: int = 30) -> requests.Response:
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

def _normalize_tsx(symbols: List[str]) -> List[str]:
    out = []
    for s in symbols:
        s = str(s).strip().upper()
        if not s or s in {"NAN", "NONE"}:
            continue
        s = s.replace(" ", "")
        # Retire préfixes type 'TSX:' / 'TSE:' s'ils existent
        s = re.sub(r"^[A-Z]+:", "", s)
        # Retire suffixes alternatifs éventuels (:CN, .CN, .XTSE)
        s = re.sub(r"[:\.](CN|XTSE|TSE)$", "", s)
        # Conventions yfinance pour TSX
        s = s.replace(".UN", "-UN").replace(".U", "-U")
        if not s.endswith(".TO"):
            s = f"{s}.TO"
        if re.fullmatch(r"[A-Z0-9\-\.]{1,12}\.TO", s):
            out.append(s)
    return sorted(set(out))


# ----------------------------- SOURCES SANS WIKIPÉDIA -----------------------------
@st.cache_data(ttl=24*60*60)
def get_tsx_universe(source_choice: str = "Auto") -> List[str]:
    """
    Univers TSX depuis sources NON-Wikipédia par ordre de priorité :
      1) BlackRock XIC CSV (holdings)  -> S&P/TSX Capped Composite
      2) TMX Money Composite constituents (table HTML)
      3) TradingView Composite components (table HTML)
      4) Repli TSX-60 (TMX)
      5) Échantillon minimal
    source_choice: "Auto" (recommandé), ou "TSX 60"
    """
    # 1) BlackRock XIC — CSV holdings (download direct)
    #    Si le lien change un jour: récupérer le nouveau href sur la page BlackRock (Download holdings)
    if source_choice in ("Auto",):
        try:
            xic_csv = (
                "https://www.blackrock.com/ca/investors/en/products/239837/"
                "ishares-sptsx-capped-composite-index-etf/1464253357814.ajax"
                "?dataType=fund&fileName=XIC_holdings&fileType=csv"
            )
            resp = _http_get(xic_csv, timeout=35)
            df = pd.read_csv(io.BytesIO(resp.content))
            # Cherche colonne ticker/symbol
            cand = None
            for c in df.columns:
                cl = str(c).strip().lower()
                if cl in {"ticker", "symbol"}:
                    cand = c
                    break
            if cand is None:
                # essais classiques BlackRock (parfois 'Ticker' capitalisé)
                for c in ["Ticker", "Symbol"]:
                    if c in df.columns:
                        cand = c
                        break
            if cand is not None:
                syms = df[cand].dropna().astype(str).tolist()
                norm = _normalize_tsx(syms)
                if len(norm) >= 150:
                    st.caption("✅ Univers chargé via BlackRock XIC (CSV holdings).")
                    return norm
            log("[XIC CSV] colonne ticker/symbol non trouvée")
        except Exception as e:
            log(f"[XIC CSV] échec — {type(e).__name__}: {e}")

    # 2) TMX Money — Constituents (Composite)
    if source_choice in ("Auto",):
        try:
            tmx_url = "https://money.tmx.com/en/quote/%5ETSX/constituents"
            resp = _http_get(tmx_url, timeout=30)
            tables = pd.read_html(resp.text)
            for t in tables:
                cols_lower = [str(c).strip().lower() for c in t.columns]
                if "symbol" in cols_lower or "ticker" in cols_lower:
                    # Choisit la première colonne dispo
                    col = None
                    for cand in ["Symbol", "Ticker", "Ticker symbol"]:
                        if cand in t.columns:
                            col = cand
                            break
                    if col is None:
                        col = t.columns[cols_lower.index("symbol")] if "symbol" in cols_lower else t.columns[cols_lower.index("ticker")]
                    syms = t[col].dropna().astype(str).tolist()
                    norm = _normalize_tsx(syms)
                    if len(norm) >= 150:
                        st.caption("✅ Univers chargé via TMX Money (Composite).")
                        return norm
            log("[TMX] colonnes Symbol/Ticker non trouvées dans les tables")
        except Exception as e:
            log(f"[TMX] échec — {type(e).__name__}: {e}")

    # 3) TradingView — Components (Composite)
    if source_choice in ("Auto",):
        try:
            tv_url = "https://www.tradingview.com/symbols/TSX-TSX/components/"
            resp = _http_get(tv_url, timeout=30)
            tables = pd.read_html(resp.text)
            best = None
            for t in tables:
                cols_lower = [str(c).strip().lower() for c in t.columns]
                if any("symbol" in c or "ticker" in c for c in cols_lower):
                    best = t
                    break
            if best is not None:
                # repère colonne la plus probable
                col = None
                for c in best.columns:
                    if str(c).strip().lower() in {"symbol", "ticker"}:
                        col = c
                        break
                if col is None:
                    col = best.columns[0]
                syms = best[col].dropna().astype(str).tolist()
                # Enlève le préfixe 'TSX:' si présent
                syms = [re.sub(r"^[A-Z]+:", "", s) for s in syms]
                norm = _normalize_tsx(syms)
                if len(norm) >= 120:
                    st.caption("✅ Univers chargé via TradingView (Composite).")
                    return norm
            log("[TradingView] table/colonne symbol introuvable")
        except Exception as e:
            log(f"[TradingView] échec — {type(e).__name__}: {e}")

    # 4) Repli TSX-60 — TMX
    if source_choice in ("Auto", "TSX 60"):
        try:
            tsx60_url = "https://money.tmx.com/en/quote/%5ETX60/constituents"
            resp = _http_get(tsx60_url, timeout=30)
            tables = pd.read_html(resp.text)
            for t in tables:
                for cand in ["Symbol", "Ticker", "Ticker symbol"]:
                    if cand in t.columns:
                        syms = t[cand].dropna().astype(str).tolist()
                        norm = _normalize_tsx(syms)
                        if len(norm) >= 40:
                            st.info("ℹ️ Univers Composite indisponible — repli **S&P/TSX 60**.")
                            return norm
            log("[TSX60] colonnes Symbol/Ticker non trouvées")
        except Exception as e:
            log(f"[TSX60] échec — {type(e).__name__}: {e}")

    # 5) Dernier recours
    st.warning("Impossible de récupérer un univers TSX en ligne. Utilisation d’un échantillon minimal.")
    return ["RY.TO", "TD.TO", "BNS.TO", "ENB.TO", "CNQ.TO", "SU.TO", "SHOP.TO", "BCE.TO"]


# ----------------------------- DONNÉES & INDICATEUR -----------------------------
@st.cache_data
def download_data(ticker: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    try:
        df = yf.download(
            ticker,
            period=period,
            interval="1d",
            progress=False,
            auto_adjust=False,
            group_by="column",
            threads=True,
        )
    except Exception as e:
        log(f"[yfinance] échec {ticker} — {type(e).__name__}: {e}")
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
        ha_open.append((ha_open[i - 1] + ha["Close"].iloc[i - 1]) / 2)
    ha["Open"] = ha_open
    ha["High"] = pd.concat([df["High"], ha["Open"], ha["Close"]], axis=1).max(axis=1)
    ha["Low"] = pd.concat([df["Low"], ha["Open"], ha["Close"]], axis=1).min(axis=1)
    return ha

def match_pattern_last4(ha: pd.DataFrame) -> bool:
    if len(ha) < 4:
        return False
    reds = ha.iloc[-4:-1]
    green = ha.iloc[-1]
    return (reds["Close"] < reds["Open"]).sum() == 3 and (green["Close"] > green["Open"]) and (
        green["Close"] > reds.iloc[-1]["Close"]
    )


# ----------------------------- SIDEBAR / UI -----------------------------
st.sidebar.header("Configuration du scan")
src = st.sidebar.selectbox(
    "Source de l’univers (sans Wikipédia)",
    ["Auto (XIC → TMX → TradingView → TSX60)", "TSX 60 (TMX)", "CSV (upload manuel)"],
    index=0,
)
limit_n = st.sidebar.slider("Limiter le nombre de tickers (accélère le scan)", 20, 400, 250, step=10)
cooldown = st.sidebar.slider("Pause entre requêtes (secondes)", 0.0, 0.5, 0.10, step=0.05)
period = st.sidebar.selectbox("Période de téléchargement", ["1mo", "2mo", "3mo", "6mo"], index=2)

uploaded = None
if src == "CSV (upload manuel)":
    up = st.sidebar.file_uploader(
        "Uploader un CSV avec une colonne 'Symbol' ou 'Ticker' (ex.: RY, ENB, XRE.UN)",
        type=["csv"],
    )
    if up is not None:
        try:
            udf = pd.read_csv(up)
            col = None
            for cand in ["Symbol", "Ticker", "Ticker symbol", "Symbole"]:
                if cand in udf.columns:
                    col = cand
                    break
            if col is None:
                st.error("Colonne introuvable. Utilise 'Symbol' ou 'Ticker' dans ton CSV.")
            else:
                uploaded = _normalize_tsx(udf[col].dropna().astype(str).tolist())
                st.success(f"{len(uploaded)} tickers chargés depuis le CSV.")
        except Exception as e:
            st.error(f"Impossible de lire le CSV: {type(e).__name__}: {e}")

go_scan = st.sidebar.button("🚦 Lancer l’analyse")


# ----------------------------- MAIN -----------------------------
if go_scan:
    if src == "CSV (upload manuel)":
        tickers = uploaded or []
        if not tickers:
            st.stop()
    else:
        tickers = get_tsx_universe("Auto" if src.startswith("Auto") else "TSX 60")

    if not tickers:
        st.error("Aucun ticker disponible.")
        st.stop()

    tickers = tickers[:limit_n]
    st.write(f"Univers sélectionné : **{len(tickers)} tickers**")

    detected: List[str] = []
    prog = st.progress(0, text="Analyse des tickers…")
    total = len(tickers)
    placeholder = st.empty()

    for i, ticker in enumerate(tickers, 1):
        df = download_data(ticker, period=period)
        if df is None or len(df) < 4:
            prog.progress(i / total, text=f"{ticker}: pas assez de données…")
            if cooldown:
                time.sleep(cooldown)
            continue

        ha = compute_heikin_ashi(df)
        if match_pattern_last4(ha):
            detected.append(ticker)

        prog.progress(i / total, text=f"Scanné: {ticker}")
        if i % 10 == 0:
            placeholder.caption(f"Progression: {i}/{total} — Détections: {len(detected)}")
        if cooldown:
            time.sleep(cooldown)

    st.write("---")
    if detected:
        st.success(f"🎯 {len(detected)} signal(s) détecté(s) !")
        df_res = pd.DataFrame(detected, columns=["Ticker"])
        st.dataframe(df_res, use_container_width=True)

        ticker_choice = st.selectbox("📌 Sélectionne un ticker à afficher :", detected)
        if ticker_choice:
            df_sel = download_data(ticker_choice, period=max(period, "3mo"))
            if df_sel is not None:
                ha_sel = compute_heikin_ashi(df_sel)
                fig = go.Figure(
                    data=[
                        go.Candlestick(
                            x=ha_sel.index,
                            open=ha_sel["Open"],
                            high=ha_sel["High"],
                            low=ha_sel["Low"],
                            close=ha_sel["Close"],
                            increasing_line_color="green",
                            decreasing_line_color="red",
                        )
                    ]
                )
                fig.update_layout(
                    title=f"Heikin-Ashi: {ticker_choice}",
                    xaxis_title="Date",
                    yaxis_title="Prix",
                )
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.error("Impossible de recharger les données pour l’affichage.")
    else:
        st.warning("Aucun signal trouvé sur la période récente.")

    with st.expander("Voir les journaux (fetch tickers, erreurs réseau, etc.)"):
        if st.session_state.logs:
            st.code("\n".join(st.session_state.logs))
        else:
            st.caption("Aucun log.")
else:
    st.info("Choisis la source (BlackRock/TMX/TradingView ou CSV), règle les options, puis clique **🚦 Lancer l’analyse**.")

st.caption(
    "Astuce: si l’hébergeur bloque certains sites, utilise **CSV (upload manuel)**. "
    "Colonnes acceptées: Symbol / Ticker (ex.: RY, ENB, XRE.UN). Le suffixe .TO est ajouté automatiquement."
)

