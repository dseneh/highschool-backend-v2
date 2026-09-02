import base64
import os

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from django.test import SimpleTestCase, override_settings

from common.crypto import decrypt_text, encrypt_text


TEST_KEY = base64.b64encode(b"k" * 32).decode("ascii")


@override_settings(SECRET_AES_KEY=TEST_KEY)
class CryptoSecurityTests(SimpleTestCase):
    def test_aes_gcm_round_trip(self):
        envelope = encrypt_text("sensitive-value")
        self.assertEqual(envelope["v"], 2)
        self.assertEqual(envelope["alg"], "AES-GCM")
        self.assertEqual(decrypt_text(envelope), "sensitive-value")

    def test_aes_gcm_rejects_tampering(self):
        envelope = encrypt_text("sensitive-value")
        raw = bytearray(base64.b64decode(envelope["data"]))
        raw[0] ^= 1
        envelope["data"] = base64.b64encode(bytes(raw)).decode("ascii")
        with self.assertRaises(InvalidTag):
            decrypt_text(envelope)

    def test_legacy_cfb_envelope_remains_readable(self):
        key = base64.b64decode(TEST_KEY)
        iv = os.urandom(16)
        cipher = Cipher(algorithms.AES(key), modes.CFB(iv))
        encryptor = cipher.encryptor()
        ciphertext = encryptor.update(b"legacy-value") + encryptor.finalize()
        envelope = {
            "iv": base64.b64encode(iv).decode("ascii"),
            "data": base64.b64encode(ciphertext).decode("ascii"),
        }
        self.assertEqual(decrypt_text(envelope), "legacy-value")
