"""Eindeutige Wertpapier-Kennungen: ISIN (mit Pruefsumme), WKN, IBKR-conId."""
import re

_ISIN_RE = re.compile(r"^[A-Z]{2}[A-Z0-9]{9}[0-9]$")


def isin_valid(isin: str) -> bool:
    """Formatpruefung + Luhn-Pruefsumme (faengt erfundene ISINs der KI ab)."""
    isin = (isin or "").strip().upper()
    if not _ISIN_RE.match(isin):
        return False
    digits = "".join(str(int(c, 36)) for c in isin)
    total = 0
    for i, ch in enumerate(reversed(digits)):
        n = int(ch)
        if i % 2 == 1:
            n *= 2
            n = n - 9 if n > 9 else n
        total += n
    return total % 10 == 0


def wkn_from_isin(isin: str) -> str:
    """Deutsche ISINs haben die Form DE + 000 + WKN (6 Zeichen) + Pruefziffer; sonst leer."""
    isin = (isin or "").strip().upper()
    ok = isin.startswith("DE000") and isin_valid(isin)
    return isin[5:11] if ok else ""


def clean_ids(isin: str | None) -> dict:
    """{'isin','wkn'} – nur bei gueltiger ISIN, sonst leer."""
    isin = (isin or "").strip().upper()
    if not isin_valid(isin):
        return {"isin": "", "wkn": ""}
    return {"isin": isin, "wkn": wkn_from_isin(isin)}
