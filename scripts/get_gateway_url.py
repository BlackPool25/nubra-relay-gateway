#!/usr/bin/env python3
"""
Gateway URL & Status Inspector
Detects running containers and extracts the public Tailscale Funnel URL.
"""

import subprocess
import json
import urllib.request
import sys

def check_local_health():
    try:
        with urllib.request.urlopen("http://localhost:8000/health", timeout=2) as resp:
            data = json.loads(resp.read().decode())
            return True, data
    except Exception:
        return False, None

def get_tailscale_container_url():
    # Check if docker is running
    cmd_ps = ["docker", "ps", "--filter", "name=nubra_relay_tailscale", "--format", "{{.Names}}"]
    try:
        out = subprocess.check_output(cmd_ps, text=True).strip()
        if not out:
            return None, "Container 'nubra_relay_tailscale' is not running."
    except Exception as e:
        return None, f"Docker command failed: {e}"

    # Extract tailscale status from inside container
    cmd_status = ["docker", "exec", "nubra_relay_tailscale", "tailscale", "status", "--json"]
    try:
        status_raw = subprocess.check_output(cmd_status, text=True)
        status_json = json.loads(status_raw)
        
        # Self node details
        self_node = status_json.get("Self", {})
        dns_name = self_node.get("DNSName", "").rstrip(".")
        cert_domains = status_json.get("CertDomains", [])

        if cert_domains:
            domain = cert_domains[0]
        elif dns_name:
            domain = dns_name
        else:
            domain = None

        if domain:
            return f"https://{domain}", None
        else:
            return None, "Tailscale node active, but domain not yet assigned."
    except Exception as e:
        # Fallback to tailscale funnel status
        try:
            status_text = subprocess.check_output(["docker", "exec", "nubra_relay_tailscale", "tailscale", "funnel", "status"], text=True)
            for line in status_text.splitlines():
                if "https://" in line:
                    for word in line.split():
                        if word.startswith("https://"):
                            return word, None
        except Exception:
            pass
        return None, f"Could not inspect Tailscale container: {e}"

def main():
    print("=======================================================")
    print("        Nubra Relay Gateway: URL & Ingress Status      ")
    print("=======================================================\n")

    # 1. Local container health
    healthy, health_data = check_local_health()
    if healthy:
        print("  ✓ Local Service: RUNNING (http://localhost:8000)")
        print(f"    Redis Connected: {health_data.get('redis_connected')}")
    else:
        print("  ✗ Local Service: NOT DETECTED on port 8000")
        print("    (Have you started containers via 'docker compose up -d'?)")

    print("\n--- Public Zero-Trust Ingress (Tailscale Funnel) ---")
    public_url, err = get_tailscale_container_url()

    if public_url:
        print(f"\n  🚀 Public Gateway URL:  {public_url}")
        print("\n  Share this URL with students. Example student config:")
        print(f"  BASE_URL = \"{public_url}\"")
        print("  headers  = {\"Authorization\": \"Bearer STU_TOKEN_01_XXXX\"}\n")
    else:
        print(f"  Status: {err or 'Funnel not active'}")
        print("\n  Troubleshooting:")
        print("  1. Ensure containers are running: 'docker compose up -d'")
        print("  2. Verify TS_AUTHKEY is set in .env")
        print("  3. Check Tailscale logs: 'docker compose logs tailscale'")

    print("=======================================================\n")

if __name__ == "__main__":
    main()
