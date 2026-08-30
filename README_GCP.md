# Ledger AI — Google Cloud Run Deployment Guide

This branch (`google-cloud`) contains all deployment manifests and container definitions tailored for **Google Cloud Run**.

## Prerequisites
- Google Cloud Console Account
- Enabled APIs: Cloud Build API, Artifact Registry API, Cloud Run Admin API

## Quick Deployment Steps

1. Go to **Google Cloud Console** -> **Cloud Run** -> **Create Service**.
2. Select **Continuously deploy from a repository** -> Choose **Cloud Build** or **Developer Connect**.
3. Select your repository `ankit-cybertron/Ledger-AI` and branch **`google-cloud`**.
4. Build Type: **Dockerfile** (`/Dockerfile`).
5. Set Configuration:
   - **Service Name**: `ledger-ai`
   - **Region**: `asia-south1 (Mumbai)` or `us-central1 (Iowa)` or `europe-west1`
   - **Authentication**: `Allow unauthenticated invocations`
   - **Capacity**: `Request-based` (Free Tier)
6. Add Environment Variables under **Containers, Networking, Security**:
   - `GROQ_API_KEY`: Your Groq API key
   - `GROQ_MODEL`: `openai/gpt-oss-120b`
   - `FLASK_ENV`: `production`
7. Click **Create** to deploy.
