import base64
import json

import pytest

from polymarket_bot.oci_vault import (
    ALLOWED_SECRET_KEYS,
    decode_secret_json,
    secret_id_from_instance_details,
    secret_id_from_metadata_payload,
)


def encoded(value):
    return base64.b64encode(json.dumps(value).encode()).decode()


def test_decode_vault_secret_requires_exact_account_keys():
    payload = {name: "value" for name in ALLOWED_SECRET_KEYS}
    assert decode_secret_json(encoded(payload)) == payload
    with pytest.raises(RuntimeError, match="exactly the four"):
        decode_secret_json(encoded({**payload, "POLYMARKET_MODE": "live"}))


def test_decode_vault_secret_rejects_invalid_or_blank_content():
    with pytest.raises(RuntimeError):
        decode_secret_json("not-base64")
    payload = {name: "value" for name in ALLOWED_SECRET_KEYS}
    payload["POLYMARKET_SIGNER_PRIVATE_KEY"] = ""
    with pytest.raises(RuntimeError, match="blank"):
        decode_secret_json(encoded(payload))


def test_secret_ocid_can_come_from_non_secret_instance_metadata():
    assert secret_id_from_metadata_payload({
        "metadata": {"polybot_secret_ocid": " ocid1.vaultsecret.example "}
    }) == "ocid1.vaultsecret.example"
    assert secret_id_from_metadata_payload({}) == ""


def test_secret_ocid_can_come_from_console_editable_freeform_tag():
    instance = type("Instance", (), {
        "freeform_tags": {"polybot_secret_ocid": " ocid1.vaultsecret.example "}
    })()
    assert secret_id_from_instance_details(instance) == "ocid1.vaultsecret.example"
    assert secret_id_from_instance_details(object()) == ""
