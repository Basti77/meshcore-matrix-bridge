# meshcore-matrix-bridge — deutsche Kurzanleitung

Eine kleine, selbst gehostete Brücke zwischen einem
[MeshCore](https://meshcore.co.uk/)-Node mit **Companion**-Firmware
(USB-seriell oder BLE) und einem [Matrix](https://matrix.org/)-Homeserver.

Es entsteht ein Matrix-Bot (`@meshcore:dein.server`), der auf deinem
Homeserver läuft, per USB oder BLE mit deinem MeshCore-Node spricht und
LoRa-Nachrichten in Matrix-Räume spiegelt (und zurück). Das ist quasi
„Amateurfunk-Style auf Matrix": jeder darf mitlesen, nur zugelassene
MXIDs dürfen senden.

Diese Datei ist die Kurzfassung — alle Details (BLE-Fallstricke,
Homeserver-Optionen, Troubleshooting, Kommando-Referenz) stehen im
englischen [README.md](README.md).

## Voraussetzungen

Kein Projekt für Einsteiger, aber auch keine Raketenwissenschaft. Du
solltest mit Linux-Server-Administration (systemd-User-Services,
`.env`-Dateien, `journalctl`) und deinem Matrix-Homeserver (Benutzer
anlegen, Access-Token holen) umgehen können. Konkret brauchst du:

- Einen **eigenen Matrix-Homeserver** (Synapse, Conduit, Dendrite —
  egal, Hauptsache du kannst dort einen Nutzer anlegen und einen
  Access-Token holen). Ein Account auf matrix.org o. ä. geht technisch
  auch, ist aber wegen Rate-Limits und Room-Creation-Beschränkungen
  mühsam — eigener Server ist klar empfohlen (Details:
  README.md → *Option B*).
- Einen **MeshCore-Node mit Companion-Firmware** (Heltec V3, RAK4631,
  T-Beam, …), angeschlossen per USB an deinen Server oder per BLE in
  Reichweite. Getestet mit Companion v1.14.x.
- Einen **Linux-Host**, auf dem die Bridge läuft (idealerweise derselbe
  Host wie der Matrix-Server). Python ≥ 3.10, `systemd --user`, kein
  Docker nötig.

Ein Install-Skript gibt es (noch) nicht — die Schritte unten sind
Handarbeit. Wer eins beisteuern will: gerne Issue aufmachen.

## Reihenfolge, die sich bewährt hat

1. **Matrix-Server läuft, du hast einen regulären Matrix-Account**
   (`@du:dein.server`) und kannst dich mit Element o. ä. einloggen.
2. **Bot-Account anlegen** (`@meshcore:dein.server`) — bei Synapse über
   `register_new_matrix_user` im Container. Kein Admin-Recht nötig.
3. **Access-Token + Device-ID holen** über die `/login`-API (Beispiel
   in README.md → *Getting a token via the login API*).
4. **MeshCore-Node verkabeln/koppeln** — entweder USB-CDC
   (`/dev/ttyUSB0` bzw. `/dev/ttyACM0`) oder BLE (einmalig die
   BT-Adresse scannen). Achtung: der Node akzeptiert nur **einen**
   BLE-Central gleichzeitig — das Handy vorher trennen.
5. **Bridge klonen, venv anlegen, `pip install .`** (README.md →
   *Installation*). Für `!mesh chart` zusätzlich
   `pip install '.[chart]'`.
6. **`bridge.env` ausfüllen** unter `~/.meshcore-bridge-secrets/` mit
   Homeserver-URL, Bot-MXID, Access-Token, Device-ID, Allowlist (deine
   eigene MXID), MeshCore-Transport und -Port. Vorlage:
   `bridge.env.example`.
7. **Einmal im Vordergrund starten** (`meshcore-matrix-bridge`) und in
   Element die DM annehmen, die der Bot dir schickt. Er postet dort
   `🟢 online`.
8. **Die eigenen MeshCore-Channels auf dem Node anlegen** — entweder
   vorher per App, oder aus der Matrix-DM heraus:
   `!mesh addchan de-nw-owl`, `!mesh addchan europe`, … Der Key wird
   aus `sha256(name)[:16]` abgeleitet (regionale Konvention, z. B.
   deutsche OWL-Community: `de`, `de-nw`, `de-nw-owl`, `de-west`,
   `europe`).
9. **Pro Channel einen Matrix-Raum binden und Relay anschalten:**
   `!mesh bind 0 mesh-de`, `!mesh relay 0 on`. Dann dem neu erzeugten
   Raum in Element beitreten — ab da kommen Funk-Nachrichten live in
   den Raum, und was du dort tippst, geht raus.
10. **Als systemd-User-Service einrichten**, damit die Bridge Reboots
    überlebt (README.md → *systemd (user scope)*).
    `loginctl enable-linger` nicht vergessen.
11. **Sanity-Checks:** `!mesh status` (Node-Info), `!mesh channels`
    (Slot/Raum-Zuordnung), `!mesh queue` (was wurde empfangen / was
    fiel wo hin).

## Telemetrie

Repeater, Room-Server und Companions beantworten LPP-Telemetrie-Anfragen
(Akkuspannung, Temperatur, je nach Build weitere Sensoren):

```
!mesh telemetry Repeater-OWL        # einmalige Abfrage
!mesh autolog add Repeater-OWL      # alle 15 min automatisch loggen
!mesh chart Repeater-OWL 48         # PNG-Chart der letzten 48 h
```

## Bots draufsetzen

Der Bridge-Code ist absichtlich **schmal** — alles „Bot-hafte"
(Wetter-Ticker, Mention-Responder, LLM-Relay, Cron-Ansagen) lebt als
separater Prozess in einem eigenen Repo:
[`Basti77/meshcore-bots`](https://github.com/Basti77/meshcore-bots).
Ein Bot braucht nichts weiter als einen eigenen Matrix-Account, der in
den gewünschten Channel-Raum eingeladen wird (Power-Level 50). Er
postet dort ganz normale Nachrichten — die Bridge fängt sie ab und
sendet sie aufs LoRa-Netz; eingehende Mesh-Nachrichten kommen im selben
Raum an und sind für den Bot lesbar.

Ergebnis: **Jeder Matrix-Bot, den du ohnehin schon hast (n8n, Python,
Home Assistant, Shell-Skript mit `curl`), wird ohne weitere Integration
mesh-fähig.**
