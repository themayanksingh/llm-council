"""Authentication and user management for LLM Council."""

import os
import json
import secrets
import hashlib
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any
import jwt

# Configuration
DATA_DIR = os.getenv("DATA_DIR", "./data")
USERS_DIR = os.path.join(DATA_DIR, "users")
OTP_EXPIRY_MINUTES = 10
JWT_SECRET = os.getenv("JWT_SECRET", "dev-secret-change-in-production")
JWT_ALGORITHM = "HS256"
JWT_EXPIRY_DAYS = 30


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
            with open(path, 'r') as f:
                user = json.load(f)
                if user.get('id') == user_id:
                    return user
    
    return None


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
    
    # Add OTP and expiry to user record
    user['otp'] = otp
    user['otp_expires_at'] = (datetime.utcnow() + timedelta(minutes=OTP_EXPIRY_MINUTES)).isoformat()
    
    # Save updated user
    path = get_user_path(email)
    with open(path, 'w') as f:
        json.dump(user, f, indent=2)


def verify_otp(email: str, otp: str) -> bool:
    """
    Verify OTP for a user.
    
    Args:
        email: User's email address
        otp: OTP to verify
        
    Returns:
        True if OTP is valid and not expired, False otherwise
    """
    user = get_user_by_email(email)
    if not user:
        return False
    
    stored_otp = user.get('otp')
    expiry = user.get('otp_expires_at')
    
    if not stored_otp or not expiry:
        return False
    
    # Check expiry
    if datetime.utcnow() > datetime.fromisoformat(expiry):
        return False
    
    # Check OTP match
    if stored_otp != otp:
        return False
    
    # Clear OTP after successful verification
    user.pop('otp', None)
    user.pop('otp_expires_at', None)
    path = get_user_path(email)
    with open(path, 'w') as f:
        json.dump(user, f, indent=2)
    
    return True


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
    
    Args:
        token: JWT token string
        
    Returns:
        user_id if valid, None otherwise
    """
    try:
        payload = jwt.decode(token, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        return payload.get('user_id')
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
    
    if not email_api_key:
        # Development mode: print OTP to console
        print(f"\n{'='*50}")
        print(f"OTP for {email}: {otp}")
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
            # Fallback: print to console
            print(f"\n{'='*50}")
            print(f"OTP for {email}: {otp}")
            print(f"{'='*50}\n")
            return True
            
    except Exception as e:
        print(f"Error sending email: {e}")
        return False
