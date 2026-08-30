# Ledger AI — Render Deployment Guide

This branch (`render`) contains all deployment manifests tailored for **Render**.

## Quick Deployment Steps

1. Go to [Render Dashboard](https://dashboard.render.com/) -> **New** -> **Web Service**.
2. Connect your GitHub repository `ankit-cybertron/Ledger-AI` and select branch **`render`**.
3. Render will automatically detect `render.yaml` or set:
   - **Environment**: Python
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn run:app --bind 0.0.0.0:$PORT --workers 2 --threads 4 --timeout 120`
4. Add Environment Variables:
   - `GROQ_API_KEY`: Your key
   - `GROQ_MODEL`: `openai/gpt-oss-120b`
   - `FLASK_ENV`: `production`
5. Click **Create Web Service**.
