# Git — how to save and back up this project

Written for someone who has never used git. Follow it literally.

**Repo:** https://github.com/mastansdev/opportunity-trader (PRIVATE)

---

## What git is (30 seconds)

Git = **save points in a game.** Every time you "commit", it photographs
every file. You can always go back to any photograph.

Two places your work lives:

| Where | What it is | Survives disk failure? |
|---|---|---|
| `D:\Opportunity Trader\.git` (hidden folder) | your local save points | ❌ NO |
| github.com/mastansdev/opportunity-trader | the off-site copy | ✅ YES |

**"Commit" saves locally. "Push" uploads.** You need BOTH. A commit
without a push is still one disk failure away from gone.

---

## THE DAILY ROUTINE (this is 95% of what you need)

Open a terminal **in `D:\Opportunity Trader`** and run these three, in
this order, at the end of every session:

```bash
git add -A                      # 1. gather every change
git commit -m "what changed"    # 2. save a checkpoint
git push                        # 3. upload it
```

Write a real message. `"Monday paper session, 14 trades"` is useful in
three weeks. `"notes"` is not.

---

## WHAT GETS SAVED — and what must NEVER be

**Saved (safe, and should be):** all `.py` code, all `.md` documents,
`requirements.txt`, `config.py`, tests.

**NEVER uploaded — protected by `.gitignore`:**

| File | Why it must stay local |
|---|---|
| `.env` | **your Dhan tokens and API keys** |
| `data/*.db` | news + candle databases (big, regenerable) |
| `data/session_state.json` | live position state |
| `logs/*.log`, `logs/*.csv` | 80+ MB of logs, and trade history |
| `__pycache__/`, `.pytest_cache/` | machine junk |

### Safety check before pushing (run if you're ever unsure)

```bash
git status                        # shows what WILL be saved
git ls-files | findstr ".env"     # must print NOTHING
```

If `.env` ever appears in `git status` as a file to be added — **stop and
ask.** It means the ignore rule broke and your broker tokens are about
to go online.

---

## READING WHAT GIT SAYS

| Message | Meaning | Action |
|---|---|---|
| `nothing to commit, working tree clean` | nothing changed since last save | none — this is fine |
| `Everything up-to-date` | GitHub already has it all | none — this is fine |
| `[main abc1234] your message` | checkpoint saved | now `git push` |
| `main -> main` | upload succeeded | done |
| `warning: LF will be replaced by CRLF` | Windows line-ending noise | ignore (already silenced) |

**Only two words matter: `error` and `rejected`.** Everything else is
git being chatty.

---

## USEFUL COMMANDS

```bash
git log --oneline           # list every save point
git status                  # what changed since the last save
git diff                    # the exact lines that changed
git diff config.py          # changes in one file only
```

---

## WHEN SOMETHING GOES WRONG

**"I broke the code and want yesterday's version back"**
```bash
git log --oneline                   # find the checkpoint, copy its id
git checkout <id> -- path/to/file.py   # restore ONE file
```

**"Undo all my uncommitted changes"** (destroys today's edits — be sure)
```bash
git checkout -- .
```

**`Authentication failed` on push**
Your token expired or was wrong. Regenerate: GitHub → Settings →
Developer settings → Personal access tokens → Tokens (classic) →
Generate new → tick **`repo`**. Use it as the *password*.

**`Updates were rejected`**
GitHub has something you don't. Run `git pull` first, then push.

**`index.lock` / "another git process is running"**
A crashed git left a lock file. Delete `.git/index.lock` and retry.
*(This exact thing silently blocked all commits here from 23 Jul to
25 Jul — worth recognising.)*

---

## RULES

1. **Push at the end of every trading day.** A local commit is not a backup.
2. **Never commit `.env`.** If in doubt, run the safety check above.
3. **Never `git push --force`.** It can erase history permanently.
4. **Commit before big changes, not after.** The save point is only
   useful if it exists *before* things break.
5. **The repo stays PRIVATE.** Your strategy is not public information.
