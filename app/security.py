import json
import os
from typing import Optional, Dict, Any, Tuple
from fastapi import Request, HTTPException, status
from app.config import settings

class StudentRegistry:
    def __init__(self):
        self.students: Dict[str, Dict[str, Any]] = {}
        self.token_to_student: Dict[str, str] = {}
        self.reload()

    def reload(self):
        if not settings.ENABLE_STUDENT_VERIFICATION:
            return
        if not os.path.exists(settings.STUDENTS_FILE_PATH):
            return

        try:
            with open(settings.STUDENTS_FILE_PATH, "r", encoding="utf-8") as f:
                data = json.load(f)
                students_list = data.get("students", [])
                self.students = {s["student_id"]: s for s in students_list}
                self.token_to_student = {s["token"]: s["student_id"] for s in students_list if "token" in s}
                print(f"[Registry] Loaded {len(self.students)} student profiles.")
        except Exception as e:
            print(f"[Registry] Error reading {settings.STUDENTS_FILE_PATH}: {e}")

    def verify_token(self, token: str) -> Tuple[bool, Optional[str]]:
        if not settings.ENABLE_STUDENT_VERIFICATION:
            # Simple token check against allowed set or prefix
            if token in settings.allowed_tokens_set or token.startswith(settings.STUDENT_TOKEN_PREFIX):
                return True, "student"
            return False, "Token not in allowed list"

        # Detailed verification against students.json
        student_id = self.token_to_student.get(token)
        if not student_id:
            return False, "Student not found in registry"

        student = self.students.get(student_id, {})
        if student.get("status") != "ACTIVE":
            return False, f"Student account is {student.get('status', 'INACTIVE')}"

        return True, student_id

student_registry = StudentRegistry()

def extract_client_token(request: Request) -> Optional[str]:
    """
    Transparently extract authentication token from standard Nubra header:
    - Authorization: Bearer <token>
    - or custom X-Student-Key fallback
    """
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    x_key = request.headers.get("X-Student-Key")
    if x_key:
        return x_key.strip()

    return None

def check_path_permission(path: str):
    """
    Deny sensitive or destructive endpoints.
    """
    clean_path = "/" + path.lower().lstrip("/")
    for blocked in settings.BLOCKED_PREFIXES:
        if clean_path.startswith(blocked):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "status": "error",
                    "error_code": "FORBIDDEN_ENDPOINT",
                    "message": f"Endpoint '{clean_path}' is restricted in the workshop environment."
                }
            )

def authenticate_student(request: Request) -> str:
    """
    Validates student credentials transparently.
    """
    token = extract_client_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "error",
                "error_code": "UNAUTHORIZED",
                "message": "Missing Bearer token in Authorization header."
            }
        )

    is_valid, identifier = student_registry.verify_token(token)
    if not is_valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "status": "error",
                "error_code": "INVALID_TOKEN",
                "message": f"Authorization denied: {identifier}"
            }
        )

    return identifier or "student"
