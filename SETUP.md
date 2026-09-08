# Setup, and how to get this on GitHub

Written for someone who has not used git before. Follow it top to bottom.

---

## Part 1 — Run it on your machine

You need Python 3.10 or newer. On a Mac, check with:

```bash
python3 --version
```

If that errors, install Python from python.org or run `brew install python`.

Then, from inside this folder:

```bash
# 1. Make an isolated environment so this project's packages
#    don't collide with anything else on your Mac.
python3 -m venv .venv
source .venv/bin/activate

# 2. Install what it needs.
pip install -r requirements.txt

# 3. Prove it works — offline, no API key.
make test
make demo
```

`make demo` scores six fictional companies from `data/fixtures/`. If you see six
rows of output, everything is wired correctly.

### Now run it for real

Get an API key from console.anthropic.com, then:

```bash
cp .env.example .env
open -e .env          # paste your key after ANTHROPIC_API_KEY=
```

```bash
make score            # scores the real companies in data/domains_sample.csv
make explain DOMAIN=gong.io
make eval             # THE IMPORTANT ONE — measures accuracy
```

`make eval` costs roughly one model call per company in `evals/labels.csv` (34),
so a full run is cents, not dollars. Results are cached, so re-running is free
unless you edit `icp.yaml`.

> **`.env` must never leave your machine.** It is already in `.gitignore`. If you
> ever paste a key somewhere public, rotate it immediately in the console.

---

## Part 2 — Put it on GitHub

### One-time setup

Check whether git is there:

```bash
git --version
```

macOS will offer to install developer tools if it isn't. Then tell git who you are:

```bash
git config --global user.name "Affan Bin Emran"
git config --global user.email "affanbinemran@gmail.com"
```

### Create the repository

**The easy way — GitHub's CLI.**

```bash
brew install gh          # if you don't have it
gh auth login            # choose GitHub.com, HTTPS, login with a browser
```

Then from inside this folder:

```bash
git init
git add .
git status               # LOOK AT THIS. If .env appears, stop and fix .gitignore.
git commit -m "ICP scorer with grounding checks and an eval harness"
git branch -M main
gh repo create icp-scorer --public --source=. --push
```

That's it. `gh` prints the URL.

**The manual way — if you'd rather not install `gh`.**

1. Go to github.com/new. Name it `icp-scorer`. Public. **Do not** tick "Add a README" — you already have one.
2. Then:

```bash
git init
git add .
git status
git commit -m "ICP scorer with grounding checks and an eval harness"
git branch -M main
git remote add origin https://github.com/YOUR_USERNAME/icp-scorer.git
git push -u origin main
```

If it asks for a password, GitHub wants a **personal access token**, not your
account password: github.com → Settings → Developer settings → Personal access
tokens → Tokens (classic) → Generate new token → tick `repo`. Paste the token
where it asks for a password.

### Making changes later

```bash
git add .
git commit -m "Tightened the gtm_motion guidance; accuracy 81% -> 87%"
git push
```

Write commit messages like that — what changed and what it did to the number.
People read commit history in interviews.

---

## Part 3 — Finish the repo before you show it

The code is done. These four things are what turn it into a portfolio piece.

1. **Replace `YOUR_USERNAME`** in `README.md` (badge URL) and `src/icp_scorer/fetch.py`
   (the user-agent string) with your GitHub handle.

2. **Run `make eval` and fill in the results table** in the README with your real
   numbers. Then change something in `icp.yaml`, run it again, and add a second
   row. The table showing accuracy *moving* is the most valuable thing in the repo.

3. **Argue with `evals/labels.csv`.** Read all 34 rows. Change every one you
   disagree with, and add more — aim for 60. These are your labels, encoding your
   commercial judgment. If you inherit someone else's labels you've skipped the
   only part of this that requires you.

4. **Record a 30-second screen capture** of `make explain DOMAIN=...` showing a
   rejected quote, save it as a GIF, and put it at the top of the README.
   `Cmd+Shift+5` records on macOS; convert with `ffmpeg` or gifski. More people
   will watch that clip than will read your code.

5. **Add topics** on the GitHub repo page — `gtm-engineering`, `revops`,
   `sales-automation`, `claude`, `lead-scoring`. It's how people find it.

---

## Troubleshooting

**`ModuleNotFoundError: No module named 'icp_scorer'`**
The virtualenv isn't active, or you're outside the repo folder. Run
`source .venv/bin/activate` from the project root. The Makefile sets `PYTHONPATH=src`
for you; if you're running commands by hand, prefix them with `PYTHONPATH=src`.

**`anthropic.NotFoundError: model not found`**
Model ids change. Open the Anthropic docs, find the current one, and set
`ANTHROPIC_MODEL=` in your `.env`.

**Every score comes back 0**
The fetcher got nothing — likely a site blocking automated requests. Check with
`cat .cache/pages/thatdomain.txt`. If it's empty, that company just can't be
scored from its homepage, which is a real limitation worth writing up.

**A company scores lower than it should**
Run `make explain DOMAIN=that-company.com` and read the quotes. Nine times out of
ten the rubric guidance is ambiguous, not the model. Fix `icp.yaml`, not the code.
