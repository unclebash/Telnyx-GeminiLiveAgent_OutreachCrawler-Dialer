import subprocess
import time
import sys
import re
import os

def start_tunnel():
    print("[*] Starting SSH tunnel via localhost.run...")
    # Run the SSH command with -T in a subprocess
    process = subprocess.Popen(
        ["ssh", "-T", "-o", "StrictHostKeyChecking=no", "-R", "80:localhost:8000", "nokey@localhost.run"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1  # Line-buffered
    )
    
    # Wait and read output to find the URL
    url = None
    start_time = time.time()
    
    # Read stdout line-by-line
    while time.time() - start_time < 20:
        # Check if process is still running
        if process.poll() is not None:
            print(f"❌ SSH Process exited with code {process.returncode}")
            break
            
        line = process.stdout.readline()
        if not line:
            time.sleep(0.5)
            continue
            
        cleaned_line = line.strip()
        print(f"SSH: {cleaned_line}")
        
        # Find http:// or https:// URL in the line
        match = re.search(r'https?://[a-zA-Z0-9.-]+\.localhost\.run', cleaned_line)
        if match:
            url = match.group(0)
            break
            
    if url:
        print("=" * 60)
        print(f"🎉 TUNNEL ESTABLISHED: {url}")
        print("=" * 60)
        # Write the URL to a local file so the parent agent can read it
        with open("tunnel_url.txt", "w") as f:
            f.write(url)
            
        # Keep process running
        try:
            while True:
                # Check if process died
                if process.poll() is not None:
                    print("❌ SSH Process died.")
                    break
                time.sleep(1)
        except KeyboardInterrupt:
            print("[*] Stopping tunnel...")
            process.terminate()
    else:
        # Read stderr to diagnose
        stderr_content = process.stderr.read()
        print(f"❌ Failed to retrieve tunnel URL. Stderr output:\n{stderr_content}")
        process.terminate()

if __name__ == "__main__":
    start_tunnel()
