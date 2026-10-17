# Security notes

## Credentials previously committed

Earlier commits contained hard-coded Alpaca **paper-trading** keys (`trading/engine.py`,
`worker_original.py`) and a Finnhub API key (`main.py`). They have been removed from the code and
are now read from environment variables. The Alpaca keys have been rotated; **rotate the Finnhub key too**
(it was public). The old values are still
present in git history.

### Purging them from history (maintainer only — rewrites history)

```bash
pip install git-filter-repo
git clone --mirror https://github.com/hardik656/lifepilot-backend.git lp-mirror && cd lp-mirror
cat > ../replacements.txt <<'TXT'
regex:PK[A-Z0-9]{18,}==>REDACTED_ALPACA_KEY
regex:ALPACA_SECRET\s*=\s*"[^"]+"==>ALPACA_SECRET = "REDACTED"
regex:FINNHUB_KEY\s*=\s*"[^"]+"==>FINNHUB_KEY = "REDACTED"
TXT
git filter-repo --replace-text ../replacements.txt
git log -p --all | grep -E 'PK[A-Z0-9]{18,}|GeVWw8|27vVNH|d65ov1hr' || echo "clean"
git push --force --mirror
```

After a force-push, anyone with an old clone must re-clone; open PRs and forks keep the old objects,
and GitHub may still serve cached commit views until you contact GitHub Support to purge them.
Rotating the keys is what actually neutralises them; history purge is clean-up.

## Reporting

Email hgumber43@gmail.com.
