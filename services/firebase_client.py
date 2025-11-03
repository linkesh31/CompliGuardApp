# services/firebase_client.py
import os
from typing import Optional

# Force REST transport globally (must be set before firestore import)
os.environ["GOOGLE_CLOUD_DISABLE_GRPC"] = "true"

from google.cloud import firestore
from google.oauth2 import service_account

_DB: Optional[firestore.Client] = None


def _find_key_path() -> str:
    base_dir = os.path.dirname(os.path.dirname(__file__))  # project root
    env_path = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS", "")
    if env_path and os.path.exists(env_path):
        return env_path
    cred_path = os.path.join(base_dir, "firebase_key.json")
    if not os.path.exists(cred_path):
        raise FileNotFoundError(f"Firebase credential not found at {cred_path}")
    return cred_path


def get_db() -> firestore.Client:
    """
    Returns a Firestore client. We disable gRPC via env var above so the
    library uses HTTP/JSON (REST) which avoids Windows/HTTP2 lockups.
    """
    global _DB
    if _DB is not None:
        return _DB

    key_path = _find_key_path()
    creds = service_account.Credentials.from_service_account_file(
        key_path,
        scopes=["https://www.googleapis.com/auth/cloud-platform"],
    )

    # With gRPC disabled, default client will use REST under the hood.
    _DB = firestore.Client(project=creds.project_id, credentials=creds)
    return _DB
