"""Orderdimensionierung: aus Depotwert, Risiko-Limits und Barmitteln eine Stueckzahl berechnen."""
import math


def size_order(action: str, price: float, held_qty: float, position_value: float,
               nav: float, cash: float, max_position_pct: float,
               max_risk_pct: float, stop_loss_pct: float) -> dict:
    """Liefert {'quantity', 'value', 'steps': [Erklaerungen], 'blocked': Grund|None}.

    BUY : Betrag so, dass ein Stopp-Verlust (stop_loss_pct) hoechstens max_risk_pct vom Depot
          kostet -> nav * risk% / stop%. Begrenzt durch Restplatz bis max_position_pct und Cash.
    SELL: gesamte Position.
    """
    steps = []
    if price <= 0:
        return {"quantity": 0, "value": 0.0, "steps": steps, "blocked": "Kein gueltiger Kurs vorhanden"}
    action = action.upper()
    if action == "SELL":
        qty = math.floor(abs(held_qty)) if held_qty > 0 else 0
        steps.append(f"Verkauf der gesamten Position: {qty} Stueck")
        return {"quantity": qty, "value": qty * price, "steps": steps,
                "blocked": None if qty else "Keine Position zum Verkaufen"}
    if nav <= 0:
        return {"quantity": 0, "value": 0.0, "steps": steps, "blocked": "Depotwert unbekannt"}
    risk_amount = nav * max_risk_pct / 100
    by_risk = risk_amount / (stop_loss_pct / 100) if stop_loss_pct > 0 else nav * max_position_pct / 100
    steps.append(f"Risiko-Budget: {max_risk_pct:g} % von {nav:,.0f} = {risk_amount:,.0f} bei {stop_loss_pct:g} % Stopp "
                 f"-> max. Betrag {by_risk:,.0f}")
    headroom = nav * max_position_pct / 100 - position_value
    steps.append(f"Platz bis Positionslimit ({max_position_pct:g} %): {max(headroom, 0):,.0f}")
    steps.append(f"Verfuegbares Cash: {max(cash, 0):,.0f}")
    amount = min(by_risk, headroom, cash)
    qty = math.floor(amount / price) if amount > 0 else 0
    steps.append(f"Betrag {max(amount, 0):,.0f} / Kurs {price:,.2f} = {qty} Stueck")
    reason = None
    if qty < 1:
        reason = ("Positionslimit bereits erreicht" if headroom <= 0 else
                  "Nicht genug Cash" if cash < price else "Betrag unter einem Stueck")
    return {"quantity": qty, "value": qty * price, "steps": steps, "blocked": reason}
