# meshcore-matrix-bridge

A small, self-hosted bridge between a [MeshCore](https://meshcore.co.uk/) node
running the **Companion** firmware (connected over USB / serial) and a
[Matrix](https://matrix.org/) homeserver.

The bridge is controlled from Matrix with a single command prefix (`!mesh …`)
and can also be driven purely from the terminal (`mc-cli`) for quick send /
receive tests without Matrix.

> **Status:** `0.4.0`. The bridge is in daily use on a private home
> server. Channel history has to be pulled manually (via `!mesh fetch`
> or `!mesh public`) because the MeshCore companion firmware itself
> does not keep a long-term channel history — it only exposes a
> pending-messages queue that must be drained by the host. Silently
> dropped channel messages are persisted to a local JSONL log so that
> `!mesh queue` can tell you what you missed even across restarts.

---

## ⚠️ Zielgruppe / Audience

This project is **not a click-and-go appliance**. You need to be
comfortable with: a Linux server that you administer yourself, systemd
user services, editing `.env` files, `journalctl`, and the basics of
your Matrix homeserver (how to create a user, how to get an access
token). If any of that sounds exhausting, come back after you have a
Matrix server running and a MeshCore Companion node that talks to your
phone.

In short: this is an amateur-radio-style home-brew bridge for people
who already run their own Matrix server. There is currently **no
install script** — the steps below have to be done by hand. If someone
shows up and wants to help turn this into a one-liner installer, that
would be very welcome; open an issue.

---

## 🇩🇪 Schnellüberblick auf Deutsch

**Kein Projekt für Einsteiger.** Du solltest mit Linux-Server-Administration
(systemd, `.env`, `journalctl`) und deinem Matrix-Homeserver (Benutzer
anlegen, Access-Token holen) vertraut sein. Wenn dir schon einer dieser
Begriffe unheimlich ist, richte erst deinen Matrix-Server ein und
besorge dir einen MeshCore-Companion-Node, der mit deinem Handy spricht
— komm dann wieder.

Was dabei entsteht: Ein Matrix-Bot (`@meshcore:dein.server`), der auf
deinem Homeserver läuft, per USB oder BLE mit deinem MeshCore-Node
spricht und LoRa-Nachrichten in Matrix-Räume spiegelt (und zurück).
Das ist quasi „Amateurfunk-Style auf Matrix": jeder darf mitlesen, nur
zugelassene MXIDs dürfen senden.

### Was du brauchst

- Einen **eigenen Matrix-Homeserver** (Synapse, Conduit, Dendrite —
  egal, Hauptsache du kannst dort einen Nutzer anlegen und einen
  Access-Token holen). Wenn du nur auf matrix.org o.ä. einen Account
  hast: geht technisch auch, ist aber wegen Rate-Limits und
  Room-Creation-Restrictions mühsam. Eigener Server ist klar empfohlen.
- Einen **MeshCore-Node mit Companion-Firmware** (Heltec V3, RAK4631,
  T-Beam, …), angeschlossen entweder per USB an deinen Server oder
  per BLE in Reichweite des Servers.
- Einen **Linux-Host** auf dem die Bridge läuft (idealerweise derselbe
  Host wie der Matrix-Server; spart Netzwerklatenz). Python ≥ 3.10,
  `systemd --user`, kein Docker nötig.

### Reihenfolge, die wir erfolgreich gegangen sind

1. **Matrix-Server läuft, du hast einen regulären Matrix-Account**
   (`@du:dein.server`) und kannst dich mit Element o.ä. einloggen.
2. **Bot-Account anlegen** (`@meshcore:dein.server`) — bei Synapse über
   `register_new_matrix_user` im Container. Kein Admin-Recht nötig.
3. **Access-Token + Device-ID holen** über die `/login`-API (Beispiel
   weiter unten im Abschnitt *Creating the Matrix bot user*).
4. **MeshCore-Node verkabeln/koppeln** — entweder USB-CDC (`/dev/ttyUSB0`
   bzw. `/dev/ttyACM0`) oder BLE (einmalig die BT-Adresse scannen). Das
   **Handy muss den Node in dem Moment nicht gekoppelt haben** — der
   Node akzeptiert nur **einen** BLE-Central gleichzeitig.
5. **Bridge klonen, Venv anlegen, `pip install .`** (siehe
   *Installation* unten).
6. **`bridge.env` ausfüllen** unter `~/.meshcore-bridge-secrets/` mit
   Homeserver-URL, Bot-MXID, Access-Token, Device-ID, Allowlist (deine
   eigene MXID), dem MeshCore-Transport und -Port.
7. **Einmal im Vordergrund starten** (`meshcore-matrix-bridge`) und in
   Element die DM annehmen, die der Bot dir schickt. Er postet dort
   `🟢 online`.
8. **Die eigenen MeshCore-Channels auf dem Node anlegen** — entweder
   vorher per App, oder aus der Matrix-DM heraus:
   `!mesh addchan de-nw-owl`, `!mesh addchan europe`, …. Der Key wird
   aus `sha256(name)[:16]` abgeleitet (regionale Konvention, z. B.
   deutsche OWL-Community: `de`, `de-nw`, `de-nw-owl`, `de-west`,
   `europe`).
9. **Pro Channel einen Matrix-Raum binden und Relay anschalten:**
   `!mesh bind 0 mesh-de`, `!mesh relay 0 on`. Dann dem neu erzeugten
   Raum in Element beitreten — ab da kommen Funk-Nachrichten live in
   den Raum und was du dort tippst geht raus.
10. **Als systemd-User-Service einrichten** damit die Bridge reboots
    überlebt (siehe *systemd (user scope)* unten). `loginctl
    enable-linger` nicht vergessen.
11. **Sanity-Checks:** `!mesh status` (Node-Info), `!mesh channels`
    (Slot/Raum-Zuordnung), `!mesh queue` (was wurde empfangen / was
    fiel wo hin).

### Bots daraufsetzen

Der Bridge-Code ist absichtlich **schmal** — alles was „Bot-haftes"
macht (Wetter-Ticker, Mention-Responder, LLM-Relay, Cron-Ansagen)
lebt als **separater Prozess** in einem eigenen Repo:
[`Basti77/meshcore-bots`](https://github.com/Basti77/meshcore-bots).
Ein Bot braucht nichts weiter als einen eigenen Matrix-Account, der
in den gewünschten Channel-Raum eingeladen wird. Er postet dort ganz
normal Nachrichten — die Bridge fängt die automatisch ab und sendet
sie aufs LoRa-Netz. Umgekehrt kommen eingehende Mesh-Nachrichten
wieder im selben Raum an und sind damit für den Bot lesbar.

Ergebnis: **Jeder Matrix-Bot, den du ohnehin schon hast (n8n, Python,
Home Assistant, Shell-Skript mit `curl`), wird dadurch ohne weitere
Integration mesh-fähig.** Einladen, Power-Level 50 geben, fertig.

### Es gibt aktuell kein Install-Skript

Bewusste Entscheidung — die Zielgruppe ist klein genug, dass ein
Skript mehr Mythos als Nutzen wäre. Wenn sich jemand ernsthaft
dransetzen will: gerne Issue aufmachen oder per Matrix melden, dann
bauen wir das gemeinsam.

---

## Features

- USB-serial connection to a MeshCore Companion node (via
  [`meshcore`](https://pypi.org/project/meshcore/) ≥ 2.3).
- Matrix bot account operating in an unencrypted DM control room (the bot
  creates the room and invites you on first start).
- `!mesh <subcommand>` from Matrix:
  - `help`, `status`, `ping`
  - `contacts` — list known MeshCore contacts
  - `channels` — list configured channels (indexes + names)
  - `fetch [limit]` — manually drain the node's pending-messages queue and
    dump DMs + channel messages into the Matrix room
  - `public [limit]` — same, but filtered to the `#public` channel
  - `dm <name|keyprefix> <text…>` — send a direct message to a MeshCore
    contact (with retry + flood-fallback, waits for ACK)
  - `send <channel_idx> <text…>` — send a message to a channel (e.g. `0` for
    `#public`)
- Optional auto-relay of incoming channel messages to the Matrix room
  (disabled by default — `#public` can be very chatty).
- Strict allow-list of Matrix users that may control the bridge.
- Persistent state (JSON) for the bridge room ID and later
  cursors.
- Standalone CLI (`mc-cli`) that reuses the same logic without Matrix.

---

## Architecture

```
┌───────────────┐   Matrix C2S     ┌──────────────────────┐
│  Element (you)│ ───────────────▶ │  @meshcore (bot)     │
└───────────────┘                  │  matrix-nio, Allowed │
                                   │  users only          │
                                   └──────────┬───────────┘
                                              │ !mesh commands
                                              ▼
                                   ┌──────────────────────┐
                                   │  CommandHandler       │
                                   │  dispatches to        │
                                   └──────────┬───────────┘
                                              │ async
                                              ▼
                                   ┌──────────────────────┐   0x3E framed
  ┌────────────────────┐   serial  │  MeshNode (meshcore   │ ◀───────────┐
  │  MeshCore node    │ ◀──────── │  py lib)               │             │
  │  Companion fw     │ ────────▶ │  subscribe RX events   │  push events│
  └────────────────────┘           └──────────────────────┘─────────────┘
```

The MeshCore Python library implements the Companion UART protocol (frames
delimited by `0x3C` / `0x3E`). Incoming radio messages arrive as events
(`CONTACT_MSG_RECV`, `CHANNEL_MSG_RECV`). The bot either auto-fetches the
message queue (`MESSAGES_WAITING` → `get_msg` loop) or drains it on demand when
you send `!mesh fetch`.

---

## Installation

On the host that will have the MeshCore node plugged in (e.g. `sentinel`):

```bash
git clone https://github.com/Basti77/meshcore-matrix-bridge.git
cd meshcore-matrix-bridge

# Dedicated venv (recommended)
python3 -m venv ~/.local/venvs/meshcore-matrix-bridge
~/.local/venvs/meshcore-matrix-bridge/bin/pip install -U pip
~/.local/venvs/meshcore-matrix-bridge/bin/pip install .

# Make the entry points visible on PATH
mkdir -p ~/.local/bin
ln -sf ~/.local/venvs/meshcore-matrix-bridge/bin/meshcore-matrix-bridge ~/.local/bin/
ln -sf ~/.local/venvs/meshcore-matrix-bridge/bin/mc-cli ~/.local/bin/
```

## Transport: serial vs. BLE

MeshCore Companion speaks over **either** USB-CDC serial **or** a BLE
Nordic-UART-style GATT service. Most RAK4631 builds (including v1.14.0)
expose the Companion protocol **only over BLE** — the USB console on those
devices is debug-only. If `create_serial` returns `None`, switch to BLE.

### Serial

```ini
MESHCORE_TRANSPORT=serial
MESHCORE_PORT=/dev/ttyACM0
MESHCORE_BAUDRATE=115200
```

The user must be in the `dialout` group:

```bash
sudo usermod -aG dialout "$USER"
# re-login
```

### BLE

```ini
MESHCORE_TRANSPORT=ble
# either pin the address …
MESHCORE_PORT=AA:BB:CC:DD:EE:FF
# … or auto-scan by name
# MESHCORE_PORT=scan
# MESHCORE_BLE_NAME=MeshCore
```

Dependencies (installed automatically via `pip`): `bleak` + `dbus-fast`.
On the host you also need a working BlueZ stack:

```bash
sudo apt install bluez
sudo systemctl enable --now bluetooth
```

**Important:** a MeshCore node accepts **only one BLE Central at a time**.
If you still have the phone connected, the bridge cannot connect and vice
versa. In the Android app tap the device and pick "Disconnect" before
starting the bridge (or toggle Bluetooth off on the phone).

**Hardware caveat**: not every BT chip has a working Linux driver. We have
seen MediaTek MT7902 modules advertise themselves but then fail with
`Bluetooth: hci0: Unsupported hardware variant` — in that case a cheap
external USB dongle (TP-Link UB400 / CSR8510) works out of the box.

Scan for a MeshCore advertisement once to find its address:

```bash
sudo bluetoothctl --timeout 10 scan on
sudo bluetoothctl devices | grep -i mesh
```

You can also let the CLI scan:

```bash
mc-cli --transport ble --port scan --ble-name MeshCore status
```

---

## Creating the Matrix bot user

There are two common situations: you run your own homeserver (more control,
the path used during development), or you use an existing / third-party
homeserver (matrix.org, Element Home, a server your friend runs, ...).

### Option A — your own Synapse

Example with Synapse in Docker. Pick any password, a strong random one is fine.

```bash
docker exec matrix-synapse register_new_matrix_user \
    -c /data/homeserver.yaml \
    -u meshcore -p '<password>' --no-admin http://localhost:8008
```

If the interactive prompt is awkward, Synapse also accepts a shared-secret
registration over HTTP (`/\_synapse/admin/v1/register`) — handy when
scripting the setup.

### Option B — a homeserver you don't own (matrix.org, Element Home, ...)

The bridge does not need any admin rights on the homeserver, **but** it does
assume the bot account can

1. log in over the client-server API,
2. create rooms,
3. accept invites,
4. set custom power levels on rooms it owns.

All of that is normal user territory on most open homeservers. Steps:

1. **Register the bot account manually** through the server's usual signup
   path (Element web, a `/register` endpoint that accepts open registration,
   etc.). On `matrix.org` this is a normal signup with a CAPTCHA.
2. **Get an access token** — easiest path: log into Element Web as the
   bot, go to *Settings → Help & About → Access Token*, copy. Or use the
   raw login API as shown below.
3. **Pin a room, optionally** — some homeservers (notably `matrix.org`)
   throttle or block new accounts from creating public rooms. In that case
   set `MATRIX_ROOM_ID=!xxx:your-server` in `bridge.env` to skip the
   auto-create step and use a pre-existing control room where you invited
   the bot.
4. Everything else (`!mesh bind`, `!mesh relay`, ...) works the same.

### Getting a token via the login API

Works against any homeserver:

```bash
curl -s -X POST https://matrix.example.com/_matrix/client/v3/login \
  -H 'Content-Type: application/json' \
  -d '{"type":"m.login.password",
       "identifier":{"type":"m.id.user","user":"meshcore"},
       "password":"<password>",
       "initial_device_display_name":"meshcore-bridge"}' | jq
```

Copy `access_token` and `device_id` into `bridge.env`.

### Gotchas on shared / third-party homeservers

- **Room creation policies.** Some servers forbid fresh accounts from
  creating public rooms (anti-spam). If `!mesh bind` fails with an HTTP
  403, create the channel room manually in Element, make the bot an admin
  (PL 100), and tell the bridge the room ID via `MATRIX_ROOM_ID=...` for
  the control room, or via a future config option for channel rooms.
- **Rate limits.** Large contact lists or bulk `fetch` commands can trip
  per-user rate limits on big homeservers. There is no workaround from the
  client side — just expect occasional `M_LIMIT_EXCEEDED` errors and let
  the bridge back off and retry. On your own server you can whitelist the
  bot's MXID in the `ratelimit_override` table (Postgres) + restart
  Synapse.
- **Federation.** Even if the bot lives on your own homeserver, people on
  other homeservers can join the `#mesh-*` rooms as long as federation is
  enabled on both sides. That is the "amateur radio on the internet"
  effect: one node, a global audience, no account on your server needed.
  Some homeservers disable federation by default — then only local users
  can read.
- **Room directory listing.** `visibility: public` makes the room appear
  in the `/publicRooms` directory of the homeserver. Some admins disable
  public listings; rooms remain joinable by direct URL / alias in that
  case.
- **End-to-end encryption.** The bridge explicitly runs unencrypted (no
  E2EE). Public channel rooms shouldn't need it anyway — the whole point
  is that anyone can read along. The control DM is not encrypted either,
  so don't use it for secrets.

---

## Configuration

The bridge reads environment variables. They can come from one or more `.env`
files — by default the bridge looks at
`~/.meshcore-bridge-secrets/matrix.env` and `~/.meshcore-bridge-secrets/bridge.env`
(override via `MESH_BRIDGE_ENV_FILES=path1:path2`).

Keep secrets (the access token) in a file with `chmod 600`:

```bash
mkdir -p ~/.meshcore-bridge-secrets
chmod 700 ~/.meshcore-bridge-secrets
cp bridge.env.example ~/.meshcore-bridge-secrets/bridge.env
chmod 600 ~/.meshcore-bridge-secrets/bridge.env
$EDITOR ~/.meshcore-bridge-secrets/bridge.env
```

Minimum required keys:

| Key | Meaning |
|---|---|
| `MATRIX_HOMESERVER` | e.g. `https://matrix.example.com` |
| `MATRIX_USER_ID` | `@meshcore:matrix.example.com` |
| `MATRIX_ACCESS_TOKEN` | from `/login` |
| `MATRIX_DEVICE_ID` | from `/login` |
| `MATRIX_ALLOWED_USERS` | comma-separated MXID allow-list; first entry is invited to the DM control room |
| `MESHCORE_PORT` | serial port, e.g. `/dev/ttyUSB0` |

See `bridge.env.example` for all options.

---

## Running

### Foreground (for first smoke test)

```bash
export MESH_BRIDGE_ENV_FILES=$HOME/.meshcore-bridge-secrets/bridge.env
meshcore-matrix-bridge
```

On first start the bot will

1. open `/dev/ttyUSB0` and query the node,
2. subscribe to RX events and start auto-fetching,
3. create a DM with the first entry of `MATRIX_ALLOWED_USERS` (unless
   `MATRIX_ROOM_ID` is pinned) and post a `🟢 online` notice there.

### systemd (user scope)

```bash
mkdir -p ~/.config/systemd/user
cp systemd/meshcore-matrix-bridge.service ~/.config/systemd/user/
systemctl --user daemon-reload
systemctl --user enable --now meshcore-matrix-bridge.service
loginctl enable-linger "$USER"          # keep running across logouts
journalctl --user -u meshcore-matrix-bridge -f
```

---

## Using it from Matrix

On first start the bot creates a **private control DM** with you and posts
a `🟢 online` notice. From there, create a public read-along room for a
channel:

```
!mesh bind 0 mesh-public       # creates #mesh-public:your.server
!mesh relay 0 on               # optional: auto-forward #public RX here
!mesh channels                 # shows idx / name / bound room / relay state
```

The bot joins the new room, invites you, and sets power levels so that
**only you and the bot can write**, while anyone on the homeserver (or any
federated user) can join and read along. That's the amateur-radio model:
TX is license-gated, RX is free.

From the `#mesh-public` room you can just type a message and it goes out on
the air (auto-split at ~140 chars).

Other useful commands in the control DM:

```
!mesh help
!mesh status
!mesh contacts
!mesh dm Alice hallo!
!mesh send 0 hallo #public         # alternative to typing in the room
!mesh public 100                    # manually drain #public backlog
!mesh fetch                         # drain everything
```

### Managing channel slots on the node

The MeshCore node keeps a small table of channel slots — each one is a
(name, 16-byte key) pair. To avoid dropping into a shell / Python script
just to add a regional channel, you can do it from the control DM:

```
!mesh addchan de-nw-owl             # auto-picks the lowest free slot
!mesh addchan europe 10             # or specify a slot explicitly
!mesh delchan 10                    # clears the slot and forgets its Matrix binding
```

The channel key is auto-derived as `sha256(name)[:16]` — that is the
scope convention used by most regional MeshCore communities (so
everyone who uses e.g. the name `de-nw-owl` ends up on the same key).

### Checking what was dropped

If a channel is active on the mesh but nothing lands in Matrix, that's
almost always one of: `relay` is off, no Matrix room is bound to the
slot yet, or the bot is not in the bound room. `!mesh queue` shows this
explicitly:

```
!mesh queue                # per-channel seen / dropped counters
!mesh queue 7              # last ~20 dropped messages on slot 7 (text + SNR + hops)
```

The bookkeeping has two tiers:

- **`seen` counters** live in memory for the current bridge process
  (reset on restart — relayed messages are already in Matrix).
- **`dropped` counters and samples** are persisted to an append-only
  JSONL log at `~/.local/state/meshcore-matrix-bridge/rx-drops.jsonl`.
  On restart the log is replayed so dropped messages and their counters
  survive service restarts. Rotation at 2 MB, one generation kept. IO
  is zero when nothing is dropping.

### Inbound message format

Channel and DM messages include both the hop count (from the packet's
`path_len`) and the SNR:

```
📡 #6 <Sam> danke für das feedback
   hops=2 snr=12.25 ts=07:56:22 UTC
```

Special values:

- `hops=0` — direct / zero-hop reception
- `hops=N` — reached via N repeaters
- `hops=flood` — flood-routed, exact hop count unknown
- `hops=?` — field not present in payload (older firmware)

If `relay` is **off** for a channel (the default), RX from that channel is
just logged — use `!mesh fetch` / `!mesh public` to pull it on demand.

---

## Using it from the terminal (no Matrix)

```bash
mc-cli --port /dev/ttyUSB0 contacts
mc-cli --port /dev/ttyUSB0 channels
mc-cli --port /dev/ttyUSB0 status
mc-cli --port /dev/ttyUSB0 public --limit 50
mc-cli --port /dev/ttyUSB0 dm Alice "hi there"
mc-cli --port /dev/ttyUSB0 send 0 "hallo #public"
mc-cli --port /dev/ttyUSB0 listen          # live-tail RX
```

Add `--json` for machine-readable output.

---

## Troubleshooting

- **`create_serial returned None`** — the attached device is not running
  Companion firmware (it might be a Repeater/Room-Server build, which uses a
  different protocol), or the port is wrong. Check `dmesg | tail`, and list
  candidate ports with `ls /dev/ttyUSB* /dev/ttyACM*`.
- **Permission denied on `/dev/ttyUSB0`** — user not in `dialout` group; see
  installation section.
- **Bot does not join your invite** — it only auto-accepts from MXIDs in
  `MATRIX_ALLOWED_USERS`.
- **No ACK for a DM** — the contact might only be known via flood (`pathlen =
  -1`). Try `!mesh dm` again; the library already tries flood after two
  direct attempts.
- **No channel backlog appears** — the Companion firmware does not persist
  channel history. `!mesh fetch` / `!mesh public` only return messages that
  were **queued by the node since the last drain**. The bridge should
  normally auto-fetch; the manual command is there mostly for debugging /
  catching up after a bridge restart.

---

## Security notes

- The bridge runs **unencrypted** Matrix (no E2EE). Do not treat the control
  room as confidential — it is only as private as your server.
- `MATRIX_ALLOWED_USERS` gates both invite auto-accept **and** command
  dispatch — keep it tight.
- The access token is long-lived; revoke it via Element (or `/logout`) when
  rotating credentials. A new token requires editing `bridge.env` and
  restarting the service.

---

## Development

```bash
pip install -e .[dev]
ruff check src/
mypy src/
```

---

## Credits

- [`fdlamotte/meshcore_py`](https://github.com/fdlamotte/meshcore_py) — the
  Python library that does the actual MeshCore protocol work.
- [`matrix-nio`](https://github.com/poljar/matrix-nio) — Matrix client library.
