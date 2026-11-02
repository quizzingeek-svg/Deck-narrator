# Deck Narrator Bot: how to run it (no coding needed)

It's free. You install one program (Docker Desktop) once, then double-click a file.

## 1. Install Docker Desktop (one time)
* Download it from **https://www.docker.com/products/docker-desktop/** (Windows, Mac or Linux) and install it.
* Open Docker Desktop once and wait until it says **"Engine running"**. Windows may ask you to restart or to enable "WSL 2"; say yes.
* Docker Desktop is free for personal use, education and small businesses.

## 2. Unzip the folder
Unzip `deck_narrator_bot.zip` anywhere you like, for example your Desktop.

## 3. Double-click to start
| Computer | Start | Stop |
|---|---|---|
| Windows | `start-windows.bat` | `stop-windows.bat` |
| Mac | `start-mac.command` (first time: right-click → **Open** → Open, because it isn't from the App Store) | `stop-mac.command` |
| Linux | `start-linux.sh` | `stop-linux.sh` |

The **first start takes about 5–15 minutes**, because it downloads and sets everything up (about 2–3 GB).
After that it starts in seconds. Your browser opens at **http://localhost:8502** on its own.

## 4. Optional: add AI keys
The bot works without any keys: it narrates your speaker notes, walks through the deck, waits for you to say "next",
and gives basic explanations. For **AI explanations, live answers to questions and translation**, add a free key:

1. Get a free Google Gemini key at https://aistudio.google.com/apikey
2. Open the file **`.env`** in the folder with Notepad or TextEdit. It's created the first time you start the bot; if you
   can't see it, copy `.env.example` and rename the copy to `.env`. On a Mac, press Cmd+Shift+. to show hidden files.
3. Paste the key after `GEMINI_API_KEY=` and save, for example `GEMINI_API_KEY=AIza...`
4. Double-click **stop**, then **start** again.

You can also paste a key directly in the app's left sidebar (🧠 AI model); that lasts until you close the tab.
Premium voices (ElevenLabs, Azure, OpenAI) are optional and go in the same `.env` file.

## Good to know
* **Internet:** the natural voices are a free online Microsoft service, and AI answers and translation are online too.
  Speech recognition (saying "next", spoken questions) runs on your computer.
* **Port:** the bot uses `localhost:8502`, so it doesn't clash with the Market Sizing bot on 8501.
* **Microphone:** your browser will ask for permission the first time you use voice. Click Allow.
* **Something went wrong?** Make sure Docker Desktop is running, then double-click start again. To see what happened,
  open a terminal in the folder and run `docker compose logs`.

---

## For whoever shares it: one file that works fully offline (no build, no downloads)
On a computer where the bot already runs:
```bash
docker save deck-narrator-bot:latest | gzip > deck-narrator-bot-image.tar.gz     # about 0.9 GB
```
On Windows PowerShell, which has no gzip: `docker save -o deck-narrator-bot-image.tar deck-narrator-bot:latest`

Put `deck-narrator-bot-image.tar.gz` (or `.tar`) **in the unzipped folder** next to the start scripts. The start scripts
find it and load it automatically instead of building. Or load it by hand:
```bash
docker load -i deck-narrator-bot-image.tar.gz     # docker load reads .tar and .tar.gz
docker compose up -d                              # then open http://localhost:8502
```
To include the more accurate Whisper "small" model (better for Indian languages, +0.5 GB):
`docker compose build --build-arg WHISPER_MODELS="base small"`, then set `WHISPER_MODEL=small` in `.env`.
