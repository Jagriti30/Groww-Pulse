"""Standalone entry script to launch the Groww Pulse Control Tower Web Dashboard (Phase 7)."""

import uvicorn

if __name__ == "__main__":
    print("=" * 70)
    print("[*] GROWW PULSE CONTROL TOWER -- WEB DASHBOARD & PIPELINE STUDIO")
    print("=" * 70)
    print("[+] Starting Uvicorn web server...")
    print("[+] Access Dashboard at: http://127.0.0.1:8000")
    print("[!] Press Ctrl+C to stop the server.\n")
    
    uvicorn.run("pulse.web.api:app", host="127.0.0.1", port=8000, reload=True)
