"""Drive/Calendar client interfaces. Real Google impls + mock impls. Inject any object
with the same methods into PhotoSync / CalendarService / create_app."""
import datetime as dt, io, json, os, shutil
FIX = os.path.join(os.path.dirname(__file__), "..", "fixtures")


class MockDrive:
    """list_images() -> [{id,name,mimeType,modifiedTime}]; download(id, dest_path)."""
    def __init__(self, folder=os.path.join(FIX, "photos")):
        self.folder = folder
    def list_images(self):
        out = []
        for n in sorted(os.listdir(self.folder)):
            p = os.path.join(self.folder, n)
            if not n.startswith(".") and os.path.isfile(p):
                out.append({"id": n.replace(".", "_"), "name": n, "mimeType": "",  # unique per extension; mime from ext
                            "modifiedTime": str(os.path.getmtime(p))})
        return out
    def _path(self, file_id):
        for n in os.listdir(self.folder):
            if n.replace(".", "_") == file_id: return os.path.join(self.folder, n)
        raise FileNotFoundError(file_id)
    def download(self, file_id, dest):
        shutil.copyfile(self._path(file_id), dest)

class MockCalendar:
    """list_events(cal_id, time_min, time_max) -> Google-shaped event dicts."""
    def __init__(self, path=os.path.join(FIX, "events.json"), tz="America/Chicago"):
        from zoneinfo import ZoneInfo
        self.path, self.tz = path, ZoneInfo(tz)
    def list_events(self, cal_id, time_min, time_max):
        today = dt.date.today()
        evs = json.load(open(self.path))
        out = []
        for e in evs:  # offsets relative to today so fixtures are always current
            d = today + dt.timedelta(days=e["day_offset"])
            if "all_day_days" in e:
                out.append({"id": e["id"], "summary": e["summary"],
                            "start": {"date": d.isoformat()},
                            "end": {"date": (d + dt.timedelta(days=e["all_day_days"])).isoformat()}})
            else:
                tz = dt.timezone.utc if e.get("utc") else self.tz   # DST-aware local time
                s = dt.datetime.combine(d, dt.time.fromisoformat(e["start"]), tz)
                en = s + dt.timedelta(minutes=e["minutes"])
                out.append({"id": e["id"], "iCalUID": e["id"] + "@mock", "summary": e["summary"],
                            "start": {"dateTime": s.isoformat()}, "end": {"dateTime": en.isoformat()}})
        return out

def _creds(cfg, scopes):
    c = cfg["credentials"]
    if c["type"] == "service_account":
        from google.oauth2 import service_account
        return service_account.Credentials.from_service_account_file(c["service_account_file"], scopes=scopes)
    from google.oauth2.credentials import Credentials
    from google.auth.transport.requests import Request
    creds = Credentials.from_authorized_user_file(c["oauth_token_file"], scopes)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        open(c["oauth_token_file"], "w").write(creds.to_json())
    return creds

SCOPES = ["https://www.googleapis.com/auth/drive.readonly",
          "https://www.googleapis.com/auth/calendar.readonly"]

class GoogleDrive:
    def __init__(self, cfg):
        from googleapiclient.discovery import build
        self.creds = _creds(cfg, SCOPES)
        self.svc = build("drive", "v3", credentials=self.creds, cache_discovery=False)
        self.folder = cfg["drive"]["folder_id"]
    def list_images(self):
        out, token = [], None
        q = f"'{self.folder}' in parents and trashed=false and mimeType contains 'image/'"
        while True:
            r = self.svc.files().list(q=q, pageSize=1000, pageToken=token,
                fields="nextPageToken, files(id,name,mimeType,modifiedTime,imageMediaMetadata(width,height))",
                supportsAllDrives=True, includeItemsFromAllDrives=True).execute()
            out += r.get("files", [])
            token = r.get("nextPageToken")
            if not token:
                return out
    def download(self, file_id, dest):
        from googleapiclient.http import MediaIoBaseDownload
        with open(dest, "wb") as f:
            d = MediaIoBaseDownload(f, self.svc.files().get_media(fileId=file_id))
            done = False
            while not done:
                _, done = d.next_chunk()

    def thumbnail(self, file_id, dest, size=1920):
        """Drive-rendered JPEG thumbnail (=s<size>): used for images too large to decode on the Pi."""
        from google.auth.transport.requests import AuthorizedSession
        link = self.svc.files().get(fileId=file_id, fields="thumbnailLink", supportsAllDrives=True).execute().get("thumbnailLink")
        if not link:
            raise RuntimeError("Drive has no thumbnail for this file")
        import re
        link = re.sub(r"=s\d+(-c)?$", "", link) + f"=s{int(size)}"
        r = AuthorizedSession(self.creds).get(link, timeout=60); r.raise_for_status()
        with open(dest, "wb") as fh: fh.write(r.content)

class GoogleCalendar:
    def __init__(self, cfg):
        from googleapiclient.discovery import build
        self.svc = build("calendar", "v3", credentials=_creds(cfg, SCOPES), cache_discovery=False)
    def list_events(self, cal_id, time_min, time_max):
        out, token = [], None
        while True:
            r = self.svc.events().list(calendarId=cal_id, timeMin=time_min.isoformat(),
                timeMax=time_max.isoformat(), singleEvents=True, orderBy="startTime",
                pageToken=token, maxResults=2500).execute()
            out += r.get("items", [])
            token = r.get("nextPageToken")
            if not token:
                return out

def make_clients(cfg):
    if cfg["mock"]:
        return MockDrive(), MockCalendar(tz=cfg.get("timezone", "America/Chicago"))
    return GoogleDrive(cfg), GoogleCalendar(cfg)
