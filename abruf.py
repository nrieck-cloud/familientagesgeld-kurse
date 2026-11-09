#!/usr/bin/env python3
"""
Datendienst für das Familien-Aktiendepot (Familientagesgeld).

Läuft als GitHub Action und legt öffentliche Marktdaten als JSON-Dateien im Zweig `daten` ab.
Die HTML-Datei lädt sie von raw.githubusercontent.com (dort ist der Abruf aus dem Browser erlaubt).
Es werden ausschließlich Marktdaten verarbeitet, keine persönlichen Daten.

  python3 abruf.py stuendlich  OUT   → kurse.json         (Kurse, Kennzahlen, 1 Jahr Tageskurse)
  python3 abruf.py taeglich    OUT   → historie.json      (10 Jahre Tageskurse, dividendenbereinigt)
                                       fundamente.json    (SEC-Bilanzdaten der US-Werte)
                                       makro.json         (FRED: Zinsen, Inflation, Arbeitsmarkt, Spreads)
                                       institutionell.json (13F großer Investoren, Insider-Käufe, Kongress)

Quellen: Yahoo Finance (inoffiziell), SEC EDGAR, FRED (St. Louis Fed), House Clerk.
Nur Python-Standardbibliothek; für Kongress-PDFs wird `pdftotext` (poppler-utils) genutzt, falls vorhanden.
"""
import datetime, gzip, http.cookiejar, io, json, math, os, re, subprocess, sys, tempfile, time, urllib.error, urllib.parse, urllib.request, zipfile

UA = "Mozilla/5.0"  # Yahoo drosselt lange Browser-Kennungen ohne echten Browser
# Die SEC verlangt Name und E-Mail als Kennung (keine Weiterleitungsadressen). Ohne Kennung bleiben die
# SEC-Daten auf dem letzten Stand; Kurse, Makro und Kongress laufen trotzdem.
SEC_UA = (os.environ.get("SEC_USER_AGENT") or "").strip()

US = ["NVDA","MSFT","AAPL","GOOGL","AMZN","META","AVGO","TSLA","BRK-B","JPM","LLY","WMT","V","ORCL","MA","XOM","NFLX","COST","JNJ","PLTR",
      "HD","PG","ABBV","BAC","UNH","AMD","KO","CRM","CVX","GE","CSCO","IBM","MU","WFC","PM","MS","GS","TMUS","MRK","AXP","LIN","TMO","ABT",
      "MCD","PEP","DIS","INTU","QCOM","TXN","CAT","ISRG","NOW","UBER","BKNG","ADBE","AMAT","RTX","SCHW","BX","SPGI"]
# DAX und ETFs nur für die Bewertung des eigenen Depots (keine Analyse)
DAX = ["SAP.DE","SIE.DE","ALV.DE","DTE.DE","AIR.DE","RHM.DE","MUV2.DE","SHL.DE","MBG.DE","DB1.DE","IFX.DE","BMW.DE","BAS.DE","DBK.DE","ENR.DE",
       "EOAN.DE","ADS.DE","DHL.DE","VOW3.DE","MRK.DE","HEI.DE","RWE.DE","BAYN.DE","CBK.DE","HNR1.DE","VNA.DE","BEI.DE","SY1.DE","MTX.DE","FRE.DE",
       "HEN3.DE","CON.DE","QIA.DE","PAH3.DE","P911.DE","SRT3.DE","ZAL.DE","G1A.DE","BNR.DE","FME.DE"]
ETF = ["SPY","QQQ","VOO","VTI","IWM","DIA","VEA","VWO","EEM","GLD","TLT","SCHD","EUNL.DE","VWCE.DE","SXR8.DE","IS3N.DE","EXS1.DE","XDWT.DE",
       "IUSN.DE","EXSA.DE","EQQQ.DE","XDWD.DE","SPPW.DE","4GLD.DE"]
IDX = ["^GSPC","^NDX","^GDAXI","^VIX","^TNX","DX-Y.NYB","GC=F","CL=F","BTC-USD"]
SEKTOR_ETF = {"XLK": "Technologie", "XLF": "Finanzen", "XLV": "Gesundheit", "XLY": "Zykl. Konsum", "XLP": "Basiskonsum", "XLE": "Energie",
              "XLI": "Industrie", "XLB": "Grundstoffe", "XLU": "Versorger", "XLRE": "Immobilien", "XLC": "Kommunikation"}
FRED = {"DGS10": "US-Staatsanleihe 10 J. (%)", "DGS2": "US-Staatsanleihe 2 J. (%)", "DGS3MO": "US-Geldmarkt 3 M. (%)", "T10Y2Y": "Zinskurve 10 J. − 2 J. (Pp.)",
        "FEDFUNDS": "US-Leitzins (%)", "ECBDFR": "EZB-Einlagenzins (%)", "CPIAUCSL": "US-Verbraucherpreise (Index)", "CP0000EZ19M086NEST": "Euroraum-Verbraucherpreise (Index)",
        "UNRATE": "US-Arbeitslosenquote (%)", "BAMLH0A0HYM2": "Risikoaufschlag Hochzinsanleihen (Pp.)", "ICSA": "US-Erstanträge Arbeitslosenhilfe", "INDPRO": "US-Industrieproduktion (Index)"}
INVESTOREN = {"0001067983": "Berkshire Hathaway (Buffett)", "0001336528": "Pershing Square (Ackman)", "0001649339": "Scion (Burry)",
              "0001061768": "Baupost (Klarman)", "0001656456": "Appaloosa (Tepper)", "0001536411": "Duquesne (Druckenmiller)",
              "0001350694": "Bridgewater (Dalio)", "0001037389": "Renaissance Technologies"}


def log(msg):
    print(datetime.datetime.utcnow().strftime("%H:%M:%S"), msg, flush=True)


def http_get(url, headers=None, tries=4, opener=None, raw=False):
    h = {"User-Agent": UA, "Accept": "*/*", "Accept-Encoding": "gzip"}
    h.update(headers or {})
    last = None
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers=h)
            with (opener.open(req, timeout=40) if opener else urllib.request.urlopen(req, timeout=40)) as r:
                b = r.read()
                if r.headers.get("Content-Encoding") == "gzip":
                    b = gzip.decompress(b)
                return b if raw else b.decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            last = e
            if e.code in (400, 401, 403, 404) and i >= 1:
                raise
            time.sleep((15 if e.code == 429 else 2) * (i + 1))
            if e.code == 429 and "query1" in url:
                url = url.replace("query1", "query2")
        except Exception as e:  # Netzfehler
            last = e
            time.sleep(2 * (i + 1))
    raise last


# ---------------------------------------------------------------- Yahoo
class Yahoo:
    def __init__(self):
        self.op = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
        self.crumb = None

    def get(self, url):
        return http_get(url, opener=self.op)

    def sitzung(self):
        try:
            self.op.open(urllib.request.Request("https://fc.yahoo.com", headers={"User-Agent": UA}), timeout=20)
        except Exception:
            pass  # 404, setzt aber das Cookie
        c = self.get("https://query1.finance.yahoo.com/v1/test/getcrumb")
        if not c or len(c) > 40 or "<" in c:
            raise RuntimeError("kein Sitzungsschlüssel")
        self.crumb = c

    def quotes(self, symbole):
        out = {}
        for i in range(0, len(symbole), 40):
            url = ("https://query1.finance.yahoo.com/v7/finance/quote?symbols=" + urllib.parse.quote(",".join(symbole[i:i + 40]))
                   + "&crumb=" + urllib.parse.quote(self.crumb))
            for q in json.loads(self.get(url)).get("quoteResponse", {}).get("result", []):
                out[q["symbol"]] = q
            time.sleep(0.5)
        return out

    def spark(self, symbole, rng="1y"):
        url = "https://query1.finance.yahoo.com/v7/finance/spark?symbols=" + urllib.parse.quote(",".join(symbole)) + "&range=" + rng + "&interval=1d"
        out = {}
        for x in json.loads(self.get(url)).get("spark", {}).get("result", []) or []:
            try:
                out[x["symbol"]] = x["response"][0]
            except (KeyError, IndexError, TypeError):
                pass
        return out

    def chart(self, sym, rng="1y", adj=False):
        url = ("https://query1.finance.yahoo.com/v8/finance/chart/" + urllib.parse.quote(sym) + "?range=" + rng + "&interval=1d"
               + ("&events=div%2Csplit&includeAdjustedClose=true" if adj else ""))
        return json.loads(self.get(url))["chart"]["result"][0]


def reihe(res, adj=False):
    q = res["indicators"]["quote"][0]
    src = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") if adj else None
    c, t = [], []
    for v, ts in zip(src or q.get("close", []), res.get("timestamp", [])):
        if v is not None and v > 0:
            c.append(v); t.append(ts)
    return c, t


def kennzahlen(res):
    m = res.get("meta", {})
    c, t = reihe(res)
    if len(c) < 20:
        return None
    last = m.get("regularMarketPrice") or c[-1]
    def perf(n):
        i = len(c) - 1 - n
        return last / c[i] - 1 if i >= 0 else None
    hoch, tief = max(c + [last]), min(c + [last])
    peak, maxdd = c[0], 0.0
    for v in c:
        peak = max(peak, v); maxdd = min(maxdd, v / peak - 1)
    jahr, ytd = datetime.date.today().year, None
    for i, ts in enumerate(t):
        if datetime.datetime.utcfromtimestamp(ts).year == jahr:
            ytd = last / (c[i - 1] if i > 0 else c[i]) - 1
            break
    r = [math.log(c[i] / c[i - 1]) for i in range(1, len(c))]
    mu = sum(r) / len(r)
    vola = math.sqrt(sum((x - mu) ** 2 for x in r) / (len(r) - 1)) * math.sqrt(252) if len(r) > 2 else None
    rsi = None
    if len(c) > 15:
        g = [max(c[i] - c[i - 1], 0) for i in range(1, len(c))]
        l = [max(c[i - 1] - c[i], 0) for i in range(1, len(c))]
        ag, al = sum(g[:14]) / 14, sum(l[:14]) / 14
        for i in range(14, len(g)):
            ag = (ag * 13 + g[i]) / 14; al = (al * 13 + l[i]) / 14
        rsi = 100.0 if al == 0 else 100 - 100 / (1 + ag / al)
    sma50 = sum(c[-50:]) / 50 if len(c) >= 50 else None
    sma200 = sum(c[-200:]) / 200 if len(c) >= 200 else None
    return {
        "kurs": round(last, 4), "vortag": m.get("chartPreviousClose"), "hoch52": round(hoch, 4), "tief52": round(tief, 4),
        "abstandHoch": last / hoch - 1, "abstandTief": last / tief - 1, "maxDD": maxdd,
        "p1w": perf(5), "p1m": perf(21), "p3m": perf(63), "p6m": perf(126), "ytd": ytd, "p1j": last / c[0] - 1,
        "vola": vola, "rsi": rsi, "sma50": sma50, "sma200": sma200,
        "ueber200": (last > sma200) if sma200 else None, "abstand200": (last / sma200 - 1) if sma200 else None,
        "verlauf": [round(c[k], 2) for k in range(len(c) - 1, -1, -5)][::-1],
        "taeglich": [round(v, 2) for v in c], "t0": t[0] * 1000, "tage": [round((x - t[0]) / 86400) for x in t],
    }


def zeile(sym, res, q):
    k = kennzahlen(res)
    if not k:
        return None
    m = res.get("meta", {})
    heute = q.get("regularMarketChangePercent")
    if heute is None and k["vortag"]:
        heute = (k["kurs"] / k["vortag"] - 1) * 100
    return {
        "symbol": sym, "name": q.get("longName") or q.get("shortName") or m.get("longName") or m.get("shortName") or sym,
        "waehrung": m.get("currency") or q.get("currency"), "typ": q.get("quoteType") or m.get("instrumentType"),
        "boerse": q.get("fullExchangeName") or m.get("fullExchangeName"),
        "heute": heute / 100 if heute is not None else None, "boersenwert": q.get("marketCap"),
        "kgv": q.get("trailingPE"), "kgvVoraus": q.get("forwardPE"), "kbv": q.get("priceToBook"), "eps": q.get("epsTrailingTwelveMonths"),
        "epsVoraus": q.get("epsForward"), "aktien": q.get("sharesOutstanding"), "buchwert": q.get("bookValue"),
        "dividende": q.get("trailingAnnualDividendYield") or (q.get("dividendYield") / 100 if q.get("dividendYield") else None),
        "dividendeJeAktie": q.get("trailingAnnualDividendRate"), "ziel": q.get("targetPriceMean") if "targetPriceMean" in q else None,
        "empfehlung": q.get("averageAnalystRating"), "volumen": q.get("regularMarketVolume") or m.get("regularMarketVolume"),
        "zeitKurs": (q.get("regularMarketTime") or m.get("regularMarketTime") or 0) * 1000, "k": k,
    }


def lade_alt(out, name):
    try:
        with open(os.path.join(out, name), encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def schreibe(out, name, daten):
    os.makedirs(out, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=out, suffix=".tmp")
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        json.dump(daten, f, separators=(",", ":"), ensure_ascii=False)
    os.replace(tmp, os.path.join(out, name))
    log("%s: %d KB" % (name, os.path.getsize(os.path.join(out, name)) // 1024))


def stuendlich(out):
    y = Yahoo()
    alle = list(dict.fromkeys(US + DAX + ETF + IDX + list(SEKTOR_ETF)))
    quotes = {}
    try:
        y.sitzung()
        quotes = y.quotes(alle + ["EURUSD=X"])
    except Exception as e:
        log("Quote-Abruf ohne Erfolg (%s), weiter mit Kursverläufen" % e)
    charts = {}
    for i in range(0, len(alle), 20):
        teil = alle[i:i + 20]
        try:
            charts.update(y.spark(teil))
        except Exception as e:
            log("Spark %d: %s, einzeln" % (i // 20 + 1, e))
            for s in teil:
                try:
                    charts[s] = y.chart(s); time.sleep(0.4)
                except Exception:
                    pass
        time.sleep(0.8)
    alt = (lade_alt(out, "kurse.json") or {}).get("werte", {})
    zeilen = {}
    for s in alle:
        z = zeile(s, charts[s], quotes.get(s, {})) if s in charts else None
        if z:
            # Kennzahlen, die nur der Quote-Abruf liefert, aus dem letzten Stand übernehmen
            if not quotes and s in alt:
                for k in ("boersenwert", "kgv", "kgvVoraus", "kbv", "eps", "epsVoraus", "aktien", "buchwert", "dividende", "dividendeJeAktie", "name", "empfehlung"):
                    if z.get(k) is None:
                        z[k] = alt[s].get(k)
            zeilen[s] = z
        elif s in alt:
            z = dict(alt[s]); z["alt"] = True; zeilen[s] = z
    if sum(1 for z in zeilen.values() if not z.get("alt")) < len(alle) * 0.5:
        log("Zu wenige frische Kurse, kurse.json bleibt unverändert")
        return 1
    us_ok = sorted([s for s in US if s in zeilen], key=lambda s: -(zeilen[s].get("boersenwert") or 0))
    eurusd = (quotes.get("EURUSD=X") or {}).get("regularMarketPrice")
    if not eurusd:
        try:
            eurusd = y.chart("EURUSD=X")["meta"]["regularMarketPrice"]
        except Exception:
            eurusd = None
    daten = {"version": 3, "zeit": int(time.time() * 1000), "quelle": "Yahoo Finance über GitHub",
             "mitBoersenwert": any(z.get("boersenwert") for z in zeilen.values()),
             "fx": {"USD": (1 / eurusd) if eurusd else ((lade_alt(out, "kurse.json") or {}).get("fx") or {}).get("USD"), "EUR": 1},
             "listen": {"us20": us_ok[:20], "us": us_ok, "dax": [s for s in DAX if s in zeilen], "etf": [s for s in ETF if s in zeilen],
                        "idx": [s for s in IDX if s in zeilen], "sektor": [s for s in SEKTOR_ETF if s in zeilen]},
             "sektorNamen": SEKTOR_ETF, "werte": zeilen}
    schreibe(out, "kurse.json", daten)
    return 0


# ---------------------------------------------------------------- 10 Jahre Historie
def historie(out):
    y = Yahoo()
    syms = US + ["SPY", "QQQ", "^GSPC", "^NDX", "^VIX", "^GDAXI", "TLT", "GLD"] + list(SEKTOR_ETF)
    alt = (lade_alt(out, "historie.json") or {}).get("werte", {})
    werte = {}
    for s in syms:
        try:
            c, t = reihe(y.chart(s, "10y", adj=True), adj=True)
            if len(c) > 250:
                t0 = t[0]
                werte[s] = {"t0": t0 * 1000, "tage": [round((x - t0) / 86400) for x in t], "c": [round(v, 3 if v < 50 else 2) for v in c]}
        except Exception as e:
            log("Historie %s: %s" % (s, e))
            if s in alt:
                werte[s] = alt[s]
        time.sleep(0.35)
    if len(werte) < len(syms) * 0.5:
        log("Historie unvollständig, bleibt unverändert"); return 1
    schreibe(out, "historie.json", {"zeit": int(time.time() * 1000), "quelle": "Yahoo Finance, dividendenbereinigt", "werte": werte})
    return 0


# ---------------------------------------------------------------- SEC Bilanzdaten
SEC_TAGS = {
    "umsatz": ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax", "InterestAndDividendIncomeOperating"],
    "brutto": ["GrossProfit"], "ebit": ["OperatingIncomeLoss"], "gewinn": ["NetIncomeLoss", "ProfitLoss"],
    "eps": ["EarningsPerShareDiluted", "EarningsPerShareBasic"], "ocf": ["NetCashProvidedByUsedInOperatingActivities"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
    "dividenden": ["PaymentsOfDividendsCommonStock", "PaymentsOfDividends"], "rueckkauf": ["PaymentsForRepurchaseOfCommonStock"],
    "aktienGew": ["WeightedAverageNumberOfDilutedSharesOutstanding"],
    "aktiva": ["Assets"], "passiva": ["Liabilities"], "eigenkapital": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "umlaufAktiva": ["AssetsCurrent"], "kurzVerb": ["LiabilitiesCurrent"], "kasse": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"],
    "schuldenLang": ["LongTermDebtNoncurrent", "LongTermDebt"], "schuldenKurz": ["LongTermDebtCurrent", "DebtCurrent"],
    "gewinnruecklage": ["RetainedEarningsAccumulatedDeficit"], "aktienAus": ["CommonStockSharesOutstanding"],
}
INSTANT = {"aktiva", "passiva", "eigenkapital", "umlaufAktiva", "kurzVerb", "kasse", "schuldenLang", "schuldenKurz", "gewinnruecklage", "aktienAus"}


def sektor_aus_sic(sic):
    try:
        n = int(sic)
    except (TypeError, ValueError):
        return "Sonstige"
    treffer = "Industrie" if 3000 <= n < 4000 else "Sonstige"
    # Spätere, engere Bereiche überschreiben frühere, weitere
    for lo, hi, name in [(100, 1499, "Grundstoffe"), (1300, 1399, "Energie"), (2000, 2199, "Basiskonsum"), (2800, 2829, "Grundstoffe"),
                         (2830, 2836, "Gesundheit"), (2840, 2844, "Basiskonsum"), (2900, 2999, "Energie"), (3570, 3579, "Technologie"), (3600, 3699, "Technologie"),
                         (3710, 3719, "Zykl. Konsum"), (3720, 3729, "Industrie"), (3800, 3851, "Gesundheit"), (4800, 4899, "Kommunikation"), (4900, 4999, "Versorger"),
                         (5000, 5199, "Industrie"), (5200, 5999, "Zykl. Konsum"), (5400, 5499, "Basiskonsum"), (6000, 6799, "Finanzen"), (7370, 7379, "Technologie"),
                         (7380, 7389, "Dienstleistungen"), (7800, 7999, "Kommunikation"), (8000, 8099, "Gesundheit")]:
        if lo <= n <= hi:
            treffer = name
    return treffer


def sec_json(url):
    return json.loads(http_get(url, headers={"User-Agent": SEC_UA, "Host": urllib.parse.urlparse(url).netloc}))


def fakten(facts, tags, instant):
    """Jahres- und Quartalswerte; von mehreren möglichen Kennzahlen gewinnt die mit dem jüngsten Stand."""
    gaap = facts.get("facts", {}).get("us-gaap", {})
    best, best_key = {"j": [], "q": []}, ("", 0)
    for tag in tags:
        if tag not in gaap:
            continue
        einheiten = gaap[tag].get("units", {})
        eintraege = einheiten.get("USD") or einheiten.get("USD/shares") or einheiten.get("shares") or next(iter(einheiten.values()), [])
        jahr, quartal = {}, {}
        for e in eintraege:
            if e.get("form") not in ("10-K", "10-Q", "10-K/A", "10-Q/A") or not e.get("end"):
                continue
            end, filed = e["end"], e.get("filed", "")
            if instant:
                if e.get("fp") == "FY" and e.get("form", "").startswith("10-K"):
                    if end not in jahr or filed > jahr[end][1]:
                        jahr[end] = (e["val"], filed)
                if end not in quartal or filed > quartal[end][1]:
                    quartal[end] = (e["val"], filed)
                continue
            if not e.get("start"):
                continue
            tage = (datetime.date.fromisoformat(end) - datetime.date.fromisoformat(e["start"])).days
            ziel = jahr if 350 <= tage <= 380 else quartal if 80 <= tage <= 100 else None
            if ziel is not None and (end not in ziel or filed > ziel[end][1]):
                ziel[end] = (e["val"], filed)
        if not jahr and not quartal:
            continue
        key = (max(list(jahr) + list(quartal)), len(jahr))
        if key > best_key:
            best_key = key
            best = {"j": [[k, v[0]] for k, v in sorted(jahr.items())[-8:]], "q": [[k, v[0]] for k, v in sorted(quartal.items())[-12:]], "tag": tag}
    return best


def fundamente(out):
    if not SEC_UA:
        log("Keine SEC-Kennung (Variable SEC_USER_AGENT): Bilanzdaten bleiben auf dem letzten Stand"); return 0
    tick = sec_json("https://www.sec.gov/files/company_tickers.json")
    cik = {v["ticker"].upper(): str(v["cik_str"]).zfill(10) for v in tick.values()}
    alt = (lade_alt(out, "fundamente.json") or {}).get("werte", {})
    werte = {}
    for s in US:
        c = cik.get(s.upper()) or cik.get(s.replace("-", ".").upper())
        if not c:
            log("SEC: kein CIK für " + s); continue
        try:
            f = sec_json("https://data.sec.gov/api/xbrl/companyfacts/CIK%s.json" % c)
            time.sleep(0.15)
            sub = sec_json("https://data.sec.gov/submissions/CIK%s.json" % c)
            w = {"cik": c, "name": sub.get("name"), "sic": sub.get("sic"), "sicText": sub.get("sicDescription"), "sektor": sektor_aus_sic(sub.get("sic")),
                 "gj": sub.get("fiscalYearEnd")}
            for k, tags in SEC_TAGS.items():
                w[k] = fakten(f, tags, k in INSTANT)
            # Letzte Insider-Meldungen (Form 4) für den Insider-Teil
            rec = sub.get("filings", {}).get("recent", {})
            w["form4"] = [[rec["accessionNumber"][i], rec["filingDate"][i], rec["primaryDocument"][i]] for i in range(len(rec.get("form", [])))
                          if rec["form"][i] == "4"][:25]
            werte[s] = w
        except Exception as e:
            log("SEC %s: %s" % (s, e))
            if s in alt:
                werte[s] = alt[s]
        time.sleep(0.15)
    if len(werte) < len(US) * 0.5:
        log("Fundamente unvollständig, bleibt unverändert"); return 1
    schreibe(out, "fundamente.json", {"zeit": int(time.time() * 1000), "quelle": "SEC EDGAR (XBRL companyfacts)", "werte": werte})
    return 0


# ---------------------------------------------------------------- Makro (FRED ohne Schlüssel)
def curl_get(url):
    """FRED lässt Pythons eigenen Abruf ins Leere laufen, curl dagegen durch."""
    for i in range(3):
        r = subprocess.run(["curl", "-sS", "--max-time", "40", "-f", url], capture_output=True, text=True)
        if r.returncode == 0 and r.stdout.startswith(("DATE", "observation_date")):
            return r.stdout
        time.sleep(3 * (i + 1))
    raise RuntimeError("curl %s: %s" % (r.returncode, r.stderr.strip()[:120]))


def makro(out):
    reihen, start = {}, (datetime.date.today() - datetime.timedelta(days=365 * 15)).isoformat()
    for sid, name in FRED.items():
        try:
            txt = curl_get("https://fred.stlouisfed.org/graph/fredgraph.csv?id=%s&cosd=%s" % (sid, start))
            pts = []
            for line in txt.splitlines()[1:]:
                d, _, v = line.partition(",")
                try:
                    pts.append([d, float(v)])
                except ValueError:
                    pass
            if len(pts) > 400:  # tägliche Reihen auf Wochenwerte verdichten
                pts = [p for i, p in enumerate(pts) if i % 5 == 0 or i == len(pts) - 1]
            reihen[sid] = {"name": name, "d": pts}
        except Exception as e:
            log("FRED %s: %s" % (sid, e))
        time.sleep(0.3)
    if len(reihen) < len(FRED) * 0.5:
        log("Makro unvollständig, bleibt unverändert"); return 1
    schreibe(out, "makro.json", {"zeit": int(time.time() * 1000), "quelle": "FRED, Federal Reserve Bank of St. Louis", "reihen": reihen})
    return 0


# ---------------------------------------------------------------- Institutionell
def text(el, pfad):
    x = el.find(pfad)
    return x.text.strip() if x is not None and x.text else None


def dreizehn_f(cik):
    import xml.etree.ElementTree as ET
    sub = sec_json("https://data.sec.gov/submissions/CIK%s.json" % cik)
    rec = sub["filings"]["recent"]
    idx = [i for i, f in enumerate(rec["form"]) if f == "13F-HR"][:2]
    berichte = []
    for i in idx:
        acc = rec["accessionNumber"][i].replace("-", "")
        basis = "https://www.sec.gov/Archives/edgar/data/%d/%s/" % (int(cik), acc)
        liste = sec_json(basis + "index.json")
        xmls = [x["name"] for x in liste["directory"]["item"] if x["name"].lower().endswith(".xml") and "primary_doc" not in x["name"].lower()]
        if not xmls:
            continue
        time.sleep(0.15)
        root = ET.fromstring(http_get(basis + xmls[0], headers={"User-Agent": SEC_UA}))
        for el in root.iter():  # Namensräume entfernen, dann gelten einfache Pfade
            el.tag = el.tag.split("}")[-1]
        pos = {}
        for it in root.iter("infoTable"):
            g = lambda p, it=it: text(it, p)
            if (g("putCall") or "").strip():
                continue
            name, cusip = g("nameOfIssuer"), g("cusip")
            wert = float(g("value") or 0)
            stk = float(g("shrsOrPrnAmt/sshPrnamt") or 0)
            p = pos.setdefault(cusip, {"name": name, "cusip": cusip, "wert": 0, "stueck": 0})
            p["wert"] += wert; p["stueck"] += stk
        groesste = sorted(pos.values(), key=lambda p: -p["wert"])[:400]  # sehr große Fonds auf die 400 größten Positionen kürzen
        berichte.append({"stichtag": rec["reportDate"][i], "gemeldet": rec["filingDate"][i], "anzahl": len(pos), "summe": sum(p["wert"] for p in pos.values()),
                         "pos": {p["cusip"]: p for p in groesste}})
        time.sleep(0.15)
    return berichte


def insider_kaeufe(fund):
    """Käufe (Code P) aus den letzten Form-4-Meldungen der US-Werte."""
    import xml.etree.ElementTree as ET
    grenze = (datetime.date.today() - datetime.timedelta(days=120)).isoformat()
    out = []
    for s, w in fund.items():
        for acc, datum, doc in (w.get("form4") or [])[:12]:
            if datum < grenze:
                break
            url = "https://www.sec.gov/Archives/edgar/data/%d/%s/%s" % (int(w["cik"]), acc.replace("-", ""), re.sub(r"^xsl[^/]*/", "", doc))
            try:
                root = ET.fromstring(http_get(url, headers={"User-Agent": SEC_UA}))
            except Exception:
                continue
            wer = text(root, "reportingOwner/reportingOwnerId/rptOwnerName")
            rolle = text(root, "reportingOwner/reportingOwnerRelationship/officerTitle") or ("Direktor" if text(root, "reportingOwner/reportingOwnerRelationship/isDirector") in ("1", "true") else "")
            for tr in root.findall("nonDerivativeTable/nonDerivativeTransaction"):
                code = text(tr, "transactionCoding/transactionCode")
                if code not in ("P", "S"):
                    continue
                stk = float(text(tr, "transactionAmounts/transactionShares/value") or 0)
                px = float(text(tr, "transactionAmounts/transactionPricePerShare/value") or 0)
                out.append({"symbol": s, "datum": text(tr, "transactionDate/value") or datum, "wer": wer, "rolle": rolle, "art": "Kauf" if code == "P" else "Verkauf",
                            "stueck": stk, "kurs": px, "wert": stk * px, "plan10b5": "10b5-1" in (ET.tostring(root, encoding="unicode")[:20000])})
            time.sleep(0.12)
    out.sort(key=lambda x: x["datum"], reverse=True)
    return out


def kongress():
    """Wertpapiergeschäfte von Abgeordneten (House Clerk, Periodic Transaction Reports)."""
    jahr = datetime.date.today().year
    raw = http_get("https://disclosures-clerk.house.gov/public_disc/financial-pdfs/%dFD.zip" % jahr, raw=True)
    import xml.etree.ElementTree as ET
    z = zipfile.ZipFile(io.BytesIO(raw))
    root = ET.fromstring(z.read([n for n in z.namelist() if n.endswith(".xml")][0]))
    fil = []
    for m in root.findall("Member"):
        if (m.findtext("FilingType") or "") != "P":
            continue
        fil.append({"name": " ".join(x for x in [m.findtext("First"), m.findtext("Last")] if x), "staat": m.findtext("StateDst"),
                    "datum": m.findtext("FilingDate"), "doc": m.findtext("DocID")})
    def iso(d):
        try:
            mo, da, yr = d.split("/"); return "%s-%02d-%02d" % (yr, int(mo), int(da))
        except Exception:
            return d or ""
    for f in fil:
        f["datum"] = iso(f["datum"])
    fil.sort(key=lambda f: f["datum"], reverse=True)
    fil = fil[:40]
    hat_pdf = subprocess.run(["which", "pdftotext"], capture_output=True).returncode == 0
    zeilen = []
    for f in fil:
        f["url"] = "https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/%d/%s.pdf" % (jahr, f["doc"])
        if not hat_pdf:
            continue
        try:
            pdf = http_get(f["url"], raw=True)
            with tempfile.NamedTemporaryFile(suffix=".pdf") as tmp:
                tmp.write(pdf); tmp.flush()
                txt = subprocess.run(["pdftotext", "-layout", tmp.name, "-"], capture_output=True, text=True, timeout=60).stdout
            for line in txt.splitlines():
                m = re.search(r"\(([A-Z][A-Z.\-]{0,6})\).*?\b(P|S|S \(partial\)|E)\b\s+(\d{2}/\d{2}/\d{4})\s+\d{2}/\d{2}/\d{4}\s+(\$[\d,]+\s*-\s*\$[\d,]+|Over \$[\d,]+)", line)
                if m:
                    zeilen.append({"wer": f["name"], "staat": f["staat"], "symbol": m.group(1), "art": "Kauf" if m.group(2) == "P" else "Verkauf" if m.group(2).startswith("S") else "Tausch",
                                   "datum": iso(m.group(3)), "betrag": re.sub(r"\s+", " ", m.group(4)), "gemeldet": f["datum"], "url": f["url"]})
        except Exception as e:
            log("PTR %s: %s" % (f["doc"], e))
        time.sleep(0.3)
    return {"meldungen": fil, "geschaefte": zeilen}


def institutionell(out):
    alt = lade_alt(out, "institutionell.json") or {}
    res = {"zeit": int(time.time() * 1000), "quelle": "SEC EDGAR (13F, Form 4), House Clerk (PTR)", "investoren": {}, "insider": alt.get("insider", []), "kongress": alt.get("kongress", {})}
    for cik, name in (INVESTOREN.items() if SEC_UA else []):
        try:
            b = dreizehn_f(cik)
            if b:
                res["investoren"][cik] = {"name": name, "berichte": b}
        except Exception as e:
            log("13F %s: %s" % (name, e))
            if cik in alt.get("investoren", {}):
                res["investoren"][cik] = alt["investoren"][cik]
    fund = (lade_alt(out, "fundamente.json") or {}).get("werte", {})
    if not SEC_UA:
        res["investoren"] = alt.get("investoren", {})
    try:
        if SEC_UA:
            res["insider"] = insider_kaeufe(fund)
    except Exception as e:
        log("Insider: %s" % e)
    try:
        res["kongress"] = kongress()
    except Exception as e:
        log("Kongress: %s" % e)
    schreibe(out, "institutionell.json", res)
    return 0


def main():
    if len(sys.argv) < 3 or sys.argv[1] not in ("stuendlich", "taeglich", "historie", "fundamente", "makro", "institutionell"):
        sys.exit(__doc__)
    out, was = sys.argv[2], sys.argv[1]
    schritte = {"stuendlich": [stuendlich], "taeglich": [stuendlich, historie, fundamente, makro, institutionell],
                "historie": [historie], "fundamente": [fundamente], "makro": [makro], "institutionell": [institutionell]}[was]
    fehler = 0
    for f in schritte:
        t = time.time()
        try:
            fehler += f(out) or 0
        except Exception as e:
            log("%s FEHLER: %r" % (f.__name__, e)); fehler += 1
        log("%s fertig in %.0f s" % (f.__name__, time.time() - t))
    # Kein Fehlschlag der Action bei Teilausfall: alte Dateien bleiben stehen
    return 0


if __name__ == "__main__":
    sys.exit(main())
