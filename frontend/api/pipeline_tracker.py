"""
pipeline_tracker.py — Live Pipeline Execution Tracker & Terminal Logger.

Tracks real-time progress percentages, current execution stage,
and live terminal log outputs for the statement import & reconciliation pipeline.
"""

import sys
import io
import time
import threading
from datetime import datetime

_lock = threading.Lock()

_STATE = {
    "is_running": False,
    "progress": 0,
    "stage": "Idle",
    "logs": [],
    "last_updated": time.time()
}

def reset_tracker():
    with _lock:
        _STATE["is_running"] = False
        _STATE["progress"] = 0
        _STATE["stage"] = "Idle"
        _STATE["logs"] = []
        _STATE["last_updated"] = time.time()
    add_log("Pipeline tracker initialized. Ready for execution.", level="SYSTEM")

def start_pipeline(stage_name="Starting Import & Reconciliation Pipeline..."):
    with _lock:
        _STATE["is_running"] = True
        _STATE["progress"] = 5
        _STATE["stage"] = stage_name
        _STATE["logs"] = []
        _STATE["last_updated"] = time.time()
    add_log("🚀 Pipeline execution started...", level="SYSTEM")
    add_log("📥 Receiving and storing uploaded statement file...", level="INFO")

def update_progress(percent, stage_name, log_msg=None, level="INFO"):
    with _lock:
        _STATE["progress"] = max(0, min(100, percent))
        _STATE["stage"] = stage_name
        _STATE["last_updated"] = time.time()
    if log_msg:
        add_log(log_msg, level=level)

def add_log(msg, level="INFO"):
    if not msg or not msg.strip():
        return
    
    timestamp = datetime.now().strftime("%H:%M:%S")
    clean_msg = msg.strip()
    
    # Auto-detect log level tags if not explicitly provided
    if level == "INFO":
        upper = clean_msg.upper()
        if "EXACT" in upper or "RULE" in upper or "TOLERANCE" in upper:
            level = "RULE"
        elif "ML" in upper or "MODEL" in upper or "CONFIDENCE" in upper or "FALSE MATCHES" in upper or "TRUE MATCHES" in upper:
            level = "ML"
        elif "LLM" in upper or "AMBIGUOUS" in upper or "GROQ" in upper or "DECISION" in upper:
            level = "LLM"
        elif "RECON" in upper or "MATCHED" in upper or "LEDGER" in upper:
            level = "RECON"
        elif "COMPLETE" in upper or "SUCCESS" in upper or "SAVED" in upper:
            level = "SUCCESS"
        elif "ERROR" in upper or "FAIL" in upper or "EXCEPTION" in upper or "WARNING" in upper:
            level = "WARNING"

    log_entry = {
        "timestamp": timestamp,
        "level": level,
        "message": clean_msg
    }

    with _lock:
        _STATE["logs"].append(log_entry)
        # Keep last 200 logs max
        if len(_STATE["logs"]) > 200:
            _STATE["logs"] = _STATE["logs"][-200:]
        _STATE["last_updated"] = time.time()

def finish_pipeline(success=True, error_msg=None):
    with _lock:
        _STATE["is_running"] = False
        _STATE["progress"] = 100
        _STATE["last_updated"] = time.time()
        if success:
            _STATE["stage"] = "Pipeline Complete"
        else:
            _STATE["stage"] = "Pipeline Failed"

    if success:
        add_log("✅ Pipeline execution completed successfully! Dashboard refreshed.", level="SUCCESS")
    else:
        add_log(f"❌ Pipeline failed: {error_msg or 'Unknown error'}", level="ERROR")

def get_status():
    with _lock:
        return {
            "is_running": _STATE["is_running"],
            "progress": _STATE["progress"],
            "stage": _STATE["stage"],
            "logs": list(_STATE["logs"]),
            "last_updated": _STATE["last_updated"]
        }

class TerminalOutputRedirector(io.TextIOBase):
    """Intercepts stdout print calls and pushes line-by-line logs to PipelineTracker."""
    def __init__(self, original_stdout):
        self.original_stdout = original_stdout
        self.buffer = ""

    def write(self, buf):
        self.original_stdout.write(buf)
        self.original_stdout.flush()
        self.buffer += buf
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            if line.strip():
                add_log(line)
        return len(buf)

    def flush(self):
        self.original_stdout.flush()
        if self.buffer.strip():
            add_log(self.buffer)
            self.buffer = ""

class PipelineOutputCapture:
    """Context manager to stream stdout into terminal logs."""
    def __enter__(self):
        self.original_stdout = sys.stdout
        self.redirector = TerminalOutputRedirector(self.original_stdout)
        sys.stdout = self.redirector
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        sys.stdout = self.original_stdout
        self.redirector.flush()
