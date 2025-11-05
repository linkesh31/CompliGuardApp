# CompliGuard — PPE Compliance Monitoring System

**CompliGuard** is a desktop safety app that detects PPE non-compliance (helmet, vest, gloves, boots) in real time, captures snapshot evidence, manages workers/zones/cameras, and produces audit-ready reports — all through a modern **Tkinter / CustomTkinter** UI and **Firebase Firestore** backend.

---

## Table of Contents
- [Features](#features)
- [Tech Stack](#tech-stack)
- [Screenshots](#screenshots)
- [Getting Started](#getting-started)
  - [Prerequisites](#prerequisites)
  - [Clone](#clone)
  - [Virtual Environment](#virtual-environment)
  - [Install Dependencies](#install-dependencies)
  - [Environment Variables](#environment-variables)
  - [Model Files](#model-files)
  - [Run](#run)
- [Project Structure](#project-structure)
- [User Roles & App Flow](#user-roles--app-flow)
- [Packaging](#packaging)
- [Troubleshooting](#troubleshooting)
- [Roadmap](#roadmap)
- [Contributing](#contributing)
- [License](#license)
- [Contact](#contact)

---

## Features

### Live Monitor (Real-time CV)
- Continuous inference with **10s verification window**
- **High-risk pop-up** escalation only when justified
- Snapshot evidence saved with timestamp/zone
- Camera **online/offline heartbeat** indicator

### Logs & Strikes
- Identify offender from worker registry
- Enforces **one strike per violation**
- Auto **cumulative strike count**
- Opens **WhatsApp** message (third strike text boldened)

### Zones & Cameras
- CRUD for zones with risk level: **low / med / high**
- Camera inventory with **RTSP/HTTP URL validation**
- Heartbeat metadata and status display

### Workers & Users
- **Unique worker IDs** and strict phone normalization (**+country code**)
- Admin management, **bcrypt** password hashing (preferred)

### Reports
- Trends by date, zone & risk, **PPE (including combinations)**, offender recurrence
- **CSV / PDF export**, quick date chips, preview tables

### UX
- Consistent light/beige theme, sidebar navigation, clear state feedback
- Keyboard-friendly forms and helpful error messages

---

## Tech Stack

- **Language:** Python 3.10–3.12 (Windows recommended)  
- **UI:** Tkinter + CustomTkinter  
- **Computer Vision:** OpenCV, Ultralytics **YOLOv8** (custom PPE + person model)  
- **Cloud:** Firebase Admin SDK (Firestore; optional Storage)  
- **Imaging:** Pillow (PIL)  
- **Utilities:** bcrypt, requests, python-dotenv, reportlab  
- **Messaging:** WhatsApp deep-link via default browser  

---

## Screenshots

> Add images in `docs/` and uncomment below.

