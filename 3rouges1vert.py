
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

# Petit panneau de logs visibles
if "logs" not in st.session_state:
    st.session_state.logs = []


def log(msg: str) -> None:
    st.session_state.logs.append(msg)


# ----------------------------- TICKERS SOURCES -----------------------------
def _normalize_tsx(symbols: List[str]) -> List[str]:
    """Normalise des tickers TSX pour yfinance : ajoute .TO, gère .UN/.U => -UN/-U, filtre simple."""
    out = []
    for s in symbols:
        s = str(s).strip().upper().replace(" ", "")
        if not s or s in {"NAN", "NONE"}:
            continue
        s = s.replace(".UN", "-UN").replace(".U", "-U")
        if not s.endswith(".TO"):
            s = f"{s}.TO"
        if re.fullmatch(r"[A-Z0-9\-\.]{1,12}\.TO", s):
            out.append(s)
    return sorted(set(out))


def _http_get(url: str, session: Optional[requests.Session] = None, timeout: int = 20) -> requests.Response:
    s = session or requests.Session()
    headers = {
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36"),
        "Accept-Language": "en,fr;q=0.9",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }
    resp = s.get(url, headers=headers, timeout=timeout)
    resp.raise_for_status()
    return resp


def _read_wiki_symbols(url: str, tries: int = 3, delay: float = 1.0) -> Optional[List[str]]:
    session = requests.Session()
    for attempt in range(1, tries + 1):
        try:
            resp = _http_get(url, session=session, timeout=25)
            tables = pd.read_html(resp.text)
            for t in tables:
                cols_lower = [str(c).strip().lower() for c in t.columns]
                # Cherche une colonne plausible
                if any(c in cols_lower for c in ["symbol", "ticker", "symbole", "ticker symbol"]):
                    for cand in ["Symbol", "Ticker", "Ticker symbol", "Symbole"]:
                        if cand in t.columns:
                            syms = t[cand].dropna().astype(str).tolist()
                            norm = _normalize_tsx(syms)
                            if len(norm) >= 40:
                                return norm
            log(f"[wiki] structure non trouvée, tentative {attempt}/{tries}")
            time.sleep(delay)
        except Exception as e:
            log(f"[wiki] échec {attempt}/{tries} — {type(e).__name__}: {e}")
            time.sleep(delay)
    return None


@st.cache_data(ttl=24 * 60 * 60)
def get_tsx_universe(source_choice: str) -> List[str]:
    """
    Récupère l'univers TSX selon l'option choisie.
    source_choice: "Composite", "TSX 60" ou "Auto"
    """
    log(f"[get_tsx_universe] source_choice={source_choice}")

    # 1) Composite via Wikipédia EN/FR
    if source_choice in ("Composite", "Auto"):
        for url in [
            "https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index",  # EN
            "https://fr.wikipedia.org/wiki/Indice_compos%C3%A9_S%26P/TSX",  # FR
        ]:
            res = _read_wiki_symbols(url)
            if res and len(res) >= 100:
                log(f"[Composite] OK via {url} — {len(res)} tickers")
                return res
            else:
                log(f"[Composite] pas de succès via {url}")

    # 2) Repli TSX-60 via Wikipédia
    if source_choice in ("TSX 60", "Auto"):
        try:
            resp = _http_get("https://en.wikipedia.org/wiki/S%26P/TSX_60", timeout=25)
            tables = pd.read_html(resp.text)
            for t in tables:
                for cand in ["Symbol", "Ticker", "Ticker symbol"]:
                    if cand in t.columns:
                        syms = t[cand].dropna().astype(str).tolist()
                        norm = _normalize_tsx(syms)
                        if len(norm) >= 40:
                            log(f"[TSX60] OK — {len(norm)} tickers")
                            st.info("Liste Composite indisponible — utilisation du **S&P/TSX 60** comme repli.")
                            return norm
            log("[TSX60] colonnes Symbol/Ticker non trouvées")
        except Exception as e:
            log(f"[TSX60] échec — {type(e).__name__}: {e}")

    # 3) Échantillon minimal
    st.warning("Impossible de récupérer la liste TSX en ligne. Utilisation d’un échantillon minimal.")
    log("[fallback] utilisation de l’échantillon minimal")
    return ["RY.TO", "TD.TO", "BNS.TO", "ENB.TO", "CNQ.TO", "SU.TO", "SHOP.TO", "BCE.TO"]


# ----------------------------- DONNÉES & INDICATEUR -----------------------------
@st.cache_data
def download_data(ticker: str, period: str = "3mo") -> Optional[pd.DataFrame]:
    """
    Télécharge les quotes daily pour le ticker.
    Période par défaut 3 mois (plus robuste qu'une semaine pour trouver 4 jours valides).
    """
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
    """
    Pattern: 3 rouges consécutifs (Close<Open) sur J-3..J-1 puis 1 vert (J0) ET
             Close(J0) > Close(J-1)
    """
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
    "Source de l’univers",
    ["Auto (Composite → TSX60)", "Composite (Wikipédia)", "TSX 60 (Wikipédia)", "CSV (upload manuel)"],
    index=0,
)

limit_n = st.sidebar.slider("Limiter le nombre de tickers (accélère le scan)", 20, 400, 250, step=10)
cooldown = st.sidebar.slider("Pause entre requêtes (secondes)", 0.0, 0.5, 0.10, step=0.05)
period = st.sidebar.selectbox("Période de téléchargement", ["1mo", "2mo", "3mo", "6mo"], index=2)

uploaded = None
if src == "CSV (upload manuel)":
    up = st.sidebar.file_uploader(
        "Uploader un CSV avec une colonne 'Symbol' ou 'Ticker' (sans .TO nécessaire)",
        type=["csv"],
    )
    if up is not None:
        try:
            udf = pd.read_csv(up)
            # Essaie plusieurs noms de colonnes
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

# Bouton de scan
go_scan = st.sidebar.button("🚦 Lancer l’analyse")


# ----------------------------- MAIN ACTION -----------------------------
if go_scan:
    # Récupère l'univers
    if src == "CSV (upload manuel)":
        tickers = uploaded or []
        if not tickers:
            st.stop()
    else:
        choice_map = {
            "Auto (Composite → TSX60)": "Auto",
            "Composite (Wikipédia)": "Composite",
            "TSX 60 (Wikipédia)": "TSX 60",
        }
        tickers = get_tsx_universe(choice_map[src])

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

    # Affiche les logs
    with st.expander("Voir les journaux (fetch tickers, erreurs réseau, etc.)"):
        if st.session_state.logs:
            st.code("\n".join(st.session_state.logs))
        else:
            st.caption("Aucun log.")
else:
    st.info("Configure l’univers dans la barre latérale puis clique sur **🚦 Lancer l’analyse**.")

st.caption(
    "Astuce: si Wikipédia est bloqué sur ton hébergeur, utilise l’option **CSV (upload manuel)**. "
    "Colonnes acceptées: Symbol / Ticker (ex.: RY, XRE.UN). Le suffixe .TO sera ajouté automatiquement."
)
