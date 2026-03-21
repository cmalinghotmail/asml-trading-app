# Claude Code — Werkinstructies voor dit project

## Bij elke sessie
- Lees altijd eerst het geheugenbestand: `C:\Users\cmali\.claude\projects\c--DEV-Prive-asml-trading-app\memory\MEMORY.md`

## Backlog / openstaande taken

### HA dashboard webpagina
AppDaemon schrijft dagelijks om 06:00 een HTML rapport naar `/homeassistant/www/asml_rapport.html`.
Het rapport is bereikbaar in de browser via `http://<tailscale-ip>/local/asml_rapport.html`,
maar is nog **niet zichtbaar in het HA dashboard** vanwege:
- HA Content Security Policy (CSP) blokkeert iframe-kaarten in Lovelace
- Tailscale IP (`100.126.16.53`) geeft "verbinding geweigerd" vanuit HA-context

Gebruiker zoekt zelf een oplossing via AppDaemon of alternatieve HA-integratie.
Bestanden: `homeassistant/asml_rapport.py`, `homeassistant/apps.yaml`, `homeassistant/INSTALLATIE.md`

### Claude Code direct in HA laten werken
Claude Code draait lokaal op de Windows-machine, maar de HA-server draait apart (via Tailscale).
Openstaande vraag: hoe kan Claude Code bestanden op de HA-server lezen/schrijven en scripts triggeren?
Mogelijke richtingen:
- SSH-toegang tot HA via Tailscale (Advanced SSH add-on)
- Samba/CIFS share van `/config/` map benaderen vanuit Windows
- HA REST API gebruiken voor AppDaemon-triggers
- VS Code Server (Studio Code Server add-on) als brug

---

## Na goedgekeurde wijzigingen
- Maak altijd een git commit na wijzigingen die door de gebruiker zijn goedgekeurd.
- Commit messages in het Nederlands.
- Gebruik `git user`: cmalinghotmail / cmaling@hotmail.com
- Push naar GitHub (remote `origin`, branch `main`).
