# Marktdaten für das Familien-Aktiendepot

Eine GitHub Action holt öffentliche Marktdaten und legt sie als JSON im Zweig `daten` ab:

| Datei | Inhalt | Takt |
|---|---|---|
| `kurse.json` | Kurse und Kennzahlen (US-Top-60, DAX, ETFs, Indizes, Sektoren), 1 Jahr Tageskurse | stündlich |
| `historie.json` | 10 Jahre dividendenbereinigte Tageskurse der US-Top-60 und Vergleichsindizes | täglich |
| `fundamente.json` | Bilanz-, Gewinn- und Cashflow-Daten aus SEC EDGAR | täglich |
| `makro.json` | Zinsen, Inflation, Arbeitsmarkt, Risikoaufschläge (FRED) | täglich |
| `institutionell.json` | 13F-Bestände großer Investoren, Insider-Käufe (Form 4), Kongress-Meldungen | täglich |

Quellen: Yahoo Finance (inoffiziell), SEC EDGAR, FRED, House Clerk. Keine persönlichen Daten.
Keine Anlageberatung. Kongress-Auswertung angelehnt an day-trader-skill (MIT, Jake Schincariol).
