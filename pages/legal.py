"""Apex legal pages."""

from dash import dcc, html


IMPRESSUM_DE = """
**Angaben gemaess Paragraph 5 TMG**

**Fundation GmbH**  
Hibbelenstr. 10  
51107 Koeln  
Deutschland

Geschaeftsfuehrer: Cosmin Novac  
E-Mail: info@fundation.de  
Internet: www.fundation.de

**Apex Portfolio**  
Website: https://apexportfolio.de/

**Steuerliche Angaben**  
Zustaendiges Finanzamt: Finanzamt Koeln-Ost  
Umsatzsteuer-Identifikationsnummer: DE360847938

Die Europaeische Kommission stellt eine Plattform zur aussergerichtlichen Online-Streitbeilegung bereit: https://ec.europa.eu/consumers/odr/  
Wir sind weder verpflichtet noch bereit, an einem Streitbeilegungsverfahren vor einer Verbraucherschlichtungsstelle teilzunehmen.

---

**Verantwortlich fuer den Inhalt nach Paragraph 55 Abs. 2 RStV**

Fundation GmbH  
Hibbelenstr. 10  
51107 Koeln  
Deutschland

---

**Haftung fuer Inhalte**

Die Inhalte dieser Seiten wurden mit groesster Sorgfalt erstellt. Fuer die Richtigkeit, Vollstaendigkeit und Aktualitaet der Inhalte koennen wir jedoch keine Gewaehr uebernehmen. Apex stellt Informationen, Analysen und Simulationen bereit, ersetzt aber keine Finanz-, Anlage-, Steuer- oder Rechtsberatung.

Als Diensteanbieter sind wir nach den allgemeinen Gesetzen fuer eigene Inhalte auf diesen Seiten verantwortlich. Wir sind jedoch nicht verpflichtet, uebermittelte oder gespeicherte fremde Informationen zu ueberwachen oder nach Umstaenden zu forschen, die auf eine rechtswidrige Taetigkeit hinweisen. Bei Bekanntwerden entsprechender Rechtsverletzungen werden wir diese Inhalte umgehend entfernen.

**Haftung fuer Links**

Unser Angebot kann Links zu externen Webseiten Dritter enthalten. Auf deren Inhalte haben wir keinen Einfluss. Fuer die Inhalte der verlinkten Seiten ist stets der jeweilige Anbieter oder Betreiber verantwortlich.

**Urheberrecht**

Die durch die Seitenbetreiber erstellten Inhalte und Werke auf diesen Seiten unterliegen dem deutschen Urheberrecht. Eine Vervielfaeltigung, Bearbeitung, Verbreitung oder sonstige Verwertung ausserhalb der Grenzen des Urheberrechts bedarf der schriftlichen Zustimmung des jeweiligen Autors bzw. Erstellers.
"""


IMPRESSUM_EN = """
**Legal Notice according to Paragraph 5 TMG**

**Fundation GmbH**  
Hibbelenstr. 10  
51107 Cologne  
Germany

Managing Director: Cosmin Novac  
Email: info@fundation.de  
Web: www.fundation.de

**Apex Portfolio**  
Website: https://apexportfolio.de/

**Tax information**  
Competent tax office: Finanzamt Koeln-Ost  
VAT ID: DE360847938

The European Commission provides a platform for online dispute resolution: https://ec.europa.eu/consumers/odr/  
We are neither obliged nor willing to participate in dispute resolution proceedings before a consumer arbitration board.

---

**Responsible for content according to Paragraph 55 Abs. 2 RStV**

Fundation GmbH  
Hibbelenstr. 10  
51107 Cologne  
Germany

---

**Liability for content**

The contents of these pages were created with great care. However, we cannot guarantee their accuracy, completeness, or timeliness. Apex provides information, analytics, and simulations, but does not replace financial, investment, tax, or legal advice.

As a service provider, we are responsible for our own content on these pages under general law. We are not obliged to monitor transmitted or stored third-party information or to investigate circumstances indicating illegal activity. If we become aware of legal violations, we will remove the relevant content promptly.

**Liability for links**

Our offer may contain links to external third-party websites. We have no influence over their content. The respective provider or operator is responsible for the linked pages.

**Copyright**

The content and works created by the site operators are subject to German copyright law. Reproduction, editing, distribution, or any other use outside the limits of copyright law requires written consent from the respective author or creator.
"""


PRIVACY_DE = """
## Datenschutzerklaerung

**Stand:** 4. Juni 2026

Diese Datenschutzerklaerung erklaert, welche personenbezogenen Daten wir bei der Nutzung von Apex Portfolio ("Apex") verarbeiten und zu welchen Zwecken dies geschieht.

## Verantwortlicher

Fundation GmbH  
Hibbelenstr. 10  
51107 Koeln  
Deutschland

Vertretungsberechtigt: Cosmin Novac  
E-Mail: info@fundation.de  
Impressum: https://apexportfolio.de/impressum

## Welche Daten wir verarbeiten

Je nach Nutzung von Apex koennen insbesondere folgende Daten verarbeitet werden:

- technische Zugriffsdaten wie IP-Adresse, Zeitpunkt des Abrufs, Browser, Betriebssystem und angefragte URL,
- Konto- und Login-Daten, soweit Sie sich anmelden,
- Portfolio- und Transaktionsdaten, wenn Sie eine Trade-Republic-Synchronisierung starten,
- lokal eingegebene Analyse-, Backtesting- und Simulationsparameter,
- Kommunikationsdaten, wenn Sie uns kontaktieren.

## Zwecke und Rechtsgrundlagen

Wir verarbeiten Daten, um Apex bereitzustellen, Logins zu ermoeglichen, Portfolio-Synchronisierung und Analysen auszufuehren, die Sicherheit der Anwendung zu gewaehrleisten und Anfragen zu beantworten.

Rechtsgrundlagen sind insbesondere Vertragserfuellung und vorvertragliche Massnahmen nach Art. 6 Abs. 1 lit. b DSGVO, berechtigte Interessen nach Art. 6 Abs. 1 lit. f DSGVO sowie, soweit erforderlich, Ihre Einwilligung nach Art. 6 Abs. 1 lit. a DSGVO.

## Hosting und Speicherung

Apex wird ueber Cloud-Infrastruktur bereitgestellt. Zur Bereitstellung der Website koennen technische Zugriffsdaten in Server-Logs verarbeitet werden. Soweit Sie ein Konto nutzen oder Portfolio-Daten synchronisieren, koennen Daten verschluesselt in Azure Blob Storage gespeichert werden, damit Ihr Apex-Konto zwischen Sitzungen wiederhergestellt werden kann.

## Authentifizierung

Fuer die Anmeldung nutzt Apex Clerk. Clerk verarbeitet die fuer Login und Sitzungsverwaltung erforderlichen Daten, insbesondere E-Mail-Adresse, Nutzerkennung, Session-Informationen und technische Sicherheitsdaten. Die Verarbeitung dient der sicheren Authentifizierung und dem Schutz vor Missbrauch.

## Trade-Republic-Synchronisierung

Wenn Sie die Trade-Republic-Synchronisierung aktivieren, verwendet Apex die von Ihnen eingegebenen Zugangsdaten bzw. eine bestehende Sitzung, um Portfolio-, Positions-, Cash-, Transaktions- und Preisdaten abzurufen und in Apex auszuwerten. Diese Synchronisierung erfolgt nur, wenn Sie sie ausloesen oder eine gespeicherte Sitzung zur erneuten Verbindung nutzen. Apex ist kein Angebot von Trade Republic und steht nicht mit Trade Republic in Verbindung.

## Externe Datenquellen

Apex kann externe Marktdatenquellen wie Yahoo Finance bzw. yfinance nutzen, um Benchmarks, Kursdaten oder Vergleichsdaten abzurufen. Dabei koennen technische Anfragen an diese Anbieter entstehen.

## Optionale KI-Funktionen

Wenn Sie KI-Funktionen nutzen und einen OpenAI API-Key hinterlegen, koennen Ihre Eingaben zur Verarbeitung an OpenAI uebermittelt werden. Dies geschieht nur fuer die jeweils genutzte KI-Funktion.

## Cookies und lokale Speicherung

Apex nutzt Cookies, Browser-Speicher und vergleichbare Technologien, soweit sie fuer Login, Spracheinstellungen, Theme, Sitzungen und App-Funktionalitaet erforderlich sind.

## Speicherdauer

Wir speichern personenbezogene Daten nur so lange, wie dies fuer die jeweiligen Zwecke erforderlich ist oder gesetzliche Aufbewahrungspflichten bestehen. Konto- und Portfolio-Daten koennen geloescht werden, wenn das Konto entfernt oder die Speicherung nicht mehr erforderlich ist.

## Ihre Rechte

Sie haben nach der DSGVO insbesondere das Recht auf Auskunft, Berichtigung, Loeschung, Einschraenkung der Verarbeitung, Datenuebertragbarkeit sowie Widerspruch gegen bestimmte Verarbeitungen. Soweit eine Verarbeitung auf Einwilligung beruht, koennen Sie diese jederzeit widerrufen.

Sie haben zudem das Recht, sich bei einer Datenschutzaufsichtsbehoerde zu beschweren.

## Kontakt

Bei Fragen zum Datenschutz erreichen Sie uns unter: info@fundation.de
"""


PRIVACY_EN = """
## Privacy Policy

**Last updated:** 4 June 2026

This Privacy Policy explains which personal data we process when you use Apex Portfolio ("Apex") and for which purposes.

## Controller

Fundation GmbH  
Hibbelenstr. 10  
51107 Cologne  
Germany

Represented by: Cosmin Novac  
Email: info@fundation.de  
Legal notice: https://apexportfolio.de/impressum

## Data we process

Depending on how you use Apex, we may process:

- technical access data such as IP address, request time, browser, operating system, and requested URL,
- account and login data if you sign in,
- portfolio and transaction data if you start a Trade Republic sync,
- analysis, backtesting, and simulation parameters entered in the app,
- communication data if you contact us.

## Purposes and legal bases

We process data to provide Apex, enable login, perform portfolio sync and analysis, secure the application, and respond to requests.

The legal bases include performance of a contract or pre-contractual measures under Art. 6(1)(b) GDPR, legitimate interests under Art. 6(1)(f) GDPR, and, where required, your consent under Art. 6(1)(a) GDPR.

## Hosting and storage

Apex is provided through cloud infrastructure. Technical access data may be processed in server logs to provide the website. If you use an account or sync portfolio data, data may be stored encrypted in Azure Blob Storage so your Apex account can be restored between sessions.

## Authentication

Apex uses Clerk for authentication. Clerk processes data required for login and session management, including email address, user identifier, session information, and technical security data. This processing enables secure authentication and misuse prevention.

## Trade Republic sync

If you activate Trade Republic sync, Apex uses the credentials you enter or an existing session to retrieve and evaluate portfolio, position, cash, transaction, and price data. Sync only happens when you trigger it or when a saved session is used to reconnect. Apex is not provided by, affiliated with, or endorsed by Trade Republic.

## External market data

Apex may use external market data sources such as Yahoo Finance or yfinance to retrieve benchmark, price, or comparison data. Technical requests may be sent to these providers for that purpose.

## Optional AI features

If you use AI features and provide an OpenAI API key, your inputs may be sent to OpenAI for processing. This only happens for the AI feature you use.

## Cookies and local storage

Apex uses cookies, browser storage, and similar technologies where required for login, language settings, theme, sessions, and app functionality.

## Retention

We store personal data only as long as required for the relevant purposes or by legal retention obligations. Account and portfolio data may be deleted when the account is removed or storage is no longer required.

## Your rights

Under the GDPR, you have rights of access, rectification, deletion, restriction of processing, data portability, and objection to certain processing. Where processing is based on consent, you may withdraw that consent at any time.

You also have the right to lodge a complaint with a data protection supervisory authority.

## Contact

For privacy questions, contact us at: info@fundation.de
"""


def layout(kind: str, lang: str = "en"):
    is_privacy = kind == "privacy"
    title = ("Datenschutzerklaerung" if lang == "de" else "Privacy Policy") if is_privacy else ("Impressum" if lang == "de" else "Legal Notice")
    text = (PRIVACY_DE if lang == "de" else PRIVACY_EN) if is_privacy else (IMPRESSUM_DE if lang == "de" else IMPRESSUM_EN)
    return html.Div([
        dcc.Link("Back to Apex" if lang == "en" else "Zurueck zu Apex", href="/", className="legal-back-link"),
        html.H1(title, className="legal-title"),
        dcc.Markdown(text, className="legal-text"),
    ], className="legal-page")
