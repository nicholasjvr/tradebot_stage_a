# Updating the Tradebot codebase (USB code + SD virtualenv)

This is a **hygienic, repeatable checklist** for updating your Tradebot project on a Raspberry Pi when:

- **Code lives on the mounted USB** (example: `/mnt/usb/projects/tradebot_stage_a`)
- **Python virtual environment (venv) lives on the SD card** (example: `~/tradebot_stage_a/.venv` or `~/venvs/...`)

The goal is: **update code safely**, **keep dependencies in sync**, and **restart cleanly** (especially if you’re running via `systemd`).

---

## The two paths you care about

### USB code repo (where you `git pull`)

From your session, the USB repo is here:

```bash
/mnt/usb/projects/tradebot_stage_a
```

The Python “app” folder is:

```bash
/mnt/usb/projects/tradebot_stage_a/tradebot
```

### SD-card virtualenv (where you `pip install -r ...`)

Common patterns (yours is likely one of these):

- `~/tradebot_stage_a/.venv` (matches the `README.md` quick start)
- `~/venvs/<something>` (matches your `~/venvs` folder)

If you’re not sure where the venv is, you can locate it like this:

```bash
ls -la ~/tradebot_stage_a/.venv/bin/python 2>/dev/null || true
ls -la ~/venvs/*/bin/python 2>/dev/null || true
```

---

## Golden rules (keeps things “clean”)

- **Always stop the running service before pulling** (prevents “half-updated” code running).
- **Only pull with fast-forward**: `git pull --ff-only` (prevents accidental merge commits).
- **Re-install dependencies after updating**: `pip install -r requirements.txt`
- **Keep secrets out of git**: don’t commit your `.env`.

---

## Update flow (systemd service installed)

This is the “production-style” update if you’re running `tradebot.service`.

### 1) Check USB is mounted

```bash
lsblk -f
ls /mnt/usb
```

You should see `projects/` and your `tradebot_stage_a/` folder.

### 2) Stop the service

```bash
sudo systemctl stop tradebot.service
```

Optional sanity check:

```bash
sudo systemctl status tradebot.service --no-pager
```

### 3) Pull the latest code on the USB repo

```bash
cd /mnt/usb/projects/tradebot_stage_a
git status
git pull --ff-only
```

If `git status` shows local changes you *didn’t* mean to make, you have two clean options:

- **Keep the changes**: commit them (best if they matter)
- **Temporarily park them**: `git stash -u` (then `git pull --ff-only`, then `git stash pop`)

### 4) Activate the SD-card venv

Use the one that exists on your Pi:

```bash
# Option A: venv inside your SD copy of the repo
source ~/tradebot_stage_a/.venv/bin/activate
```

```bash
# Option B: venvs folder on SD
source ~/venvs/<YOUR_VENV_NAME>/bin/activate
```

Quick check you’re using the venv Python:

```bash
which python
python --version
```

### 5) Install/refresh dependencies (into the venv)

Run this from the **USB code** folder that has `requirements.txt`:

```bash
cd /mnt/usb/projects/tradebot_stage_a/tradebot
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
```

### 6) Quick “did it import?” check (optional but recommended)

```bash
cd /mnt/usb/projects/tradebot_stage_a/tradebot
python -m bot.validate
```

### 7) Start the service again

```bash
sudo systemctl start tradebot.service
sudo systemctl status tradebot.service --no-pager
```

Follow logs:

```bash
sudo journalctl -u tradebot.service -f
```

---

## Update flow (manual run, no systemd)

### 1) Pull code (USB)

```bash
cd /mnt/usb/projects/tradebot_stage_a
git status
git pull --ff-only
```

### 2) Activate venv (SD)

```bash
source ~/tradebot_stage_a/.venv/bin/activate
# or:
source ~/venvs/<YOUR_VENV_NAME>/bin/activate
```

### 3) Update deps + run

```bash
cd /mnt/usb/projects/tradebot_stage_a/tradebot
python -m pip install -r requirements.txt
python -m bot.collector
```

---

## If you have *two* copies of the repo (USB + `~/tradebot_stage_a`)

From your terminal history, you have:

- USB: `/mnt/usb/projects/tradebot_stage_a`
- Home: `~/tradebot_stage_a`

That’s totally fine while learning, but it can get confusing.

### The cleanest approach

- **Treat the USB repo as the one true repo** (the one you pull + run).
- Keep the SD card for **venv + OS + logs**, not a second copy of the code.

### If you *do* keep both copies

Be consistent:

- `git pull` on the copy you actually run
- `pip install -r requirements.txt` using the requirements from the copy you actually run

---

## Where the service points (quick reference)

Your `tradebot/tradebot.service` template uses paths like:

- `WorkingDirectory=/home/pi/tradebot_stage_a/tradebot`
- `EnvironmentFile=/home/pi/tradebot_stage_a/tradebot/.env`
- `ExecStart=/home/pi/tradebot_stage_a/.venv/bin/python -m bot.collector`

If you want the service to run from the **USB code**, you’ll want to update those to match your USB path, e.g.:

- `WorkingDirectory=/mnt/usb/projects/tradebot_stage_a/tradebot`
- `EnvironmentFile=/mnt/usb/projects/tradebot_stage_a/tradebot/.env`
- `ExecStart=<PATH_TO_SD_VENV_PYTHON> -m bot.collector`

After editing a service file:

```bash
sudo systemctl daemon-reload
sudo systemctl restart tradebot.service
```

---

## Handy one-liners

- Show what’s mounted on `/mnt/usb`:

```bash
mount | grep /mnt/usb || true
```

- See the last 200 service log lines:

```bash
sudo journalctl -u tradebot.service -n 200 --no-pager
```

- Confirm your `.env` is being read (working directory matters):

```bash
cd /mnt/usb/projects/tradebot_stage_a/tradebot
python -c "from bot import config; print(config.EXCHANGE_NAME, config.SYMBOLS, config.TIMEFRAME, config.PUBLIC_ONLY)"
```

