CompliGuard – PPE Compliance Monitoring System

A desktop safety application that detects PPE non-compliance (helmet, vest, gloves, boots) in real-time, records violations with snapshot evidence, manages workers/zones/cameras, and generates audit-ready reports — all with a polished Tkinter / CustomTkinter UI and Firebase Firestore as the data layer.

Why CompliGuard? Move from manual spot-checks to an objective, traceable, and operator-friendly workflow that links detection → identification → escalation → reporting.

✨ Key Features

Live Monitor (Real-time CV)

Continuous inference, 10s verification window, high-risk pop-up, snapshot evidence

Camera online/offline heartbeat display

Logs & Strikes

Identify offender from worker registry

One strike per violation, auto cumulative strike count, WhatsApp escalation message

Zones & Cameras

CRUD for zones (risk level: low/med/high)

Camera inventory with URL validation (RTSP/HTTP) and heartbeat status

Workers & Users

Unique worker IDs, strict phone normalization (+country code)

Admin management, secure password hashing (bcrypt preferred)

Reports

Trends by date, zone & risk, PPE (incl. combinations), offender recurrence

CSV / PDF export, preview tables and quick date chips

UX

Consistent light/beige theme, sidebar navigation, clear states and feedback

🧰 Tech Stack
Area	Tools
Language	Python 3.10 – 3.12 (Windows recommended)
UI	Tkinter + CustomTkinter
CV	OpenCV, Ultralytics YOLOv8 (custom PPE model + person model)
Cloud	Firebase Admin SDK (Firestore; optional Storage)
Imaging	Pillow (PIL)
Utilities	bcrypt, requests, python-dotenv, reportlab
Messaging	WhatsApp deep-link via default browser
🚀 Getting Started
1) Prerequisites

Windows 10/11 with Python 3.10–3.12 on PATH

A Firebase project and service account JSON

(Optional) NVIDIA drivers/CUDA for GPU acceleration

Microsoft Visual C++ Redistributable (needed by some wheels like bcrypt)

2) Clone
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

3) Virtual environment
# PowerShell
python -m venv .venv
. .venv\Scripts\activate

4) Dependencies

Create a requirements.txt (or copy the block below) and install:

pip install -r requirements.txt


requirements.txt

customtkinter==5.2.2
opencv-python==4.10.0.84
numpy>=1.24
pillow>=9.5
ultralytics>=8.2.0
firebase-admin>=6.5.0
google-cloud-firestore>=2.14.0
google-cloud-storage>=2.16.0
bcrypt>=4.1.2
requests>=2.31.0
python-dotenv>=1.0.1
reportlab>=4.0.9


If bcrypt fails to build, install MS C++ Build Tools or temporarily remove bcrypt during development. Use bcrypt in production.

5) Environment variables

Create .env in the repo root (use .env.example below as a start):

.env.example

GOOGLE_APPLICATION_CREDENTIALS=./secrets/serviceAccount.json
FIREBASE_PROJECT_ID=your-project-id
COMPANY_NAME=Your Company

# Optional email (if you wire up emailer.py later)
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=


Put your service account JSON at ./secrets/serviceAccount.json (create the folder).

6) Model files

Place your YOLO weights in models/:

models/
├─ best.pt        # your custom PPE model (helmet/vest/gloves/boots)
└─ yolov8n.pt     # person model (if your pipeline uses a separate one)


Adjust paths in services/ppe_infer.py if needed.

7) Run
python app.py

📂 Project Structure (typical)
<repo-root>/
├─ app.py
├─ models/                 # YOLO weights
├─ secrets/                # serviceAccount.json (gitignored)
├─ services/
│  ├─ firebase_client.py
│  ├─ users.py             # admin CRUD + hashing
│  ├─ workers.py           # worker CRUD + phone normalization
│  ├─ zones.py             # zones + cameras + heartbeat helpers
│  ├─ violations.py        # strikes + offender updates
│  ├─ ppe_infer.py         # YOLO inference wrapper
│  ├─ ui_theme.py          # theme + components
│  ├─ ui_assets.py         # icons/images loader
│  ├─ session.py           # in-memory session
│  ├─ messaging.py         # WhatsApp deeplink
│  └─ reports.py           # CSV/PDF exports
├─ data/ui/                # UI assets (logos/icons)
├─ .env
└─ requirements.txt

🧑‍💼 User Roles

Superadmin – multi-site/company view, manage companies and admins

Admin / Safety Officer – day-to-day operations at a site

🖱️ Using the App

Login / Entry → select company context

Zones → create zones, set risk, assign cameras (validated URLs/heartbeat)

Workers → add/activate workers; store phone as +<countrycode><number>

Live Monitor → real-time detection, 10s verification, high-risk pop-up, snapshot

Logs → open violation, identify offender, system records/ensures strike, prepare WhatsApp

Reports → filter by date/zone/PPE(PPE-combos), export CSV/PDF

📦 Packaging (optional)

Create a single executable with PyInstaller:

pip install pyinstaller
pyinstaller --noconfirm --name CompliGuard --onefile --add-data "data/ui;data/ui" app.py
# Copy models/ and .env next to the EXE (or add with --add-data)

🛠 Troubleshooting

Firebase credentials not found
Ensure GOOGLE_APPLICATION_CREDENTIALS points to an existing serviceAccount.json.

bcrypt install error
Install MS C++ Build Tools or use precompiled wheel matching your Python version.

OpenCV import error
Reinstall opencv-python for your Python version; avoid mixing multiple OpenCV wheels.

WhatsApp link doesn’t open
Default browser must be set; numbers must include +country code.

Models slow / inconsistent
Verify paths and models folder; reduce input size / FPS for weaker CPUs; ensure a stable stream.

📊 Roadmap (next phase)

Multi-platform client (web/mobile) backed by a local API service

Active learning pipeline for PPE model (hard-frame mining + periodic retraining)

Deeper analytics with audit-ready weekly/monthly packs

🙏 Acknowledgments

Thanks to supervisors, safety officers, and testers who provided invaluable feedback; and to the open-source communities behind Python, CustomTkinter, Ultralytics, and Firebase.

📬 Contact

Your Name — your.email@example.com

Repo: https://github.com/
<your-username>/<your-repo>
