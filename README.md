CompliGuard – PPE Compliance Monitoring System
Overview

CompliGuard is a desktop safety application that automates detection of PPE (helmet, vest, gloves, boots), records violations with evidence, manages workers and zones, and produces audit-ready reports.
It’s built in Python with a polished Tkinter/CustomTkinter UI and uses Firebase/Firestore as the cloud data layer.

Key Features

Real-time PPE Detection: Live Monitor with verification window, high-risk escalation, and snapshot evidence.

Logs & Strikes: Identify offender, record single-strike per violation, auto-count cumulative strikes, WhatsApp escalation.

Zones & Cameras: CRUD for zones with risk levels; camera management with URL validation and online/offline heartbeat.

Workers & Users: Unique worker IDs, phone validation (+country code), admin management with hashed passwords.

Reports: Daily trends, zone and risk breakdowns, PPE (including combinations), offender recurrence, CSV/PDF export.

Theming & UX: Consistent light/beige UI shell with header + sidebar, keyboard-friendly forms, and status feedback.

Tech Stack

Language: Python 3.10–3.12 (Windows recommended)

UI: Tkinter + CustomTkinter

CV / Inference: OpenCV, Ultralytics YOLOv8 (custom PPE model + person model)

Storage: Firebase Admin SDK (Firestore; optional Storage)

Imaging: Pillow (PIL)

Utilities: bcrypt (password hashing), requests, python-dotenv (env), reportlab (PDF export)

Messaging: WhatsApp deep-link via default browser

Getting Started
Prerequisites

Windows 10/11 with Python 3.10 – 3.12 installed and on PATH

A Firebase project and service account JSON

If you plan to use GPU acceleration, install appropriate NVIDIA drivers/CUDA (optional)

Microsoft Visual C++ Redistributable (for some wheels like bcrypt, if needed)

Clone the repository
git clone https://github.com/<your-username>/<your-repo>.git
cd <your-repo>

Create & activate a virtual environment
# Windows (PowerShell)
python -m venv .venv
.venv\Scripts\activate

Install dependencies

If you don’t have a requirements.txt yet, create one with the block below.

pip install -r requirements.txt


requirements.txt (recommended)

# UI
customtkinter==5.2.2
# CV
opencv-python==4.10.0.84
numpy>=1.24
pillow>=9.5
ultralytics>=8.2.0
# Firebase / Google
firebase-admin>=6.5.0
google-cloud-firestore>=2.14.0
google-cloud-storage>=2.16.0
# Utilities
bcrypt>=4.1.2
requests>=2.31.0
python-dotenv>=1.0.1
reportlab>=4.0.9


If any wheel fails to build (e.g., bcrypt), install Microsoft C++ Build Tools or temporarily skip bcrypt during development; the app supports a fallback hasher for dev environments.

Environment Variables

Create a file named .env in the project root (or set variables in your system environment).

# Firebase / Google
GOOGLE_APPLICATION_CREDENTIALS=./secrets/serviceAccount.json
FIREBASE_PROJECT_ID=<your-project-id>

# App brand (shown in UI headers / reports)
COMPANY_NAME=<Your Company Name>

# Optional: Email/SMTP if you later wire emailer.py
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=


Put your service account JSON at ./secrets/serviceAccount.json or update the path accordingly.
Firestore security rules should allow the Admin SDK (service account) to read/write the collections used by the app.

Model Files

Place your trained model files in a models/ folder:

models/
├─ best.pt                 # custom PPE detector (helmet/vest/gloves/boots)
└─ yolov8n.pt              # person model (if required by your pipeline)


You can rename paths in services/ppe_infer.py if your filenames differ.

Running the App
# Make sure the venv is activated
python app.py


On first run, the app will initialize Firebase, render the UI shell, and load the default company/site context after you sign in.

Project Structure

A typical layout for this repository:

<repo-root>/
├─ app.py                      # App entry
├─ data/ui/                    # Icons, avatars, logos, card images
├─ models/                     # YOLO weights (best.pt, yolov8n.pt)
├─ secrets/                    # serviceAccount.json (not committed)
├─ services/
│  ├─ firebase_client.py       # Firestore init
│  ├─ firebase_auth.py         # Auth helpers (if used)
│  ├─ users.py                 # Admin user CRUD (hashing, status)
│  ├─ workers.py               # Worker CRUD + phone validation
│  ├─ zones.py                 # Zones + cameras + heartbeat helpers
│  ├─ violations.py            # Strikes & offender update helpers
│  ├─ ppe_infer.py             # Inference wrapper (YOLO)
│  ├─ ui_theme.py              # Theme tokens/styling
│  ├─ ui_assets.py             # Icon/image loader
│  ├─ session.py               # In-memory session store
│  ├─ messaging.py             # WhatsApp deeplink builder
│  ├─ reports.py               # CSV / PDF export helpers
│  └─ security.py              # Hashing (bcrypt preferred)
├─ views/ or pages/            # (If split) Tkinter page classes
├─ .env                        # Your environment variables
└─ requirements.txt


(Exact filenames may vary; the above mirrors the code you provided.)

Usage Guide
Roles

Superadmin: Multi-site view; manage companies and admins.

Admin / Safety Officer: Daily operations for one company/site.

Main Pages

Login/Entry: Authenticate and select company context.

Dashboard/Home: Quick KPIs and navigation.

Zones: Create/edit zones, assign cameras, set risk levels.

Workers: Add/modify workers with unique IDs and phone normalization (+country code).

Live Monitor: Real-time detection; 10s verification timer; high-risk popup; snapshots.

Logs: Search violations, identify offender, record strikes, open WhatsApp message.

Reports: Preview and export CSV/PDF for trends, zones, PPE combos, offenders, daily counts.

Add Admin / Profile: Manage users and account details.

Data Model (Core Collections)

users: { email, name, role, company_id, status, password_hash, ... }

workers: { worker_id, name, phone, active, company_id, created_at }

zones: { name, description, risk_level, company_id, created_at, updated_at }

cameras: { name, rtsp_url/http, zone_id, company_id, mode, online, last_heartbeat }

violations: { ts, zone_id, company_id, snapshot, offender_id/name/phone, ppe_status, risk }

strikes: { worker_id, worker_name, company_id, violation_id, created_at }

Packaging (Optional)

To create a single-file executable with PyInstaller:

pip install pyinstaller
pyinstaller --noconfirm --name CompliGuard --onefile --add-data "data/ui;data/ui" app.py
# Copy models/ and .env next to the EXE or embed with --add-data as needed

Troubleshooting

App can’t find Firebase credentials
Ensure GOOGLE_APPLICATION_CREDENTIALS points to your service account JSON and the path exists.

bcrypt fails to install
Install Microsoft C++ Build Tools (or use the precompiled wheel for your Python version). As a temporary dev fallback, you can comment bcrypt in requirements and rely on the built-in dev hasher—but use bcrypt in production.

OpenCV import errors
Reinstall opencv-python matching your Python version. If you installed opencv-contrib-python, keep only one OpenCV distribution in the venv.

WhatsApp message doesn’t open
Make sure the default browser is set and that the device can access https://wa.me/<number> links. Phone numbers must be stored with +<countrycode>.

Models load slowly or detections are erratic
Verify model paths in services/ppe_infer.py, ensure the models/ directory exists, and test with a stable camera stream. Consider lowering input size or frame rate for slower CPUs.

Contributing

Fork the repository

Create a feature branch: git checkout -b feature/<FeatureName>

Commit changes: git commit -m "Add <FeatureName>"

Push: git push origin feature/<FeatureName>

Open a Pull Request

License

If you don’t already have a license file, this project can be released under MIT License. Add a LICENSE file or update this section to your chosen license.

Acknowledgments

Supervisors and reviewers who provided feedback during development

Safety officers and testers who validated the workflow and reports

Open-source authors of Python, CustomTkinter, Ultralytics, and Firebase SDKs

Contact

Your Name – your.email@example.com

Project Link – https://github.com/<your-username>/<your-repo>
