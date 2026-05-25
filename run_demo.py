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

import random

def run_demo():
    test_files_dir = Path("test_files")
    if not test_files_dir.exists():
        print(f"{Colors.FAIL}Error: test_files directory not found{Colors.ENDC}")
        return

    # Criticality mapping based on extensions
    criticality_map = {
        ".txt": "standard",
        ".jpg": "critical",
        ".mp4": "classified",
        ".bin": "critical",
        ".pcap": "classified"
    }
    
    # Dynamically find all files in test_files/
    discovered_files = []
    for f in sorted(test_files_dir.iterdir()):
        if f.is_file() and not f.name.endswith(".diode_tmp"):
            ext = f.suffix.lower()
            criticality = criticality_map.get(ext, "standard")
            discovered_files.append((str(f), criticality))
    
    if not discovered_files:
        print(f"{Colors.WARNING}No files found in {test_files_dir}{Colors.ENDC}")
        return

    storage_dir = "demo_output/storage"
    if os.path.exists("demo_output"):
        import shutil
        shutil.rmtree("demo_output")
    os.makedirs(storage_dir, exist_ok=True)

    print(f"{Colors.HEADER}{Colors.BOLD}=== DATA DIODE E2E DEMO ==={Colors.ENDC}")
    print(f"Target Storage: {storage_dir}")
    print(f"Discovered {len(discovered_files)} files in {test_files_dir}/\n")
    
    for i, (file_path, criticality) in enumerate(discovered_files, 1):
        file_size = os.path.getsize(file_path) / 1024
        
        # Determine a random loss rate for this file to show robustness
        # 2% to 15% loss
        loss_rate = random.uniform(0.02, 0.15)
        
        log_step(i, f"Transferring {Colors.BOLD}{os.path.basename(file_path)}{Colors.ENDC} ({file_size:.1f} KB)")
        print(f"Security Level: {Colors.BOLD}{criticality.upper()}{Colors.ENDC}")
        print(f"Simulated Loss Rate: {Colors.WARNING}{loss_rate*100:.1f}%{Colors.ENDC}")
        
        # Run the simulation script
        cmd = [
            "python3", "simulate_diode.py", file_path, 
            "--criticality", criticality, 
            "--storage", storage_dir,
            "--loss-rate", str(loss_rate)
        ]
        env = os.environ.copy()
        env["PYTHONPATH"] = "."
        
        start_time = time.time()
        process = subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
        
        import selectors
        import sys
        
        selector = selectors.DefaultSelector()
        selector.register(process.stdout, selectors.EVENT_READ)
        
        # Stream output
        success = False
        interesting_logs = [
            "Sending manifest",      # Phase 0
            "Processing window",     # Step 1
            "chunking",              # Step 2
            "RS encoding",           # Step 4
            "Fountain encoding",     # Step 6
            "Triggering decode",     # Step 16
            "RS Decoder — Attempting to recover", # Step 17
            "Window complete",       # Step 19
            "reassembling file",     # Step 20
            "verification passed",   # Step 21
            "Stored file",           # Step 23
            "SUCCESS!",              # Final
            "METRICS:",               # Metrics
            "Window",                # Progress
        ]
        
        last_elapsed_print = 0
        while process.poll() is None:
            events = selector.select(timeout=0.1)
            
            # Print elapsed time every second if no output
            elapsed = int(time.time() - start_time)
            if elapsed > last_elapsed_print:
                sys.stdout.write(f"\r  {Colors.BOLD}{Colors.OKBLUE}[Timer: {elapsed}s]{Colors.ENDC}   ")
                sys.stdout.flush()
                last_elapsed_print = elapsed

            if events:
                line = process.stdout.readline()
                if not line: continue
                line = line.strip()
                
                # Clear the timer line before printing log
                sys.stdout.write("\r" + " " * 40 + "\r")
                
                if "SUCCESS!" in line:
                    print(f"  {Colors.OKGREEN}✔ {line.split('] ')[-1]}{Colors.ENDC}")
                    success = True
                elif "METRICS:" in line:
                    print(f"  {Colors.OKBLUE}📊 {line.split('] ')[-1]}{Colors.ENDC}")
                elif "ERROR" in line or "FAIL" in line or "Traceback" in line or "Exception" in line:
                    print(f"  {Colors.FAIL}{line}{Colors.ENDC}")
                elif any(x.lower() in line.lower() for x in interesting_logs):
                    # Format pipeline steps
                    msg = line.split('] ')[-1]
                    if "Processing window" in msg or "Starting" in msg or "stored" in msg:
                        print(f"  {Colors.OKBLUE}➡ {msg}{Colors.ENDC}")
                    elif "RS Decoder — Attempting to recover" in msg:
                        print(f"    {Colors.WARNING}🔧 {msg}{Colors.ENDC}")
                    else:
                        print(f"    {Colors.OKCYAN}• {msg}{Colors.ENDC}")
        
        # Final read for anything remaining
        for line in process.stdout:
            if "SUCCESS!" in line: success = True

        process.wait()
        sys.stdout.write("\r" + " " * 40 + "\r") # Final clear
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
