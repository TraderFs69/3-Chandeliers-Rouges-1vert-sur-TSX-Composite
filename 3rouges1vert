import streamlit as st
import pandas as pd
import yfinance as yf
import plotly.graph_objects as go
import requests
import time

st.set_page_config(page_title="TSX — 3 Chandeliers (Rouges x3 + Vert)", layout="wide")
st.title("🇨🇦 S&P/TSX Composite — Détection 3 Rouges puis 1 Vert (Heikin-Ashi)")

# ---------- Tickeurs TSX ----------
@st.cache_data(ttl=24*60*60)  # 24h
def get_tsx_composite_tickers() -> list[str]:
    """
    Récupère la liste S&P/TSX Composite depuis Wikipédia et normalise pour yfinance.
    Ex.: 'BCE' -> 'BCE.TO', 'XRE.UN' -> 'XRE-UN.TO', 'DOL.U' -> 'DOL-U.TO'
    """
    wiki_url = "https://en.wikipedia.org/wiki/S%26P/TSX_Composite_Index"
    headers = {
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
    }
    try:
        resp = requests.get(wiki_url, headers=headers, timeout=20)
        resp.raise_for_status()
        tables = pd.read_html(resp.text)
        # Cherche la table qui contient une colonne 'Symbol' ou 'Ticker'
        table = next(t for t in tables if any(c.lower() in {"symbol", "ticker"} for c in t.columns.astype(str).str.lower()))
        # Trouve le nom réel de la colonne
        col = [c for c in table.columns if str(c).lower() in {"symbol", "ticker"}][0]
        syms = (
            table[col]
            .astype(str)
            .str.strip()
            .dropna()
            .tolist()
        )
    except Exception as e:
        print(f"[get_tsx_composite_tickers] Wikipedia fetch failed: {e}")
        st.warning("Impossible de récupérer la liste S&P/TSX Composite en ligne. Utilisation d’un échantillon minimal.")
        return ["RY.TO", "TD.TO", "BNS.TO", "ENB.TO", "CNQ.TO", "SU.TO", "SHOP.TO", "BCE.TO"]

    norm = []
    for s in syms:
        s = s.upper().replace(" ", "")
        # Cas spéciaux TSX: parts de fiducie / classes cotées
        if s.endswith(".UN"):
            s = s.replace(".UN", "-UN")  # XRE.UN -> XRE-UN
        elif s.endswith(".U"):
            s = s.replace(".U", "-U")    # DOL.U -> DOL-U
        # Ajoute suffixe yfinance
        if not s.endswith(".TO"):
            s = f"{s}.TO"
        # Filtre simple
        if 3 <= len(s) <= 12 and s.endswith(".TO"):
            norm.append(s)
    # Unicité
    norm = sorted(set(norm))
    # Petit garde-fou
    return norm if len(norm) >= 50 else ["RY.TO", "TD.TO", "BNS.TO", "ENB.TO", "CNQ.TO", "SU.TO", "SHOP.TO", "BCE.TO"]

# ---------- Données Marché ----------
@st.cache_data
def download_data(ticker: str, period: str = "3mo") -> pd.DataFrame | None:
    # 3 mois pour être robustes aux fériés/absences de quotes sur 4 jours
    df = yf.download(
        ticker, period=period, interval="1d",
        progress=False, auto_adjust=False, group_by="column", threads=True
    )
    if df is None or df.empty:
        return None
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    return df.dropna(subset=["Open", "High", "Low", "Close"])

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

# ---------- UI ----------
st.sidebar.header("Configuration")
scan_universe = st.sidebar.selectbox(
    "Univers de scan",
    ["S&P/TSX Composite (par défaut)", "Échantillon rapide"],
    index=0
)
limit_n = st.sidebar.slider("Limiter le nombre de tickers (accélère le scan)", 20, 300, 250, step=10)
cooldown = st.sidebar.slider("Pause entre requêtes (s) pour éviter le throttling", 0.0, 0.5, 0.1, step=0.05)

if st.sidebar.button("🚦 Lancer l'analyse"):
    tickers = get_tsx_composite_tickers()
    if scan_universe == "Échantillon rapide":
        tickers = tickers[:min(limit_n, 60)]
    else:
        tickers = tickers[:limit_n]

    detected = []
    prog = st.progress(0, text="Analyse des tickers…")
    total = len(tickers)

    for i, ticker in enumerate(tickers, 1):
        df = download_data(ticker)
        if df is None or len(df) < 4:
            prog.progress(i/total, text=f"{ticker}: pas assez de données…")
            if cooldown: time.sleep(cooldown)
            continue

        ha = compute_heikin_ashi(df)
        if len(ha) < 4:
            prog.progress(i/total, text=f"{ticker}: pas assez de HA…")
            if cooldown: time.sleep(cooldown)
            continue

        # 3 rouges (Close < Open) sur les 3 derniers avant-dernier jour, puis 1 vert
        reds = ha.iloc[-4:-1]
        green = ha.iloc[-1]
        cond = (
            (reds["Close"] < reds["Open"]).sum() == 3 and
            green["Close"] > green["Open"] and
            green["Close"] > reds.iloc[-1]["Close"]
        )
        if cond:
            detected.append(ticker)

        prog.progress(i/total, text=f"Scanné: {ticker}")
        if cooldown: time.sleep(cooldown)

    st.write("---")
    if detected:
        st.success(f"🎯 {len(detected)} signal(s) détecté(s) !")
        df_res = pd.DataFrame(detected, columns=["Ticker"])
        st.dataframe(df_res, use_container_width=True)

        ticker_choice = st.selectbox("📌 Sélectionne un ticker à afficher :", detected)
        if ticker_choice:
            df_sel = download_data(ticker_choice)
            ha_sel = compute_heikin_ashi(df_sel)
            fig = go.Figure(data=[go.Candlestick(
                x=ha_sel.index,
                open=ha_sel["Open"],
                high=ha_sel["High"],
                low=ha_sel["Low"],
                close=ha_sel["Close"],
                increasing_line_color='green',
                decreasing_line_color='red'
            )])
            fig.update_layout(title=f"Heikin-Ashi: {ticker_choice}", xaxis_title="Date", yaxis_title="Prix")
            st.plotly_chart(fig, use_container_width=True)
    else:
        st.warning("Aucun signal trouvé sur la période récente.")
else:
    st.info("Clique sur le bouton dans le menu latéral pour lancer l'analyse.")

# ---------- Notes requêtes ----------
st.caption(
    "Conseils: • Utilise un petit cooldown si tu as beaucoup de tickers. "
    "• Les FNB/parts avec .UN/.U sont normalisés en -UN/-U pour yfinance (p.ex. XRE.UN → XRE-UN.TO). "
    "• Change la période dans download_data si tu veux scanner plus court/long."
)
