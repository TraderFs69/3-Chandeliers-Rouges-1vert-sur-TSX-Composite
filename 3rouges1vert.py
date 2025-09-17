import io, re, csv
from typing import List, Optional
import pandas as pd
import streamlit as st

def _normalize_tsx(symbols: List[str]) -> List[str]:
    out = []
    for s in symbols:
        s = str(s).strip().upper().replace(" ", "")
        if not s or s in {"NAN", "NONE"}:
            continue
        s = re.sub(r"^[A-Z]+:", "", s)  # ex. TSX:RY -> RY
        s = re.sub(r"[:\.](CN|XTSE|TSE)$", "", s)  # nettoie suffixes autres
        s = s.replace(".UN", "-UN").replace(".U", "-U")
        if not s.endswith(".TO"):
            s = f"{s}.TO"
        if re.fullmatch(r"[A-Z0-9\-\.]{1,12}\.TO", s):
            out.append(s)
    return sorted(set(out))

def _read_blackrock_xic_tickers() -> Optional[List[str]]:
    """
    Télécharge et parse robustement le CSV 'holdings' de BlackRock XIC.
    Le fichier contient souvent des lignes descriptives avant l'entête.
    On détecte la ligne d'entête (celle qui contient 'Ticker' ou 'Symbol'),
    on sniffe le délimiteur, puis on lit le CSV à partir de cette ligne.
    """
    import requests
    url = (
        "https://www.blackrock.com/ca/investors/en/products/239837/"
        "ishares-sptsx-capped-composite-index-etf/1464253357814.ajax"
        "?dataType=fund&fileName=XIC_holdings&fileType=csv"
    )
    headers = {
        "User-Agent": ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")
    }
    r = requests.get(url, headers=headers, timeout=35)
    r.raise_for_status()
    # Décodage robuste (UTF-8 avec BOM éventuel)
    text = r.content.decode("utf-8-sig", errors="replace")
    lines = text.splitlines()

    # Trouve la première ligne qui ressemble à une en-tête de table
    header_idx = None
    header_candidates = {"ticker", "symbol", "holding ticker", "holding symbol"}
    for i, line in enumerate(lines[:200]):  # limite prudente
        low = line.lower()
        if any(h in low for h in header_candidates):
            header_idx = i
            break
    if header_idx is None:
        # parfois BlackRock place l'entête un peu plus loin; on tente un fallback simple
        # on cherche la première ligne avec >3 séparateurs CSV plausibles
        for i, line in enumerate(lines[:300]):
            if line.count(",") >= 3 or line.count(";") >= 3 or line.count("\t") >= 3:
                header_idx = i
                break
    if header_idx is None:
        return None

    # Recompose le CSV à partir de l'entête
    body_text = "\n".join(lines[header_idx:])

    # Sniff du délimiteur
    try:
        dialect = csv.Sniffer().sniff(body_text.splitlines()[0] + "\n" + body_text.splitlines()[1])
        sep = dialect.delimiter
    except Exception:
        # défaut: virgule
        sep = ","

    df = pd.read_csv(io.StringIO(body_text), sep=sep, engine="python")
    # Cherche colonne tickers
    col = None
    for c in df.columns:
        if str(c).strip().lower() in {"ticker", "symbol", "holding ticker", "holding symbol"}:
            col = c
            break
    if col is None:
        return None

    syms = df[col].dropna().astype(str).tolist()
    norm = _normalize_tsx(syms)
    # XIC réplique ~230-250 titres (capped composite), on attend >150 tickers
    return norm if len(norm) >= 150 else None

@st.cache_data(ttl=24*60*60)
def get_tsx_universe(source_choice: str = "Auto") -> List[str]:
    """
    Univers TSX SANS lecture HTML (pas besoin de lxml) :
      1) BlackRock XIC (CSV holdings) — principal
      2) Repli statique TSX-60 (liste codée en dur)
      3) Échantillon minimal (dernier recours)
    """
    # 1) BlackRock XIC (CSV)
    try:
        tickers = _read_blackrock_xic_tickers()
        if tickers and len(tickers) >= 150:
            st.caption("✅ Univers chargé via BlackRock XIC (CSV holdings).")
            return tickers
    except Exception as e:
        st.info(f"[XIC CSV] échec: {type(e).__name__}: {e}")

    # 2) Repli codé en dur : TSX-60 (liste stable)
    tsx60 = [
        # banques & financières majeures
        "RY.TO","TD.TO","BNS.TO","BMO.TO","CM.TO","NA.TO","MFC.TO","SLF.TO","GWO.TO","IFC.TO",
        # énergie & matières
        "CNQ.TO","SU.TO","ENB.TO","TRP.TO","TOU.TO","CVE.TO","IMO.TO","POU.TO","ARX.TO","PPL.TO",
        # mines / or
        "AEM.TO","ABX.TO","FNV.TO","NEM.TO","WPM.TO","NGD.TO",
        # télécoms & médias
        "BCE.TO","T.TO","QBR-B.TO",
        # indus / rails
        "CP.TO","CNR.TO","WSP.TO","CAE.TO","TFII.TO","ATD.TO","MG.TO",
        # tech & e-commerce
        "SHOP.TO","GIB-A.TO","OTEX.TO","DSG.TO","CSU.TO","BB.TO","KXS.TO",
        # immobilier / REITs majeures
        "CPX.TO","BAM.TO","BN.TO","BIP-UN.TO","BEPC.TO","BEP-UN.TO",
        # conso / pharma / divers
        "DOL.TO","L.TO","WN.TO","ATZ.TO","TRI.TO","QSR.TO","EMP-A.TO","CTC-A.TO",
    ]
    st.info("ℹ️ Univers Composite indisponible — repli **S&P/TSX 60** (liste interne).")
    if len(tsx60) >= 40:
        return sorted(set(tsx60))

    # 3) Dernier recours
    st.warning("Impossible de récupérer un univers TSX en ligne. Utilisation d’un échantillon minimal.")
    return ["RY.TO", "TD.TO", "BNS.TO", "ENB.TO", "CNQ.TO", "SU.TO", "SHOP.TO", "BCE.TO"]


