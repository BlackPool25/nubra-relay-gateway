#!/usr/bin/env python3
"""
Host PC Credential Setup & Pre-Flight Validation Wizard
Configures and tests Nubra UAT master credentials before container startup.
Supports both:
1. Interactive Login (Phone + OTP + MPIN -> automatically extracts session_token)
2. Manual Entry (Paste pre-existing session_token and device_id)
"""

import os
import stat
import secrets
import urllib.request
import urllib.error
import json
import getpass
from typing import Tuple, Optional

def http_post(url: str, data: dict, headers: dict = None) -> Tuple[int, dict, dict]:
    headers = headers or {}
    headers["Content-Type"] = "application/json"
    headers["Accept"] = "application/json"

    body_bytes = json.dumps(data).encode("utf-8")
    req = urllib.request.Request(url, data=body_bytes, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp_headers = dict(resp.headers)
            try:
                resp_data = json.loads(resp.read().decode("utf-8"))
            except Exception:
                resp_data = {}
            return resp.status, resp_data, resp_headers
    except urllib.error.HTTPError as e:
        resp_headers = dict(e.headers)
        try:
            err_data = json.loads(e.read().decode("utf-8"))
        except Exception:
            err_data = {"error": str(e.reason)}
        return e.code, err_data, resp_headers
    except Exception as e:
        return 500, {"error": str(e)}, {}

def interactive_nubra_login(base_url: str) -> Optional[Tuple[str, str]]:
    """
    Executes Nubra REST API v3 4-step login sequence:
    Step 1 & 2: /sendphoneotp -> generate OTP
    Step 3: /verifyphoneotp -> get auth_token
    Step 4: /verifypin -> get session_token
    """
    print("\n--- Nubra UAT Interactive Terminal Login ---")
    phone = input("Enter registered mobile number: ").strip()
    if not phone:
        print("[!] Phone number is required.")
        return None

    device_id = input("Choose device ID for this session [default: workshop-pc]: ").strip() or "workshop-pc"

    # Step 1: Initial OTP generation request
    print("\n[Step 1/4] Initiating login flow with Nubra...")
    code, resp, _ = http_post(f"{base_url}/sendphoneotp", {"phone": phone})
    temp_token = resp.get("temp_token") or (resp.get("data", {}).get("temp_token") if isinstance(resp.get("data"), dict) else None)
    if code != 200 or not temp_token:
        print(f"[!] Step 1 failed (HTTP {code}): {resp.get('message', resp)}")
        return None

    # Step 2: Trigger OTP send with x-temp-token
    print("[Step 2/4] Requesting OTP dispatch to your phone...")
    code, resp, _ = http_post(
        f"{base_url}/sendphoneotp",
        {"phone": phone},
        headers={"x-temp-token": temp_token}
    )
    if code != 200:
        print(f"[!] Step 2 failed (HTTP {code}): {resp.get('message', resp)}")
        return None

    temp_token = resp.get("temp_token") or temp_token
    print(f"  ✓ {resp.get('message', 'OTP dispatched successfully!')}")

    # Step 3: Verify OTP
    otp = input("\nEnter the OTP received on SMS: ").strip()
    if not otp:
        print("[!] OTP cannot be empty.")
        return None

    print("\n[Step 3/4] Verifying OTP with Nubra...")
    code, resp, resp_hdrs = http_post(
        f"{base_url}/verifyphoneotp",
        {"phone": phone, "otp": otp},
        headers={"x-temp-token": temp_token, "x-device-id": device_id}
    )
    
    # Flexible token extraction across all possible Nubra response shapes
    data_dict = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    auth_token = (
        resp.get("auth_token")
        or resp.get("token")
        or resp.get("temp_token")
        or data_dict.get("auth_token")
        or data_dict.get("token")
        or resp_hdrs.get("x-auth-token")
        or resp_hdrs.get("authorization")
    )

    if code != 200 or not auth_token:
        print(f"[!] Step 3 failed (HTTP {code}): {resp.get('message', resp)}")
        print(f"    Payload received: {resp}")
        return None

    print(f"  ✓ {resp.get('message', 'OTP verified successfully.')}")

    # Step 4: Verify MPIN
    pin = getpass.getpass("\nEnter your 4-digit MPIN: ").strip()
    if not pin:
        print("[!] MPIN cannot be empty.")
        return None

    print("\n[Step 4/4] Validating MPIN...")
    code, resp, resp_hdrs = http_post(
        f"{base_url}/verifypin",
        {"pin": pin},
        headers={"Authorization": f"Bearer {auth_token}", "x-device-id": device_id}
    )

    data_dict = resp.get("data") if isinstance(resp.get("data"), dict) else {}
    session_token = (
        resp.get("session_token")
        or resp.get("token")
        or resp.get("auth_token")
        or data_dict.get("session_token")
        or data_dict.get("token")
        or resp_hdrs.get("authorization")
    )

    if code != 200 or not session_token:
        print(f"[!] Step 4 failed (HTTP {code}): {resp.get('message', resp)}")
        print(f"    Payload received: {resp}")
        return None

    print("  ✓ Login successful! Session token acquired.")
    return session_token, device_id

def test_nubra_credentials(base_url: str, session_token: str, device_id: str) -> bool:
    print("\nTesting Nubra UAT connectivity with credentials...")
    test_url = f"{base_url.rstrip('/')}/instruments"
    headers = {
        "Authorization": f"Bearer {session_token}",
        "x-device-id": device_id,
        "Accept": "application/json"
    }

    req = urllib.request.Request(test_url, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status == 200:
                print("  ✓ Verified! Nubra UAT accepted the master credentials.")
                return True
            else:
                print(f"  ✗ Unexpected response code: {response.status}")
                return False
    except urllib.error.HTTPError as e:
        print(f"  ✗ HTTP Error from Nubra UAT: {e.code} ({e.reason})")
        return False
    except Exception as e:
        print(f"  ✗ Connection failed: {e}")
        return False

def main():
    print("=======================================================")
    print("    Nubra UAT Relay & Queue Gateway: Setup Wizard     ")
    print("=======================================================\n")

    base_url = input("Nubra UAT Base URL [https://uatapi.nubra.io]: ").strip() or "https://uatapi.nubra.io"

    print("\nHow would you like to provide master Nubra UAT credentials?")
    print("  1. Interactive Login (Enter Phone, receive OTP on SMS, enter MPIN)")
    print("  2. Manual Entry (Paste already logged-in session_token & x-device-id)")
    choice = input("Select option [1/2] (default: 1): ").strip() or "1"

    if choice == "1":
        login_result = interactive_nubra_login(base_url)
        if not login_result:
            print("[!] Interactive login was not completed. Exiting.")
            return
        session_token, device_id = login_result
    else:
        session_token = input("Enter your master Nubra session_token: ").strip()
        device_id = input("Enter your master Nubra x-device-id: ").strip()
        if not session_token or not device_id:
            print("[!] Both session_token and device_id are required.")
            return

    # Verify session credentials against upstream
    test_ok = test_nubra_credentials(base_url, session_token, device_id)
    if not test_ok:
        proceed = input("\nProceed anyway and save configuration? (y/N): ").strip().lower()
        if proceed != "y":
            print("Setup aborted.")
            return

    # Student keys generation
    print("\n[2/3] Configuring Student Access Tokens...")
    num_students = input("How many student keys to generate? [5]: ").strip()
    count = int(num_students) if num_students.isdigit() else 5

    student_tokens = []
    for i in range(1, count + 1):
        rand_suffix = secrets.token_hex(4).upper()
        token = f"STU_TOKEN_{i:02d}_{rand_suffix}"
        student_tokens.append(token)

    allowed_tokens_str = ",".join(student_tokens)

    # Optional Student Detail Verification
    enable_verification = input("Enable student detail verification? (y/N) [default: N]: ").strip().lower() == "y"

    # Zero-Trust Ingress (Tailscale Funnel)
    print("\n[Optional] Zero-Trust Ingress (Tailscale Funnel):")
    print("  • Get an auth key from https://login.tailscale.com/admin/settings/keys")
    ts_authkey = input("  Enter Tailscale TS_AUTHKEY (press Enter to skip): ").strip()

    # Writing .env
    print("\n[3/3] Writing configuration to .env...")
    env_content = f"""# Generated by setup_credentials.py
NUBRA_UAT_BASE={base_url}
NUBRA_SESSION_TOKEN={session_token}
NUBRA_DEVICE_ID={device_id}

ENABLE_STUDENT_VERIFICATION={'true' if enable_verification else 'false'}
STUDENTS_FILE_PATH=students.json
ALLOWED_STUDENT_TOKENS={allowed_tokens_str}
STUDENT_TOKEN_PREFIX=STU_

MAX_UPSTREAM_RPS=85
MAX_HISTORICAL_RPM=50
REDIS_URL=redis://redis:6379/0
ENABLE_CACHE=true

# Zero-Trust Ingress
TS_AUTHKEY={ts_authkey}
"""

    env_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env")
    with open(env_path, "w", encoding="utf-8") as f:
        f.write(env_content)

    os.chmod(env_path, stat.S_IRUSR | stat.S_IWUSR)
    print(f"  ✓ Configuration saved to {env_path} (mode 0600)")

    # Print summary
    print("\n=======================================================")
    print("               SETUP COMPLETE!                         ")
    print("=======================================================")
    print(f"Generated {len(student_tokens)} Student Authorization Tokens:")
    for i, t in enumerate(student_tokens, 1):
        print(f"  Student {i:02d}: {t}")

    print("\nNext Steps to Start the Gateway:")
    print("  $ docker compose up -d")
    if ts_authkey:
        print("  (Tailscale Funnel is active and exposing https://nubra-relay.<your-tailnet>.ts.net)")
    else:
        print("  (Running locally on http://localhost:8000. Run 'tailscale funnel 8000' or add TS_AUTHKEY to .env)")

    print("\nStudents only need to replace 'https://uatapi.nubra.io' with your Tailscale Funnel URL.")
    print("=======================================================\n")

if __name__ == "__main__":
    main()
