from __future__ import annotations

import base64
import json
import os
from typing import Any
from urllib.request import ProxyHandler, Request, build_opener


ALLOWED_SECRET_KEYS = {
    "POLYMARKET_SIGNER_PRIVATE_KEY",
    "POLYMARKET_WALLET_ADDRESS",
    "POLYMARKET_RELAYER_API_KEY",
    "POLYMARKET_RELAYER_API_KEY_ADDRESS",
}


def decode_secret_json(content: str) -> dict[str, str]:
    """Decode one OCI BASE64 secret containing a restricted JSON object."""
    try:
        raw = base64.b64decode(content, validate=True).decode("utf-8")
        payload: Any = json.loads(raw)
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("OCI Vault secret must be base64 JSON") from exc
    if not isinstance(payload, dict) or set(payload) != ALLOWED_SECRET_KEYS:
        raise RuntimeError("OCI Vault JSON must contain exactly the four Polymarket account keys")
    if not all(isinstance(value, str) and value.strip() for value in payload.values()):
        raise RuntimeError("OCI Vault JSON contains a blank or non-string value")
    return payload


def secret_id_from_metadata_payload(payload: Any) -> str:
    if not isinstance(payload, dict):
        return ""
    # OCI IMDSv2 exposes console-managed tags directly. Custom metadata remains
    # a fallback for instances that were configured using the older workflow.
    for section_name in ("freeformTags", "metadata"):
        section = payload.get(section_name)
        if isinstance(section, dict):
            value = section.get("polybot_secret_ocid", "")
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def _instance_metadata_payload() -> dict[str, Any]:
    request = Request(
        "http://169.254.169.254/opc/v2/instance/",
        headers={"Authorization": "Bearer Oracle"},
    )
    # Never let host proxy variables redirect an OCI metadata request.
    with build_opener(ProxyHandler({})).open(request, timeout=2) as response:
        payload = json.loads(response.read().decode("utf-8"))
    if not isinstance(payload, dict):
        raise RuntimeError("OCI instance metadata returned an invalid payload")
    return payload


def load_oci_vault_env_if_configured() -> bool:
    """Load secrets with the VM Instance Principal; never print secret content."""
    if all(os.getenv(name) for name in ALLOWED_SECRET_KEYS):
        return False
    secret_id = os.getenv("OCI_POLYBOT_SECRET_OCID", "").strip()
    use_metadata = os.getenv("OCI_POLYBOT_USE_INSTANCE_METADATA", "").lower() in {
        "1", "true", "yes", "on"
    }
    if not secret_id and use_metadata:
        try:
            metadata = _instance_metadata_payload()
            secret_id = secret_id_from_metadata_payload(metadata)
        except Exception as exc:
            raise RuntimeError("Could not read polybot_secret_ocid from OCI instance metadata") from exc
    if not secret_id:
        return False
    try:
        import oci
    except ImportError as exc:
        raise RuntimeError("Install requirements-live-sdk.txt for OCI Vault support") from exc
    signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    client = oci.secrets.SecretsClient(config={}, signer=signer)
    bundle = client.get_secret_bundle(secret_id=secret_id, stage="CURRENT").data
    content = getattr(getattr(bundle, "secret_bundle_content", None), "content", None)
    if not isinstance(content, str):
        raise RuntimeError("OCI Vault returned an unsupported or empty secret bundle")
    for name, value in decode_secret_json(content).items():
        # An explicit runtime variable wins, which supports emergency rotation.
        os.environ.setdefault(name, value)
    return True
