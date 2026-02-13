"""Authentication and user management for LLM Council."""

import os
import json
import secrets
import hashlib
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
from collections import defaultdict
import jwt

# Configuration
DATA_DIR = os.getenv("DATA_DIR", "./data")
USERS_DIR = os.path.join(DATA_DIR, "users")
OTP_EXPIRY_MINUTES = 10
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 7  # Reduced from 30 days
MAX_OTP_ATTEMPTS = 5
OTP_LOCKOUT_MINUTES = 15

# Rate limiting storage (in-memory, resets on restart)
_rate_limit_store = defaultdict(list)
_otp_attempts = defaultdict(int)

# Environment detection
IS_PRODUCTION = os.getenv("ENVIRONMENT", "development").lower() == "production"


def validate_jwt_secret():
    """
    Validate JWT_SECRET at startup.
    Fails fast if missing or weak in production.
    """
    jwt_secret = os.getenv("JWT_SECRET", "")
    
    if not jwt_secret:
        if IS_PRODUCTION:
            print("FATAL: JWT_SECRET environment variable is required in production")
            sys.exit(1)
        else:
            print("WARNING: Using default JWT_SECRET for development. DO NOT use in production!")
            return "dev-secret-change-in-production"
    
    # Require minimum 32 bytes (64 hex characters) for production
    if IS_PRODUCTION and len(jwt_secret) < 32:
        print(f"FATAL: JWT_SECRET must be at least 32 characters in production (got {len(jwt_secret)})")
        sys.exit(1)
    
    return jwt_secret


def validate_email_config():
    """
    Validate email configuration at startup.
    Fails fast if not configured in production.
    """
    email_api_key = os.getenv("EMAIL_API_KEY", "")
    email_service = os.getenv("EMAIL_SERVICE", "").lower()
    
    if IS_PRODUCTION and not email_api_key:
        print("FATAL: EMAIL_API_KEY is required in production")
        sys.exit(1)
    
    if IS_PRODUCTION and email_service not in ["resend", "sendgrid", "mailgun"]:
        print(f"FATAL: EMAIL_SERVICE must be one of [resend, sendgrid, mailgun] in production (got '{email_service}')")
        sys.exit(1)


# Initialize and validate configuration
JWT_SECRET = validate_jwt_secret()
validate_email_config()


def ensure_users_dir():
    """Ensure the users directory exists."""
    Path(USERS_DIR).mkdir(parents=True, exist_ok=True)


def get_user_path(email: str) -> str:
    """Get the file path for a user by email."""
    # Use hash of email as filename for privacy
    email_hash = hashlib.sha256(email.lower().encode()).hexdigest()
    return os.path.join(USERS_DIR, f"{email_hash}.json")


def create_user(email: str) -> Dict[str, Any]:
    """
    Create a new user or return existing user.
    
    Args:
        email: User's email address
        
    Returns:
        User dict with id, email, created_at
    """
    ensure_users_dir()
    email = email.lower().strip()
    
    # Check if user already exists
    existing_user = get_user_by_email(email)
    if existing_user:
        return existing_user
    
    # Create new user
    user_id = secrets.token_urlsafe(16)
    user = {
        "id": user_id,
        "email": email,
        "created_at": datetime.utcnow().isoformat(),
        "token_version": 0,  # For future token revocation
    }
    
    # Save to file
    path = get_user_path(email)
    with open(path, 'w') as f:
        json.dump(user, f, indent=2)
    
    return user


def get_user_by_email(email: str) -> Optional[Dict[str, Any]]:
    """
    Get user by email address.
    
    Args:
        email: User's email address
        
    Returns:
        User dict or None if not found
    """
    email = email.lower().strip()
    path = get_user_path(email)
    
    if not os.path.exists(path):
        return None
    
    with open(path, 'r') as f:
        return json.load(f)


def get_user_by_id(user_id: str) -> Optional[Dict[str, Any]]:
    """
    Get user by user ID (slower, scans all users).
    
    Args:
        user_id: User's unique ID
        
    Returns:
        User dict or None if not found
    """
    ensure_users_dir()
    
    for filename in os.listdir(USERS_DIR):
        if filename.endswith('.json'):
            path = os.path.join(USERS_DIR, filename)
            try:
                with open(path, 'r') as f:
                    user = json.load(f)
                    if user.get('id') == user_id:
                        return user
            except (json.JSONDecodeError, KeyError):
                continue
    
    return None


def check_rate_limit(key: str, max_requests: int, window_minutes: int) -> bool:
    """
    Check if a rate limit has been exceeded.
    
    Args:
        key: Rate limit key (e.g., IP address or email)
        max_requests: Maximum requests allowed
        window_minutes: Time window in minutes
        
    Returns:
        True if within limit, False if exceeded
    """
    now = datetime.utcnow()
    cutoff = now - timedelta(minutes=window_minutes)
    
    # Clean old entries
    _rate_limit_store[key] = [
        timestamp for timestamp in _rate_limit_store[key]
        if timestamp > cutoff
    ]
    
    # Check limit
    if len(_rate_limit_store[key]) >= max_requests:
        return False
    
    # Record this request
    _rate_limit_store[key].append(now)
    return True


def generate_otp() -> str:
    """Generate a 6-digit OTP."""
    return str(secrets.randbelow(1000000)).zfill(6)


def store_otp(email: str, otp: str):
    """
    Store OTP for a user with expiry time.
    
    Args:
        email: User's email address
        otp: Generated OTP
    """
    user = get_user_by_email(email)
    if not user:
        user = create_user(email)
    
    # Reset attempt counter when new OTP is generated
    _otp_attempts[email] = 0
    
    # Add OTP and expiry to user record
    user['otp'] = otp
    user['otp_expires_at'] = (datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()
    user['otp_created_at'] = datetime.utcnow().isoformat()
    
    # Save updated user
    path = get_user_path(email)
    with open(path, 'w') as f:
        json.dump(user, f, indent=2)


def verify_otp(email: str, otp: str) -> tuple[bool, Optional[str]]:
    """
    Verify OTP for a user with attempt limiting.
    
    Args:
        email: User's email address
        otp: OTP to verify
        
    Returns:
        Tuple of (success: bool, error_message: Optional[str])
    """
    user = get_user_by_email(email)
    if not user:
        return False, "Invalid email or OTP"
    
    stored_otp = user.get('otp')
    expiry = user.get('otp_expires_at')
    
    if not stored_otp or not expiry:
        return False, "No OTP found. Please request a new one"
    
    # Check expiry
    if datetime.utcnow() > datetime.fromisoformat(expiry):
        return False, "OTP has expired. Please request a new one"
    
    # Check attempt limit
    if _otp_attempts[email] >= MAX_OTP_ATTEMPTS:
        return False, f"Too many failed attempts. Please wait {OTP_LOCKOUT_MINUTES} minutes and request a new OTP"
    
    # Check OTP match
    if stored_otp != otp:
        _otp_attempts[email] += 1
        remaining = MAX_OTP_ATTEMPTS - _otp_attempts[email]
        if remaining > 0:
            return False, f"Invalid OTP. {remaining} attempts remaining"
        else:
            return False, f"Too many failed attempts. Please wait {OTP_LOCKOUT_MINUTES} minutes and request a new OTP"
    
    # Clear OTP and attempts after successful verification
    user.pop('otp', None)
    user.pop('otp_expires_at', None)
    user.pop('otp_created_at', None)
    _otp_attempts.pop(email, None)
    
    path = get_user_path(email)
    with open(path, 'w') as f:
        json.dump(user, f, indent=2)
    
    return True, None


def generate_jwt(user_id: str) -> str:
    """
    Generate JWT token for a user.
    
    Args:
        user_id: User's unique ID
        
    Returns:
        JWT token string
    """
    payload = {
        'user_id': user_id,
        'exp': datetime.utcnow() + timedelta(days=JWT_EXPIRY_DAYS),
        'iat': datetime.utcnow(),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def verify_jwt(token: str) -> Optional[str]:
    """
    Verify JWT token and extract user_id.
    Also verifies that the user still exists.
    
    Args:
        token: JWT token string
        
    Returns:
        user_id if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        user_id = payload.get('user_id')
        
        # Verify user still exists
        user = get_user_by_id(user_id)
        if not user:
            return None
        
        return user_id
    except jwt.ExpiredSignatureError:
        return None
    except jwt.InvalidTokenError:
        return None


async def send_otp_email(email: str, otp: str) -> bool:
    """
    Send OTP via email using configured email service.
    
    Args:
        email: Recipient email address
        otp: OTP code to send
        
    Returns:
        True if sent successfully, False otherwise
    """
    email_service = os.getenv("EMAIL_SERVICE", "").lower()
    email_api_key = os.getenv("EMAIL_API_KEY", "")
    email_from = os.getenv("EMAIL_FROM", "noreply@llm-council.app")
    
    # In production, email must be configured
    if IS_PRODUCTION and not email_api_key:
        print("ERROR: Cannot send OTP in production without EMAIL_API_KEY")
        return False
    
    # Development mode: print OTP to console
    if not email_api_key:
        print(f"\n{'='*50}")
        print(f"DEV MODE - OTP for {email}: {otp}")
        print(f"{'='*50}\n")
        return True
    
    subject = "Your LLM Council Login Code"
    html_body = f"""
    <html>
        <body style="font-family: Arial, sans-serif; padding: 20px;">
            <h2>Your Login Code</h2>
            <p>Use this code to log in to LLM Council:</p>
            <h1 style="background: #f0f0f0; padding: 20px; text-align: center; letter-spacing: 8px;">
                {otp}
            </h1>
            <p style="color: #666;">This code will expire in {OTP_EXPIRY_MINUTES} minutes.</p>
            <p style="color: #666; font-size: 12px;">If you didn't request this code, you can safely ignore this email.</p>
        </body>
    </html>
    """
    
    try:
        if email_service == "resend":
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.resend.com/emails",
                    headers={
                        "Authorization": f"Bearer {email_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "from": email_from,
                        "to": [email],
                        "subject": subject,
                        "html": html_body,
                    },
                )
                return response.status_code == 200
        
        elif email_service == "sendgrid":
            import httpx
            async with httpx.AsyncClient() as client:
                response = await client.post(
                    "https://api.sendgrid.com/v3/mail/send",
                    headers={
                        "Authorization": f"Bearer {email_api_key}",
                        "Content-Type": "application/json",
                    },
                    json={
                        "personalizations": [{"to": [{"email": email}]}],
                        "from": {"email": email_from},
                        "subject": subject,
                        "content": [{"type": "text/html", "value": html_body}],
                    },
                )
                return response.status_code == 202
        
        else:
            print(f"ERROR: Unsupported email service: {email_service}")
            return False
            
    except Exception as e:
        print(f"Error sending email: {e}")
        return False
