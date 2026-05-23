import base64
import hashlib
import hmac
import json
import logging
import random
import struct
from datetime import datetime, timedelta, timezone

from ainara.framework.template_manager import TemplateManager

try:
    from solana.rpc.api import Client
    from solana.rpc.types import TokenAccountOpts
    from solders.pubkey import Pubkey
    from solders.signature import Signature

    SOLANA_AVAILABLE = True
except ImportError:
    SOLANA_AVAILABLE = False

logger = logging.getLogger(__name__)

# Collection Address for Ainara Genesis Pass
NFT_COLLECTION_ADDRESS = "GhDd7CvvM4vMzJ3FpWkitUpwQwTj8XUn3KvdENyxHYiX"
METADATA_PROGRAM_ID = "metaqbxxUerdq28cj1RbAWkYQm3ybzjb6a8bt518x1s"
TOKEN_PROGRAM_ID = "TokenkegQfeZyiNwAJbNbGKPFXCWuBvf9Ss623VQ5DA"
TOKEN_2022_PROGRAM_ID = "TokenzQdBNbLqP5VEhdkAS6EPFLC1PHnBqCXEpPxuEb"

RPC_URL = "https://api.mainnet-beta.solana.com"
RPC_CANDIDATES = [
    "https://api.mainnet-beta.solana.com",
    "https://solana-rpc.publicnode.com",
    "https://rpc.ankr.com/solana",
    "https://solana.drpc.org",
    "https://api.mainnet.solana.com",
]
AUTH_MESSAGE = "Authenticate to Ainara Polaris"

# Internal secret for signing session data.
# Changing this invalidates all existing sessions.
AUTH_SECRET = NFT_COLLECTION_ADDRESS[::-1].encode("utf-8")


class AuthManager:
    def __init__(self, storage_backend):
        self.storage = storage_backend
        self.client = Client(RPC_CANDIDATES[0]) if SOLANA_AVAILABLE else None
        self.template_manager = TemplateManager()

    def get_portal_html(self):
        return self.template_manager.render(
            "framework.auth.portal", {"auth_message": AUTH_MESSAGE}
        )

    def _create_session_token(self, wallet: str, timestamp: str) -> str:
        """Creates a signed, base64 encoded session token."""
        # 1. Create payload
        payload = {"w": wallet, "t": timestamp}
        json_bytes = json.dumps(payload, separators=(",", ":")).encode("utf-8")

        # 2. Sign payload
        signature = hmac.new(
            AUTH_SECRET, json_bytes, hashlib.sha256
        ).hexdigest()

        # 3. Encode payload to hide contents from casual view
        b64_payload = base64.urlsafe_b64encode(json_bytes).decode("utf-8")

        # 4. Return format: payload.signature
        return f"{b64_payload}.{signature}"

    def _get_metadata_pda(self, mint_key: Pubkey) -> Pubkey:
        """Derives the Metadata PDA for a given mint."""
        program_id = Pubkey.from_string(METADATA_PROGRAM_ID)
        seeds = [
            b"metadata",
            bytes(program_id),
            bytes(mint_key),
        ]
        pda, _ = Pubkey.find_program_address(seeds, program_id)
        return pda

    def _check_nft_collection(self, mint_address: str, client: Client) -> bool:
        """
        Verifies if the mint belongs to the required verified collection.
        Manually parses the Metaplex Metadata account data with bounds checking.
        """
        try:
            mint_key = Pubkey.from_string(mint_address)
            metadata_pda = self._get_metadata_pda(mint_key)

            account_info = client.get_account_info(metadata_pda)
            if not account_info.value:
                return False

            data = account_info.value.data
            data_len = len(data)

            # --- Manual Parsing of Metaplex Metadata ---
            # Layout:
            # Key(1) + UpdateAuth(32) + Mint(32) = 65 bytes
            offset = 65
            if offset > data_len:
                return False

            # Data Struct: Name, Symbol, URI (all variable length strings)
            # String layout: Length(4) + Bytes
            for _ in range(3):  # Skip Name, Symbol, URI
                if offset + 4 > data_len:
                    return False
                length = struct.unpack("<I", data[offset: offset + 4])[0]
                offset += 4 + length

            # SellerFeeBasisPoints(2)
            offset += 2

            # Creators (Option<Vec<Creator>>)
            if offset >= data_len:
                return False
            has_creators = data[offset]
            offset += 1
            if has_creators:
                if offset + 4 > data_len:
                    return False
                creators_len = struct.unpack("<I", data[offset: offset + 4])[
                    0
                ]
                offset += 4
                # Each creator: Address(32) + Verified(1) + Share(1) = 34 bytes
                offset += creators_len * 34

            # PrimarySaleHappened(1) + IsMutable(1)
            offset += 2

            # --- Optional Fields (Check bounds before reading) ---

            # EditionNonce (Option<u8>)
            if offset >= data_len:
                return False  # Truncated before we reached Collection

            if data[offset]:  # has_nonce
                offset += 2
            else:
                offset += 1

            # TokenStandard (Option<u8>)
            if offset >= data_len:
                # Data ends here (V1.0/V1.1), so no Collection field exists
                return False

            if data[offset]:  # has_token_std
                offset += 2
            else:
                offset += 1

            # Collection (Option<Collection>)
            if offset >= data_len:
                return False

            has_collection = data[offset]
            offset += 1

            if has_collection:
                # Collection struct: Verified(1) + Key(32)
                if offset + 33 > data_len:
                    return False

                verified = data[offset]
                offset += 1
                collection_key_bytes = data[offset: offset + 32]
                collection_key = Pubkey.from_bytes(collection_key_bytes)

                target_collection = Pubkey.from_string(NFT_COLLECTION_ADDRESS)

                if verified and collection_key == target_collection:
                    return True

            return False

        except Exception as e:
            logger.error(f"Error checking NFT metadata: {e}")
            return False

    def _verify_wallet_has_nft(
        self, wallet_address: str, client: Client
    ) -> bool:
        """Checks if the wallet holds the required NFT using the provided client."""
        try:
            pubkey = Pubkey.from_string(wallet_address)

            # Check both Standard Token Program and Token-2022
            programs_to_check = [TOKEN_PROGRAM_ID, TOKEN_2022_PROGRAM_ID]

            for prog_id in programs_to_check:
                opts = TokenAccountOpts(
                    program_id=Pubkey.from_string(prog_id),
                    encoding="base64",
                )
                response = client.get_token_accounts_by_owner(pubkey, opts)

                if response.value:
                    for account in response.value:
                        # Parse raw token data
                        # Layout: Mint(32) + Owner(32) + Amount(8) + ...
                        data = account.account.data
                        amount = struct.unpack("<Q", data[64:72])[0]

                        # Check if it's an NFT (Amount == 1)
                        if amount == 1:
                            mint_bytes = data[:32]
                            mint = Pubkey.from_bytes(mint_bytes)

                            # Verify if this specific NFT belongs to our collection
                            if self._check_nft_collection(str(mint), client):
                                return True
            return False
        except Exception as e:
            # Propagate exception to trigger failover in _execute_rpc_check
            raise e

    def _execute_rpc_check(self, wallet_address: str):
        """
        Round-robin check through RPC candidates to verify NFT ownership.
        Returns:
            True: NFT found (Authorized)
            False: NFT NOT found (Revoked)
            None: Could not connect to any RPC (Network Error)
        """
        if not SOLANA_AVAILABLE:
            return None

        # Create a rotated list starting from a random index
        start_idx = random.randint(0, len(RPC_CANDIDATES) - 1)
        rotated_candidates = (
            RPC_CANDIDATES[start_idx:] + RPC_CANDIDATES[:start_idx]
        )

        for rpc_url in rotated_candidates:
            try:
                logger.info(f"Attempting NFT verification with RPC: {rpc_url}")
                client = Client(rpc_url)

                # Check if wallet has NFT
                if self._verify_wallet_has_nft(wallet_address, client):
                    # Success: Update main client and return True
                    self.client = client
                    return True

                # If we got here, RPC worked but NFT was not found.
                # We assume the node is synced and the user truly lacks the NFT.
                return False

            except Exception as e:
                logger.warning(f"RPC check failed for {rpc_url}: {e}")
                continue

        logger.error("All RPC candidates failed.")
        return None

    def _verify_session_token(self, token: str):
        """Decodes and verifies a session token. Returns dict or None."""
        try:
            if not token or "." not in token:
                return None

            b64_payload, received_sig = token.split(".", 1)

            # 1. Re-calculate signature
            json_bytes = base64.urlsafe_b64decode(b64_payload)
            expected_sig = hmac.new(
                AUTH_SECRET, json_bytes, hashlib.sha256
            ).hexdigest()

            # 2. Verify signature (constant time comparison)
            if not hmac.compare_digest(expected_sig, received_sig):
                return None

            return json.loads(json_bytes)
        except Exception:
            return None

    def is_authorized(self):
        """Checks if a valid, non-expired session exists in metadata."""
        try:
            # Retrieve the single signed token blob
            token = self.storage.get_metadata("auth_session_token")

            if not token:
                return {"authorized": False, "reason": "no_session"}

            session = self._verify_session_token(token)
            if not session:
                return {"authorized": False, "reason": "tampered_or_invalid"}

            wallet = session.get("w")
            last_verified = session.get("t")

            # Check daily if user is authorized
            verified_dt = datetime.fromisoformat(last_verified)
            time_delta = datetime.now(timezone.utc) - verified_dt
            if time_delta > timedelta(days=1):
                # Attempt to refresh authorization via RPC check
                rpc_result = self._execute_rpc_check(wallet)

                if rpc_result is True:
                    now = datetime.now(timezone.utc).isoformat()
                    new_token = self._create_session_token(wallet, now)
                    self.storage.set_metadata("auth_session_token", new_token)
                    return {"authorized": True, "wallet": wallet}

                if rpc_result is False:
                    # RPC worked, but NFT is missing. Revoke session.
                    self.storage.delete_metadata("auth_session_token")
                    return {"authorized": False, "reason": "revoked"}

                if time_delta < time_delta(days=7):
                    # give a grace period of 7 days to update (allow offline)
                    return {"authorized": True, "wallet": wallet}
                else:
                    # rpc_result is None (Network Error)
                    # Do NOT delete metadata, allow retry later, but force update
                    return {"authorized": False, "reason": "network_error"}

            return {"authorized": True, "wallet": wallet}
        except Exception as e:
            logger.error(f"Auth check failed: {e}")
            return {"authorized": False, "reason": "error"}

    def verify_and_login(self, wallet_address, signature_arr, message_text):
        """Verifies signature and checks for NFT ownership."""
        if not SOLANA_AVAILABLE:
            return False, "Solana libraries not installed on server."

        try:
            # 1. Verify Signature
            pubkey = Pubkey.from_string(wallet_address)
            msg_bytes = message_text.encode("utf-8")

            if isinstance(signature_arr, list):
                sig_bytes = bytes(signature_arr)
            else:
                return False, "Invalid signature format"

            sig_obj = Signature.from_bytes(sig_bytes)

            if not sig_obj.verify(pubkey, msg_bytes):
                return False, "Invalid signature."

            # 2. Check for Access NFT
            logger.info(
                f"Signature valid. Checking NFTs for {wallet_address}..."
            )

            rpc_result = self._execute_rpc_check(wallet_address)

            if rpc_result is True:
                # 3. Success - Store Session
                now = datetime.now(timezone.utc).isoformat()
                token = self._create_session_token(wallet_address, now)
                self.storage.set_metadata("auth_session_token", token)

                logger.info(f"Auth successful for {wallet_address}")
                return True, "Authentication successful"

            if rpc_result is None:
                return False, "Network error: Could not reach Solana RPCs."

            return False, "No valid Access NFT found in wallet."

        except Exception as e:
            logger.error(f"Verification failed: {e}")
            return False, str(e)
