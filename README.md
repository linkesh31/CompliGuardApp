# CompliGuard – PPE Compliance Monitoring System

## Overview

CompliGuard is a desktop application that automates PPE compliance monitoring in industrial environments. It performs real-time detection of helmet, vest, gloves, and boots; captures snapshot evidence; manages workers, zones, and cameras; and generates audit-ready reports. The app features a polished Tkinter/CustomTkinter UI and uses Firebase Firestore as the cloud data layer.

## Key Features

-   🖥️ **Live Monitor (Real-time CV)**: Continuous inference with 10s verification window, high-risk pop-up escalation, snapshot evidence, and camera online/offline heartbeat
-   🧾 **Logs & Strikes**: Identify offender from worker registry, one strike per violation, auto cumulative strike count, WhatsApp escalation (third-strike text emphasized)
-   🗺️ **Zones & Cameras**: CRUD for zones with low/medium/high risk, camera URL validation (RTSP/HTTP), heartbeat status
-   👷 **Workers & Users**: Unique worker IDs, strict phone normalization (+country code), admin management with bcrypt password hashing
-   📈 **Reports**: Trends by date, zone & risk, PPE (including combinations), offender recurrence, CSV/PDF export
-   🎛️ **Consistent UX**: Light/beige theme, sidebar navigation, keyboard-friendly forms, clear error/status feedback

## Tech Stack

-   **Language**: Python 3.10–3.12 (Windows recommended)
-   **UI**: Tkinter + CustomTkinter
-   **Computer Vision**: OpenCV, Ultralytics YOLOv8 (custom PPE model + person model)
-   **Cloud**: Firebase Admin SDK (Firestore; optional Storage)
-   **Imaging**: Pillow (PIL)
-   **Utilities**: bcrypt, requests, python-dotenv, reportlab
-   **Messaging**: WhatsApp deep-link via default browser

## Getting Started

### Prerequisites

-   Windows 10/11 with Python 3.10–3.12 on PATH
-   A Firebase project and service account JSON
-   Microsoft Visual C++ Redistributable (helps with wheels like bcrypt)
-   (Optional) NVIDIA drivers/CUDA if you plan to use GPU

### Installation

1. Clone the repository

```bash
git clone https://github.com/yourusername/compliguard.git
cd compliguard
```

2. Create & activate a virtual environment
#### PowerShell
```bash
python -m venv .venv
. .venv\Scripts\activate
```

3. Install dependencies

```bash
pip install -r requirements.txt
```

4. If you don’t have requirements.txt, create it with:

```bash
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
```

5. If bcrypt fails to build, install MS C++ Build Tools or omit it during development and re-enable for production.

6. Set up environment variables
Create .env (you can keep a .env.example and copy it):

7. GOOGLE_APPLICATION_CREDENTIALS=./secrets/serviceAccount.json
FIREBASE_PROJECT_ID=your-project-id
COMPANY_NAME=Your Company

8. Optional email settings (only if you wire email sender)
```bash
SMTP_HOST=
SMTP_PORT=
SMTP_USER=
SMTP_PASS=
```

9. Add model files

```
models/
├─ best.pt        # custom PPE model (helmet/vest)
└─ yolov8n.pt     # person model (if your pipeline uses it)
└─ gloves_shoes_yolo9e.pt     # custom PPE model (gloves/shoes)
```

10. Update paths in services/ppe_infer.py if you use different names.

11. Run the application
 ```bash
python app.py
```

## Project Structure

```
compliguard/
├── app.py
├── models/                 # YOLO weights
├── pages/                  # Frontend + UI
├── services/
│   ├── firebase_client.py
│   ├── users.py            # admin CRUD + hashing
│   ├── workers.py          # worker CRUD + phone normalization
│   ├── zones.py            # zones + cameras + heartbeat helpers
│   ├── violations.py       # strikes + offender updates
│   ├── ppe_infer.py        # YOLO inference wrapper
│   ├── messaging.py        # WhatsApp deep-link builder
│   ├── reports.py          # CSV/PDF export helpers
│   ├── ui_theme.py         # theme tokens/components
│   ├── ui_assets.py        # icon/image loader
│   └── session.py          # in-memory session
├── data/ui/                # UI assets (logos/icons)
├── .env
└── requirements.txt
```

## User Roles

-   **Superadmin**: Multi-site/company management and admin creation
-   **Admin / Safety Officer**: Day-to-day operations for one site (zones, workers, live monitor, logs, reports)

## Contributing

1. Fork the repository
2. Create your feature branch 
3. Commit your changes 
4. Push to the branch 
5. Open a Pull Request

## License

This project is licensed under the MIT License — see the LICENSE file for details.

## Acknowledgments

-   Site supervisors and safety officers who tested the workflow
-   Project supervisors and mentors
-   Open-source communities behind Python, CustomTkinter, Ultralytics, and Firebase

## Contact

Linkesh Jaya Prakash Rao — [linkeshjpr.25@gmail.com]
Project Link: [https://github.com/linkesh31/CompliGuardApp]
