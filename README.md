# Heizplan

Heizpläne für Home Assistant, wie in der Eve-App: Tagesprofile („ab 06:00 20 °C, ab 08:30 18 °C …“)
mit Namen speichern und pro Raum den Wochentagen zuweisen. Dazu Sondertage für freie Werktage
(Feiertag, Brückentag, Urlaub) und Homeoffice.

Die Integration rechnet nur aus, **was der Plan gerade sagt**. Sie stellt keine Thermostate.
Fenster, Anwesenheit, Urlaub und Handeinstellungen bleiben in der eigenen Konfiguration, die den
Sensor liest. So kommt der Grund für jede Solltemperatur aus einer Hand.

## Was es gibt

- **Panel „Heizpläne“** in der Seitenleiste, fürs iPhone gebaut
  - *Räume*: Solltemperatur jetzt, Tagesverlauf mit Jetzt-Markierung, Wochenleiste. Tag antippen,
    Profil wählen; mehrere Tage auf einmal (Mo–Fr, Sa + So, Alle).
  - *Profile*: Zeitpunkte mit Uhrzeit und Temperatur, Vorschau, Kopie, Löschen mit Ersatzprofil.
  - Ansehen darf jeder, ändern nur Admins.
- **Sensor pro Raum** `sensor.heizplan_<kürzel>`: Solltemperatur laut Plan.
  Attribute: `profil`, `profil_id`, `tag` (z. B. „Montag“, „Homeoffice“), `tagestyp`, `seit`,
  `naechster_wechsel`, `naechste_temperatur`, `heute` (Zeitpunkte des heutigen Profils).
- **Dienst** `heizplan.assign` (`raum`, `tage`, `profil`), z. B. um vor dem Urlaub alle Räume auf
  „Sparen“ zu setzen.

## Welcher Tag gilt

1. Montag bis Freitag, aber kein Werktag (Werktag-Sensor aus): **Freier Tag**, falls zugewiesen
2. Werktag und Homeoffice-Sensor an: **Homeoffice**, falls zugewiesen
3. sonst der **Wochentag**

Der Werktag-Sensor (z. B. aus der Workday-Integration) und der Homeoffice-Sensor werden beim
Einrichten gewählt und lassen sich unter *Konfigurieren* ändern.

Ein Profil beschreibt den ganzen Tag: Der erste Zeitpunkt liegt immer auf 00:00, jeder gilt bis
zum nächsten.

## Installation

HACS → Benutzerdefinierte Repositories → `https://github.com/chriseeg/heizung_control`
(Kategorie Integration) → *Heizplan* installieren → Neustart → Integration hinzufügen.

## Thermostate mit eigener Regelung (z. B. Eve Thermo)

Das Thermostat regelt das Ventil weiter selbst gegen seinen eigenen Fühler. Zeitpläne in der
Hersteller-App müssen aus sein, sonst arbeiten zwei Steuerungen gegeneinander.

## Entwicklung

```bash
uv pip install -r requirements_test.txt
ruff check . && ruff format --check . && mypy && pytest -q
```
