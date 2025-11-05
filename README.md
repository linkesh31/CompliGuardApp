CompliGuard — PPE Compliance Monitoring System

CompliGuard is a desktop safety application that automates PPE compliance monitoring in industrial environments. It performs real-time detection of helmet, vest, gloves, and boots; captures snapshot evidence; manages workers, zones, and cameras; and generates audit-ready reports. The system features a polished Tkinter / CustomTkinter UI and uses Firebase Firestore as the cloud data layer.

Table of Contents

Key Features

Tech Stack

Screenshots

Getting Started

Prerequisites

Installation

Environment Variables

Model Files

Run

Project Structure

User Roles

Packaging (Optional)

Troubleshooting

Roadmap

Contributing

License

Acknowledgments

Contact

Key Features

🖥️ Live Monitor (Real-time CV) — Continuous inference, 10-second verification window, high-risk pop-up, snapshot evidence, and camera online/offline heartbeat.

🧾 Logs & Strikes — Identify offender from worker registry, one strike per violation, auto cumulative strike count, and WhatsApp escalation (third-strike wording emphasized).

🗺️ Zones & Cameras — CRUD for zones with risk levels (low / medium / high), camera URL validation (RTSP/HTTP), and heartbeat status.

👷 Workers & Users — Unique worker IDs, strict phone normalization (+country code), admin management with bcrypt password hashing.

📈 Reports — Trends by date, zone & risk, PPE (including combinations), offender recurrence, CSV/PDF export with preview tables and quick date chips.

🎛️ Consistent UX — Light/beige theme, sidebar navigation, keyboard-friendly forms, and clear error/status feedback.

Tech Stack

Language: Python 3.10–3.12 (Windows recommended)

UI: Tkinter + CustomTkinter

Computer Vision: OpenCV, Ultralytics YOLOv8 (custom PPE model + person model)

Cloud: Firebase Admin SDK (Firestore; optional Storage)

Imaging: Pillow (PIL)

Utilities: bcrypt, requests, python-dotenv, reportlab

Messaging: WhatsApp deep-link via default browser

Screenshots

Place screenshots in docs/ and link them here (optional).

![Live Monitor](docs/live-monitor.png)
![Logs](docs/logs.png)
![Reports](docs/reports.png)
![Zones & Workers](docs/zones-workers.png)

Getting Started
Prerequisites

Windows 10/11 with Python 3.10–3.12 on PATH

A Firebase project and service account JSON

Microsoft Visual C++ Redistributable (helps with wheels like bcrypt)

(Optional) NVIDIA drivers/CUDA if you plan to use GPU

Installation

Clone the repository

git clone https://github.com/yourusername/compliguard.git
cd compliguard


Create & activate a virtual environment

# PowerShell
python -m venv .venv
. .venv\Scripts\activate


Install dependencies

pip install -r requirements.txt


If you don’t have requirements.txt, create it with this content:

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


If bcrypt fails to build, install MS C++ Build Tools or temporarily omit it for development (re-enable for production).

Environment Variables

Create a .env file in the project root (you can commit a .env.example and copy it):

GOOGLE_APPLICATION_CREDENTIALS=./secrets/serviceAccount.json
FIREBASE_PROJECT_ID=your-project-id
COMPANY_NAME=Your Company

# Optional email settings (only if you wire email sender)
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=


Place your service account at ./secrets/serviceAccount.json and ensure the secrets/ folder is gitignored.

Model Files

Put your YOLO weights here (filenames adjustable in services/ppe_infer.py):

models/
├─ best.pt        # custom PPE model (helmet/vest/gloves/boots)
└─ yolov8n.pt     # person model (if your pipeline uses it)

Run
python app.py

Project Structure
compliguard/
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
│  ├─ messaging.py             # WhatsApp deeplink builder
│  ├─ reports.py               # CSV/PDF export helpers
│  ├─ ui_theme.py              # theme tokens/components
│  ├─ ui_assets.py             # icon/image loader
│  └─ session.py               # in-memory session
├─ data/ui/                    # UI assets (logos/icons)
├─ docs/                       # screenshots (optional)
├─ .env
└─ requirements.txt

User Roles

Superadmin — Multi-site/company management and admin creation

Admin / Safety Officer — Day-to-day operations for one site (zones, workers, live monitor, logs, reports)

Packaging (Optional)

Create a single executable with PyInstaller:

pip install pyinstaller
pyinstaller --noconfirm --name CompliGuard --onefile --add-data "data/ui;data/ui" app.py
# Copy models/ and .env next to the EXE (or embed via --add-data)

Troubleshooting

Firebase credentials not found — Check GOOGLE_APPLICATION_CREDENTIALS path and file.

bcrypt install error — Install MS C++ Build Tools or use a prebuilt wheel; keep bcrypt for production.

OpenCV import error — Reinstall opencv-python matching your Python version; avoid multiple OpenCV wheels.

WhatsApp link not opening — Ensure default browser is set; phone numbers include +country code.

Slow/erratic detections — Verify model paths, reduce input size/FPS for weak CPUs, ensure a stable camera stream.

Roadmap

Multiple-platform client (web/mobile) backed by a local API service

Model quality pipeline with active learning and periodic retraining

Deeper analytics with audit-ready weekly/monthly packs

Contributing

Fork the repository

Create your feature branch: git checkout -b feature/AmazingFeature

Commit your changes: git commit -m "Add AmazingFeature"

Push to the branch: git push origin feature/AmazingFeature

Open a Pull Request

License

This project is licensed under the MIT License — see the LICENSE file for details.

Acknowledgments

Site supervisors and safety officers who tested the workflow

Project supervisors and mentors

Open-source communities behind Python, CustomTkinter, Ultralytics, and Firebase

Contact

Your Name – your.email@example.com

Project Link: https://github.com/yourusername/compliguard
