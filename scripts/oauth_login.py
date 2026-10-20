"""One-time OAuth login (run on a machine with a browser): python scripts/oauth_login.py"""
import sys; sys.path.insert(0, ".")
from google_auth_oauthlib.flow import InstalledAppFlow
from app.config import load_config
from app.clients import SCOPES
c = load_config()["credentials"]
creds = InstalledAppFlow.from_client_secrets_file(c["oauth_client_file"], SCOPES).run_local_server(port=0)
open(c["oauth_token_file"], "w").write(creds.to_json()); print("saved", c["oauth_token_file"])
