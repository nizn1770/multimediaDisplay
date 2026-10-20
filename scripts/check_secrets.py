#!/usr/bin/env python3
"""Fail (exit 1) if tracked/staged files contain real-looking Google IDs or keys.
Usage: check_secrets.py [--staged] [--history]"""
import hashlib, re, subprocess, sys
# Known real values stored only as SHA-256 so this public repo never contains them.
BLOCKED_SHA256 = {"e17d2f911deef556864f581eb707feb810bd56a306ab10c08fd69f3136891bde"}
PATTERNS = {
    "drive_id": re.compile(r"(?<![A-Za-z0-9_-])1[A-Za-z0-9_-]{32}(?![A-Za-z0-9_-])"),
    "pem_or_key_field": re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----|\"private_" r"key(_id)?\"\s*:"),
    "oauth_secret": re.compile(r"\"client_" r"secret\"\s*:|GOCSPX-[A-Za-z0-9_-]{10,}"),
    "calendar_id": re.compile(r"[A-Za-z0-9._-]+@group\.calendar\.google\.com"),
    "service_account_email": re.compile(r"[a-z0-9-]+@[a-z0-9-]+\.iam\.gserviceaccount\.com"),
    "google_api_key": re.compile(r"AIza[0-9A-Za-z_-]{35}"),
}
ALLOW = re.compile(r"YOUR_|EXAMPLE|example")
TOKEN = re.compile(r"[A-Za-z0-9_-]{20,64}")

def scan_text(text, where):
    hits = []
    for tok in TOKEN.findall(text):
        if hashlib.sha256(tok.encode()).hexdigest() in BLOCKED_SHA256:
            hits.append((where, "blocked_value", tok[:4] + "…"))
    for name, rx in PATTERNS.items():
        for m in rx.finditer(text):
            line = text[text.rfind("\n", 0, m.start()) + 1: text.find("\n", m.end())]
            if not ALLOW.search(line):
                hits.append((where, name, m.group(0)[:6] + "…"))
    return hits

def git(*a): return subprocess.run(["git", *a], capture_output=True, check=True).stdout

def main(argv):
    hits = []
    if "--history" in argv:
        hits += scan_text(git("log", "--all", "-p", "--no-color").decode("utf-8", "replace"), "history")
    files = git("diff", "--cached", "--name-only", "--diff-filter=ACM").decode().split() if "--staged" in argv \
        else git("ls-files").decode().split()
    for f in files:
        try:
            data = git("show", ":" + f) if "--staged" in argv else open(f, "rb").read()
        except Exception:
            continue
        if b"\0" in data[:1024]: continue  # binary
        hits += scan_text(data.decode("utf-8", "replace"), f)
    for h in hits: print("SECRET? %s: %s %s" % h)
    if hits: print("Refusing: move real values to config.local.yaml / secrets/ (gitignored)."); return 1
    print("secret check: clean"); return 0

if __name__ == "__main__": sys.exit(main(sys.argv[1:]))
