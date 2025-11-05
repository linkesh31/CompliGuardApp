CompliGuard · PPE Compliance Monitoring System










CompliGuard is a desktop safety app that detects PPE non-compliance (helmet, vest, gloves, boots) in real time, captures evidence, manages workers/zones/cameras, and produces audit-ready reports—all through a modern Tkinter / CustomTkinter UI and Firebase Firestore backend.

📚 Table of Contents

Features

Tech Stack

Screenshots

Getting Started

Prerequisites

Clone

Virtual Environment

Install Dependencies

Environment Variables

Model Files

Run

Project Structure

User Roles & App Flow

Packaging

Troubleshooting

Roadmap

Contributing

License

Contact

✨ Features
Live Monitor (Real-time CV)

Continuous inference with 10s verification window

High-risk pop-up escalation only when justified

Snapshot evidence saved with timestamp/zone

Camera online/offline heartbeat indicator

Logs & Strikes

Pick the offender from the worker registry

Enforces one strike per violation

Auto cumulative strike count

Opens WhatsApp message (third strike text boldened)

Zones & Cameras

CRUD for zones with risk level: low / med / high

Camera inventory with RTSP/HTTP URL validation

Heartbeat metadata and status display

Workers & Users

Unique worker IDs and strict phone normalization (+countrycode)

Admin/user management, bcrypt password hashing (preferred)

Reports

Trends by date, zone & risk, PPE (including combinations), offender recurrence

CSV / PDF export, quick date chips, preview tables

UX

Consistent light/beige theme, sidebar navigation, clear state feedback

Keyboard-friendly forms and helpful error messages

🧰 Tech Stack
Area	Tools
Language	Python 3.10 – 3.12 (Windows recommended)
UI	Tkinter + CustomTkinter
Computer Vision	OpenCV, Ultralytics YOLOv8 (custom PPE + person model)
Cloud	Firebase Admin SDK (Firestore; optional Storage)
Imaging	Pillow (PIL)
Utilities	bcrypt, requests, python-dotenv, reportlab
Messaging	WhatsApp deep-link via default browser
🖼️ Screenshots

Replace with your actual images (put them in docs/).

docs/
 ├─ live-monitor.png
 ├─ logs.png
 ├─ reports.png
 └─ zones-workers.png

![Live Monitor](docs/live-monitor.png)
![Logs](docs/logs.png)
![Reports](docs/reports.png)
![Zones & Workers](docs/zones-workers.png)

🚀 Getting Started
Prerequisites

Windows 10/11 with Python 3.10–3.12 on PATH

Firebase project + service account JSON

(Optional) NVIDIA drivers/CUDA for GPU acceleration

Microsoft Visual C++ Redistributable (helps with wheels like bcrypt)

Clone
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

Virtual Environment
# PowerShell
python -m venv .venv
. .venv\Scripts\activate

Install Dependencies

Create requirements.txt (or use below) and install:

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


If bcrypt fails to install, install MS C++ Build Tools or temporarily remove it during development. Use bcrypt in production.

Environment Variables

Create a .env in the project root (you can commit a .env.example).

.env.example

GOOGLE_APPLICATION_CREDENTIALS=./secrets/serviceAccount.json
FIREBASE_PROJECT_ID=your-project-id
COMPANY_NAME=Your Company Name

# Optional email settings (if you wire emailer later)
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=


Place your service account file at ./secrets/serviceAccount.json (and gitignore the folder).

Model Files

Put your weights in models/:

models/
├─ best.pt        # your custom PPE model (helmet/vest/gloves/boots)
└─ yolov8n.pt     # person model (if pipeline expects it)


Update paths in services/ppe_infer.py if you use different filenames.

Run
python app.py

🗂 Project Structure
<repo-root>/
├─ app.py
├─ models/                     # YOLO weights
├─ secrets/                    # serviceAccount.json (ignored)
├─ services/
│  ├─ firebase_client.py
│  ├─ users.py                 # admin CRUD + hashing
│  ├─ workers.py               # worker CRUD + phone normalization
│  ├─ zones.py                 # zones + cameras + heartbeat helpers
│  ├─ violations.py            # strikes + offender updates
│  ├─ ppe_infer.py             # YOLO inference wrapper
│  ├─ messaging.py             # WhatsApp deep-link builder
│  ├─ reports.py               # CSV/PDF export
│  ├─ ui_theme.py              # themed components
│  ├─ ui_assets.py             # icon/image loader
│  └─ session.py               # in-memory session store
├─ data/ui/                    # UI assets (logos/icons)
├─ docs/                       # screenshots (optional)
├─ .env                        # local env
└─ requirements.txt

👤 User Roles & App Flow

Roles

Superadmin: multi-site/company management

Admin / Safety Officer: daily operations for one site

Typical Flow

Login / Entry → select company context

Zones → create zones, set risk level, assign cameras

Workers → register workers (ID + +countrycode phone)

Live Monitor → real-time detection → snapshot → high-risk popup

Logs → pick offender → system ensures strike → prepare WhatsApp message

Reports → filter by date/zone/PPE → export CSV / PDF

📦 Packaging (optional)

Create a single EXE with PyInstaller:

pip install pyinstaller
pyinstaller --noconfirm --name CompliGuard --onefile --add-data "data/ui;data/ui" app.py
# Copy models/ and .env next to the EXE (or embed via --add-data)

🧩 Troubleshooting

Firebase credentials not found → check GOOGLE_APPLICATION_CREDENTIALS path.

bcrypt build error → install MS C++ Build Tools or use a prebuilt wheel.

OpenCV import error → reinstall opencv-python matching your Python version.

WhatsApp link not opening → ensure default browser is set; phone numbers must include +country code.

Slow/erratic detections → verify model paths; reduce input size/FPS; test with stable stream.

🗺 Roadmap

Multi-platform clients (web/mobile) backed by a local API service

Active-learning pipeline for PPE model (hard-frame mining + periodic retraining)

Deeper analytics with audit-ready weekly/monthly packs

🤝 Contributing

Fork the repo

git checkout -b feature/<FeatureName>

Commit your changes

git push origin feature/<FeatureName>

Open a Pull Request

📄 License

This project is licensed under the MIT License. See LICENSE for details.

📬 Contact

Your Name — your.email@example.com

Repo: https://github.com/
<your-username>/<your-repo>
