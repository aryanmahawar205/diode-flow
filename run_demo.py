"""
Demo runner for Data Diode simulation.
Transfers multiple file types sequentially with clear status logging.
"""

import os
import subprocess
import time
from pathlib import Path

# ANSI colors for clear console output
class Colors:
    HEADER = '\033[95m'
    OKBLUE = '\033[94m'
    OKCYAN = '\033[96m'
    OKGREEN = '\033[92m'
    WARNING = '\033[93m'
    FAIL = '\033[91m'
    ENDC = '\033[0m'
    BOLD = '\033[1m'

def log_step(step, description):
    print(f"\n{Colors.BOLD}{Colors.OKCYAN}[STEP {step}]{Colors.ENDC} {description}")

def run_demo():
    test_files = [
        ("test_files/sample.txt", "standard"),
        ("test_files/photo.jpg", "critical"),
        ("test_files/video_clip.mp4", "classified")
    ]
    
    storage_dir = "/tmp/data_diode_demo"
    if os.path.exists(storage_dir):
        import shutil
        shutil.rmtree(storage_dir)
    os.makedirs(storage_dir, exist_ok=True)

    print(f"{Colors.HEADER}{Colors.BOLD}=== DATA DIODE E2E DEMO ==={Colors.ENDC}")
    print(f"Target Storage: {storage_dir}")
    
    for i, (file_path, criticality) in enumerate(test_files, 1):
        if not os.path.exists(file_path):
            print(f"{Colors.WARNING}Skipping {file_path}: File not found{Colors.ENDC}")
            continue

        file_size = os.path.getsize(file_path) / 1024
        log_step(i, f"Transferring {Colors.BOLD}{os.path.basename(file_path)}{Colors.ENDC} ({file_size:.1f} KB)")
        print(f"Security Level: {Colors.BOLD}{criticality.upper()}{Colors.ENDC}")
        
        # Run the simulation script
        # Using subprocess to capture and filter output for a cleaner demo feel
        cmd = ["python3", "simulate_diode.py", file_path, "--criticality", criticality, "--storage", storage_dir]
        env = os.environ.copy()
        env["PYTHONPATH"] = "."
        
        start_time = time.time()
        process = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        
        # Stream output
        success = False
        interesting_logs = [
            "Sending manifest",      # Phase 0
            "Processing window",     # Step 1
            "chunking",              # Step 2
            "RS encoding",           # Step 4
            "Fountain encoding",     # Step 6
            "Triggering decode",     # Step 16
            "RS decode",             # Step 17
            "Window complete",       # Step 19
            "reassembling file",     # Step 20
            "verification passed",   # Step 21
            "Stored file",           # Step 23
            "SUCCESS!"               # Final
        ]
        for line in process.stdout:
            line = line.strip()
            if not line: continue
            
            if "SUCCESS!" in line:
                print(f"  {Colors.OKGREEN}✔ {line.split('] ')[-1]}{Colors.ENDC}")
                success = True
            elif "ERROR" in line or "FAIL" in line or "Traceback" in line or "Exception" in line:
                print(f"  {Colors.FAIL}{line}{Colors.ENDC}")
            elif any(x.lower() in line.lower() for x in interesting_logs):
                # Format pipeline steps
                msg = line.split('] ')[-1]
                if "Processing window" in msg or "Starting" in msg:
                    print(f"  {Colors.OKBLUE}➡ {msg}{Colors.ENDC}")
                else:
                    print(f"    {Colors.OKCYAN}• {msg}{Colors.ENDC}")
            else:
                # Show all output for debugging
                print(f"    {line}")

        process.wait()
        duration = time.time() - start_time
        
        if success:
            print(f"{Colors.OKGREEN}{Colors.BOLD}Result: {os.path.basename(file_path)} transferred successfully in {duration:.2f}s{Colors.ENDC}")
        else:
            print(f"{Colors.FAIL}{Colors.BOLD}Result: {os.path.basename(file_path)} transfer failed!{Colors.ENDC}")
        
        time.sleep(2) # Brief pause between files for readability

    print(f"\n{Colors.HEADER}{Colors.BOLD}=== DEMO COMPLETE ==={Colors.ENDC}")
    print(f"All verified files are located in: {storage_dir}")

if __name__ == "__main__":
    run_demo()
