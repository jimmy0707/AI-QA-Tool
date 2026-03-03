# AI QA Decision Intelligence Platform

A web-based internal tool for QA teams — **Regression Optimizer** and **Manual-to-Automation Analyzer**, powered by local AI (Ollama / phi3).

---

## Architecture

```
Frontend (React)  →  Backend (FastAPI / Python)  →  Ollama (Local LLM)
     :3000                   :8000                        :11434
```

**No data leaves your network.** All AI inference runs locally via Ollama.

---

## Quick Start (Docker Compose)

### Prerequisites
- Docker & Docker Compose
- ~4 GB disk (for phi3 model)

### 1. Start all services
```bash
docker-compose up -d
```

### 2. Pull the AI model (one-time)
```bash
docker exec -it $(docker-compose ps -q ollama) ollama pull phi3
```

### 3. Open the app
Visit [http://localhost:3000](http://localhost:3000)

---

## Manual Setup (Without Docker)

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn main:app --reload --port 8000
```

### Frontend
```bash
cd frontend
npm install
npm start
```

### Ollama
```bash
# Install from https://ollama.com
ollama pull phi3
ollama serve
```

---

## Features

### Feature 1 — Regression Optimizer
- Upload Excel file (up to 2,000 test cases)
- Input execution days, team size, cases/tester/day
- AI assigns **Risk Score (1–10)** and **Priority (P1/P2/P3)**
- Recommends which cases fit within your capacity
- Exports styled Excel report with Summary sheet

### Feature 2 — Manual to Automation Analyzer
- Upload manual test cases Excel
- AI evaluates automation suitability: **Automatable / Partial / Not Suitable**
- Confidence percentage per test case
- Exports styled Excel report with statistics

---

## Excel Input Format

Your input file should have columns (any order, case-insensitive):
- `Title` or `Test Case Title`
- `Description` or `Test Description`
- `Steps` or `Test Steps`
- `Expected Result` or `Expected`
- `Severity` *(optional, for regression optimizer)*

---

## Environment Variables

| Variable | Default | Description |
|---|---|---|
| `OLLAMA_URL` | `http://localhost:11434` | Ollama server URL |
| `OLLAMA_MODEL` | `phi3` | LLM model to use |
| `REACT_APP_API_URL` | `http://localhost:8000` | Backend API URL |

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Checks API & Ollama status |
| POST | `/api/regression/analyze` | Analyze regression test cases |
| POST | `/api/automation/analyze` | Analyze automation suitability |
| GET | `/api/download/{id}/{type}` | Download generated Excel report |

---

## Tech Stack

| Layer | Technology |
|---|---|
| Frontend | React 18 |
| Backend | Python 3.11, FastAPI |
| AI Engine | Ollama (phi3 — local LLM) |
| Data Processing | pandas, openpyxl |
| Containerization | Docker Compose |
