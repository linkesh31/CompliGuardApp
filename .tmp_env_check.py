import os
from pathlib import Path
from dotenv import find_dotenv, load_dotenv

cwd = os.getcwd()
path = find_dotenv(filename=".env", usecwd=True)
print("cwd =", cwd)
print(".env found at =", path, "exists?", Path(path).exists())

load_dotenv(path, override=False)

u = os.getenv("SMTP_USERNAME")
p = os.getenv("SMTP_PASSWORD")
print("ENV SMTP_USERNAME =", u)
print("ENV SMTP_PASSWORD set? ->", bool(p), "len:", len(p or ""))

import services.config as cfg
print("cfg.SMTP_USERNAME =", cfg.SMTP_USERNAME)
print("cfg.SMTP_PASSWORD set? ->", cfg.SMTP_PASSWORD not in ("", "YOUR_APP_PASSWORD"))
