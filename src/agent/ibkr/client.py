"""IBKR-Client – in eigenem Thread mit eigener Event-Loop.

Alle ib_insync-Calls laufen in isolierten Threads mit eigener asyncio-Loop,
um Konflikte mit der uvicorn-Loop zu vermeiden.
"""
import logging, threading, asyncio
from dataclasses import dataclass, field

log = logging.getLogger(__name__)


@dataclass
class Position:
    symbol:         str
    quantity:       float
    avg_cost:       float
    current_price:  float
    market_value:   float
    unrealized_pnl: float
    weight:         float
    currency:       str
    sector:         str = ""
    conid:          int = 0      # IBKR-Contract-ID (global eindeutig)
    isin:           str = ""
    wkn:            str = ""
    exchange:       str = ""
    metrics:        dict = field(default_factory=dict)   # Kennzahlen aus der Kurshistorie


class IBKRResult:
    def __init__(self):
        self.positions: list[Position] = []
        self.account:   dict           = {}
        self.error:     str | None     = None
        self.history:   dict           = {}    # symbol -> [(date, close)] (+ Benchmark)
        self.benchmark: str            = ""
        self.history_errors: list      = []


@dataclass
class OrderResult:
    symbol:     str
    action:     str
    quantity:   float
    fill_price: float | None = None
    status:     str          = "PENDING"
    error:      str | None   = None
    commission: float | None = None


# ── Portfolio-Worker ──────────────────────────────────────────────────────────

def _portfolio_worker(host, port, client_id, result, done, benchmark=""):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_fetch_portfolio(host, port, client_id, result, benchmark))
    except Exception as e:
        result.error = str(e)
        log.error(f"Portfolio-Worker Fehler: {e}", exc_info=True)
    finally:
        loop.close()
        done.set()


async def _fetch_portfolio(host, port, client_id, result, benchmark=""):
    from ib_insync import IB
    ib = IB()
    try:
        await ib.connectAsync(host, port, clientId=client_id,
                              readonly=True, timeout=15)
        log.info(f"IBKR verbunden: {host}:{port}")

        for v in ib.accountValues():
            if v.tag in ("NetLiquidation", "TotalCashValue",
                         "UnrealizedPnL", "RealizedPnL"):
                try:
                    result.account[v.tag] = float(v.value)
                except ValueError:
                    pass

        portfolio = ib.portfolio()
        if not portfolio:
            log.warning("Portfolio leer")
            return

        from ..identifiers import clean_ids
        positions = []
        for item in portfolio:
            c = item.contract
            isin, sector = "", ""
            try:   # ISIN und Branche stehen in den Contract-Details
                details = await asyncio.wait_for(ib.reqContractDetailsAsync(c), 10)
                for d in details[:1]:
                    isin = next((x.value for x in (d.secIdList or [])
                                 if x.tag == "ISIN"), "")
                    sector = d.industry or d.category or ""
            except Exception as e:
                log.warning(f"[{c.symbol}] ISIN nicht abrufbar: {e}")
            ids = clean_ids(isin)
            positions.append(Position(
                symbol=c.symbol, quantity=item.position,
                avg_cost=item.averageCost, current_price=item.marketPrice,
                market_value=item.marketValue, unrealized_pnl=item.unrealizedPNL,
                weight=0.0, currency=c.currency,
                conid=int(c.conId or 0), isin=ids["isin"], wkn=ids["wkn"],
                exchange=c.primaryExchange or c.exchange or "", sector=sector,
            ))

        total = sum(abs(p.market_value) for p in positions)
        if total > 0:
            for p in positions:
                p.weight = abs(p.market_value) / total

        result.positions = positions
        log.info(f"{len(positions)} Positionen geladen")
        await _fetch_history(ib, portfolio, benchmark, result)
    finally:
        if ib.isConnected():
            ib.disconnect()


async def _bars(ib, contract) -> list[tuple]:
    """Ein Jahr Tagesschlusskurse [(date, close)]."""
    from ib_insync import Contract
    c = Contract(conId=contract.conId, exchange=contract.exchange or "SMART",
                 currency=contract.currency, secType=contract.secType, symbol=contract.symbol)
    if not c.exchange or c.exchange == "":
        c.exchange = "SMART"
    bars = await asyncio.wait_for(ib.reqHistoricalDataAsync(
        c, endDateTime="", durationStr="1 Y", barSizeSetting="1 day",
        whatToShow="ADJUSTED_LAST", useRTH=True, formatDate=1), 25)
    return [(b.date if hasattr(b.date, "year") else b.date.date(), float(b.close)) for b in bars or []]


async def _fetch_history(ib, portfolio, benchmark, result):
    """Kurshistorie je Position (+ Benchmark); Fehler einzelner Titel sind nicht fatal
    (z.B. fehlendes Marktdaten-Abo)."""
    from ib_insync import Stock
    for item in portfolio:
        sym = item.contract.symbol
        try:
            series = await _bars(ib, item.contract)
            if series:
                result.history[sym] = series
            else:
                result.history_errors.append(f"{sym}: keine Daten")
        except Exception as e:
            result.history_errors.append(f"{sym}: {type(e).__name__}")
            log.warning(f"[{sym}] Kurshistorie nicht abrufbar: {e}")
        await asyncio.sleep(0.25)       # IBKR-Pacing
    if benchmark:
        try:
            c = Stock(benchmark, "SMART", "USD")
            await ib.qualifyContractsAsync(c)
            series = await _bars(ib, c)
            if series:
                result.history[f"__BENCH__{benchmark}"] = series
                result.benchmark = benchmark
        except Exception as e:
            result.history_errors.append(f"Benchmark {benchmark}: {type(e).__name__}")
            log.warning(f"Benchmark {benchmark} nicht abrufbar: {e}")


# ── Order-Worker ──────────────────────────────────────────────────────────────

def _order_worker(host, port, client_id, symbol, action,
                  quantity, dry_run, result, done, conid=0):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(
            _place_order(host, port, client_id, symbol, action,
                         quantity, dry_run, result, conid)
        )
    except Exception as e:
        result.error = str(e)
        log.error(f"Order-Worker Fehler: {e}", exc_info=True)
    finally:
        loop.close()
        done.set()


async def _place_order(host, port, client_id, symbol, action,
                       quantity, dry_run, result, conid=0):
    from ib_insync import IB, Stock, Contract, MarketOrder

    if dry_run:
        log.info(f"[DRY-RUN] {action} {quantity:.0f}x {symbol} – keine echte Order")
        result.status     = "DRY_RUN"
        result.fill_price = None
        return

    ib = IB()
    try:
        # Order-Client braucht eigene Client-ID (nicht readonly!)
        await ib.connectAsync(host, port, clientId=client_id + 10,
                              readonly=False, timeout=15)

        # conId macht das Wertpapier eindeutig (kein Verwechseln gleicher Ticker an
        # verschiedenen Boersen); ohne conId faellt es auf Symbol/SMART/USD zurueck
        contract = Contract(conId=conid) if conid else Stock(symbol, "SMART", "USD")
        await ib.qualifyContractsAsync(contract)
        log.info(f"Order-Contract: {symbol} conId={contract.conId} {contract.primaryExchange}")

        order    = MarketOrder(action, quantity)
        trade    = ib.placeOrder(contract, order)

        # Auf Fill warten (max 30s)
        for _ in range(30):
            await asyncio.sleep(1)
            if trade.isDone():
                break

        if trade.fills:
            result.fill_price = trade.fills[-1].execution.avgPrice
            comm = [f.commissionReport.commission for f in trade.fills
                    if f.commissionReport and f.commissionReport.commission < 1e9]
            result.commission = sum(comm) if comm else None
            result.status     = "FILLED"
            log.info(f"Order gefüllt: {action} {quantity}x {symbol} "
                     f"@ {result.fill_price}")
        else:
            result.status = "SUBMITTED"
            log.warning(f"Order submitted aber noch kein Fill: {symbol}")

    finally:
        if ib.isConnected():
            ib.disconnect()


# ── ISIN-Lookup ───────────────────────────────────────────────────────────────

def _isin_worker(host, port, client_id, symbols, result, done):
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        loop.run_until_complete(_lookup_isins(host, port, client_id, symbols, result))
    except Exception as e:
        log.warning(f"ISIN-Lookup Fehler: {e}")
    finally:
        loop.close()
        done.set()


async def _lookup_isins(host, port, client_id, symbols, result):
    from ib_insync import IB, Stock
    ib = IB()
    try:
        await ib.connectAsync(host, port, clientId=client_id, readonly=True, timeout=10)
        for sym in symbols:
            try:
                details = await asyncio.wait_for(
                    ib.reqContractDetailsAsync(Stock(sym, "SMART", "USD")), 10)
            except Exception as e:
                log.info(f"[{sym}] IBKR kennt das Symbol nicht: {e}")
                continue
            found = {x.value: d.contract.conId for d in details
                     for x in (d.secIdList or []) if x.tag == "ISIN"}
            if len(found) == 1:                       # nur eindeutige Treffer
                isin, conid = next(iter(found.items()))
                result[sym] = {"isin": isin, "conid": int(conid)}
            elif found:
                log.info(f"[{sym}] mehrdeutig ({len(found)} ISINs) – uebersprungen")
    finally:
        if ib.isConnected():
            ib.disconnect()


# ── Public Interface ──────────────────────────────────────────────────────────

class IBKRClient:
    def __init__(self, host: str, port: int, client_id: int, benchmark: str = ""):
        self.host = host; self.port = port; self.client_id = client_id
        self.benchmark = benchmark

    async def fetch(self) -> IBKRResult:
        result = IBKRResult()
        done   = threading.Event()
        t = threading.Thread(
            target=_portfolio_worker,
            args=(self.host, self.port, self.client_id, result, done, self.benchmark),
            daemon=True,
        )
        t.start()
        await asyncio.get_event_loop().run_in_executor(None, done.wait)
        return result

    async def lookup_isins(self, symbols: list[str]) -> dict:
        """Best-Effort: {symbol: {isin, conid}} fuer eindeutig aufloesbare US-Symbole."""
        result: dict = {}
        done = threading.Event()
        threading.Thread(
            target=_isin_worker,
            args=(self.host, self.port, self.client_id + 20, symbols, result, done),
            daemon=True).start()
        await asyncio.get_event_loop().run_in_executor(None, done.wait, 90)
        return result

    async def place_order(self, symbol: str, action: str,
                          quantity: float, dry_run: bool,
                          conid: int = 0) -> OrderResult:
        result = OrderResult(symbol=symbol, action=action, quantity=quantity)
        done   = threading.Event()
        t = threading.Thread(
            target=_order_worker,
            args=(self.host, self.port, self.client_id,
                  symbol, action, quantity, dry_run, result, done, conid),
            daemon=True,
        )
        t.start()
        await asyncio.get_event_loop().run_in_executor(None, done.wait)
        return result
