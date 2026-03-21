# ASML Dagrapport — Installatie op Home Assistant OS

## Wat je krijgt
Elke dag om 06:00 wordt automatisch een HTML-rapport aangemaakt op je HA-server.
Bereikbaar via je HA-dashboard op telefoon, iPad en computer.

---

## Stap 1 — AppDaemon add-on installeren

1. Ga in HA naar **Instellingen → Add-ons → Add-on store**
2. Zoek op **AppDaemon**
3. Klik op **Installeren**
4. Schakel **"Start bij opstarten"** in
5. Ga naar het tabblad **Configuratie** en voeg toe:

```yaml
python_packages:
  - yfinance
  - pandas
  - pytz
```

6. Klik **Opslaan** en dan **Herstart**

---

## Stap 2 — Bestanden kopiëren

Gebruik de **File Editor** add-on (of Studio Code Server) in HA om de bestanden te plaatsen.

### `asml_rapport.py`
Kopieer de inhoud van `asml_rapport.py` naar:
```
/config/appdaemon/apps/asml_rapport.py
```

### `apps.yaml`
Voeg de volgende regels toe aan het **bestaande** bestand:
```
/config/appdaemon/apps/apps.yaml
```

```yaml
asml_rapport:
  module: asml_rapport
  class: ASMLRapport
```

---

## Stap 3 — www-map aanmaken

Maak de map aan als die nog niet bestaat:
```
/config/www/
```

Het script maakt het HTML-bestand daarin automatisch aan bij de eerste run.

---

## Stap 4 — Herstart AppDaemon

Ga naar **Instellingen → Add-ons → AppDaemon → Herstart**

Controleer het logboek: je zou moeten zien dat de app geladen is zonder fouten.

---

## Stap 5 — Direct testen (optioneel)

Open `asml_rapport.py` en verwijder het commentaar bij deze regel:

```python
# self.run_in(self.generate_rapport, 15)
```

Herstart AppDaemon. Na 15 seconden wordt het rapport aangemaakt.
Zet de regel daarna weer terug als commentaar.

Controleer of het bestand bestaat:
```
/config/www/asml_rapport.html
```

---

## Stap 6 — Dashboard-kaart toevoegen

### Optie A — Webpage-kaart in bestaand dashboard
1. Ga naar je HA-dashboard
2. Klik op de potlood-icon (bewerken)
3. Klik **+ Kaart toevoegen**
4. Kies **Webpage** (of zoek op "iframe")
5. Vul in:
   - **URL:** `/local/asml_rapport.html`
   - Hoogte: stel in op gewenste grootte (bijv. 800px)

Of via YAML:
```yaml
type: iframe
url: /local/asml_rapport.html
aspect_ratio: 150%
```

### Optie B — Eigen paneel in sidebar
1. Ga naar **Instellingen → Dashboards**
2. Klik **+ Dashboard toevoegen**
3. Kies type: **Webpagina**
4. URL: `/local/asml_rapport.html`
5. Geef het een naam en pictogram (bijv. 📊)

---

## Rapport bekijken

Direct in de browser:
```
http://homeassistant.local:8123/local/asml_rapport.html
```

Of via je HA-app op telefoon/iPad.

---

## Schema

Het rapport wordt elke dag automatisch bijgewerkt om **06:00** (servertijd HA).
Weekend: het rapport toont de meest recente handelsdagdata met een weekendwaarschuwing.
