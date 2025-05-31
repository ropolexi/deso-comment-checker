#From https://github.com/deso-protocol/deso-python-sdk
import hashlib
import json
import requests
from typing import Optional, Dict, Any, List, Union
from pprint import pprint
from typing import Tuple, Optional
import binascii
from bip32 import BIP32, base58
from mnemonic import Mnemonic
from coincurve import PrivateKey
import hashlib
from typing import Optional
from ecdsa import SigningKey, SECP256k1
from ecdsa.util import sigencode_der
import time
from requests.exceptions import RequestException

class DeSoDexClient:
    """
    A Python client for interacting with the DeSo DEX endpoints on a DeSo node.
    """

    def __init__(self, is_testnet: bool=False, seed_phrase_or_hex=None, passphrase=None, index=0, node_url=None):
        self.is_testnet = is_testnet

        desoKeyPair, err = create_key_pair_from_seed_or_seed_hex(
            seed_phrase_or_hex, passphrase, index, is_testnet,
        )
        if desoKeyPair is None:
            raise ValueError(err)
        self.deso_keypair = desoKeyPair

        if node_url is None:
            if is_testnet:
                node_url = "https://test.deso.org"
            else:
                node_url = "https://node.deso.org"
        self.node_url = node_url.rstrip("/")

    def sign_single_txn(self, unsigned_txn_hex: str) -> str:
        try:
            # Decode hex transaction to bytes
            txn_bytes = bytes.fromhex(unsigned_txn_hex)

            # Double SHA256 hash of the transaction bytes
            first_hash = hashlib.sha256(txn_bytes).digest()
            txn_hash = hashlib.sha256(first_hash).digest()

            # Create signing key from private key bytes
            signing_key = SigningKey.from_string(self.deso_keypair.private_key, curve=SECP256k1)

            # Sign the hash
            signature = signing_key.sign_digest(txn_hash, sigencode=sigencode_der)

            # Convert signature to hex
            signature_hex = signature.hex()

            return signature_hex

        except Exception as e:
            return None

    def submit_txn(self, unsigned_txn_hex: str, signature_hex: str) -> dict:
        """
        Submit a transaction with signature to the specified node URL.

        Args:
            node_url: Base URL of the node
            unsigned_txn_hex: Hex string of unsigned transaction
            signature_hex: Hex string of transaction signature

        Returns:
            dict: Parsed response from the server

        Raises:
            requests.exceptions.RequestException: If request fails
            json.JSONDecodeError: If response parsing fails
            ValueError: If server returns non-200 status code
        """
        submit_url = f"{self.node_url}/api/v0/submit-transaction"

        payload = {
            "UnsignedTransactionHex": unsigned_txn_hex,
            "TransactionSignatureHex": signature_hex
        }

        headers = {
            "Origin": self.node_url,
            "Content-Type": "application/json"
        }

        response = requests.post(
            submit_url,
            data=json.dumps(payload),
            headers=headers
        )

        if response.status_code != 200:
            raise ValueError(
                f"Error status returned from {submit_url}: "
                f"{response.status_code}, {response.text}"
            )

        return response.json()

    from typing import Dict, List, Any

    def submit_atomic_txn(
            self,
            incomplete_atomic_txn_hex: str,
            unsigned_inner_txn_hexes: List[str],
            txn_signatures_hex: List[str]
    ) -> Dict[str, Any]:
        """
        Submit an atomic transaction using the designated endpoint.

        Args:
            node_url: Base URL of the node
            transaction_hex: Hex string of the incomplete atomic transaction
            unsigned_inner_txn_hexes: List of unsigned inner transaction hex strings
            txn_signatures_hex: List of transaction signatures in hex

        Returns:
            dict: Parsed JSON response

        Raises:
            requests.exceptions.RequestException: If request fails
            json.JSONDecodeError: If response parsing fails
            ValueError: If server returns non-200 status code
        """
        endpoint = "/api/v0/submit-atomic-transaction"
        url = f"{self.node_url}{endpoint}"

        payload = {
            "IncompleteAtomicTransactionHex": incomplete_atomic_txn_hex,
            "UnsignedInnerTransactionsHex": unsigned_inner_txn_hexes,
            "TransactionSignaturesHex": txn_signatures_hex
        }

        response = requests.post(url, json=payload)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            try:
                error_json = response.json()
            except ValueError:
                error_json = response.text
            raise requests.exceptions.HTTPError(
                f"Error status returned from {url}: {response.status_code}, {error_json}"
            )

        return response.json()

    def sign_and_submit_txn(self, resp):
        unsigned_txn_hex = resp.get('TransactionHex')
        if unsigned_txn_hex is None:
            raise ValueError("TransactionHex not found in response")
        if 'InnerTransactionHexes' in resp:
            unsigned_inner_txn_hexes = resp.get('InnerTransactionHexes')
            signature_hexes = []
            for unsigned_inner_txn_hex in unsigned_inner_txn_hexes:
                signature_hex = self.sign_single_txn(unsigned_inner_txn_hex)
                signature_hexes.append(signature_hex)
            return self.submit_atomic_txn(
                unsigned_txn_hex, unsigned_inner_txn_hexes, signature_hexes
            )
        signature_hex = self.sign_single_txn(unsigned_txn_hex)
        return self.submit_txn(unsigned_txn_hex, signature_hex)

    def create_unsigned_atomic_txn(self, unsigned_transaction_hexes: List[Dict[str, Any]]) -> Dict[str, Any]:
        """
        Creates an unsigned atomic transaction from a list of transactions.

        Args:
            unsigned_transaction_hexes (List[Dict[str, Any]]): A list of transactions represented as dictionaries.

        Returns:
            Dict[str, Any]: The parsed response containing the atomic transaction details.

        Raises:
            Exception: If the request fails or the response cannot be parsed.
        """
        route_path = "/api/v0/create-atomic-txns-wrapper"
        url = f"{self.node_url}{route_path}"

        payload = {
            "UnsignedTransactionHexes": unsigned_transaction_hexes
        }

        headers = {
            "Content-Type": "application/json"
        }

        response = requests.post(url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            try:
                error_json = response.json()
            except ValueError:
                error_json = response.text
            raise requests.exceptions.HTTPError(
                f"CreateUnsignedAtomicTxn: Error status returned from {url}: {response.status_code}, {error_json}"
            )

        try:
            response_data = response.json()
        except json.JSONDecodeError as e:
            raise Exception(f"CreateUnsignedAtomicTxn: Error parsing JSON response: {str(e)}")

        if "InnerTransactionHexes" not in response_data:
            raise Exception("CreateUnsignedAtomicTxn: Missing 'InnerTransactionHexes' in response")

        return response_data

    def get_transaction(self, txn_hash_hex: str, committed_txns_only: bool) -> Dict[str, Any]:
        """
        Fetch a transaction by its hash with an optional filter for committed transactions.

        Args:
            txn_hash_hex (str): The hex string of the transaction hash.
            committed_txns_only (bool): If True, fetch only committed transactions;
                                        otherwise, fetch transactions in mempool.

        Returns:
            Dict[str, Any]: The JSON response containing transaction details.

        Raises:
            requests.exceptions.RequestException: If the request fails.
            json.JSONDecodeError: If the response parsing fails.
            ValueError: If the server returns a non-200 status code.
        """
        url = f"{self.node_url}/api/v0/get-txn"

        # Determine the transaction status based on the argument
        txn_status = "Committed" if committed_txns_only else "InMempool"

        payload = {
            "TxnHashHex": txn_hash_hex,
            "TxnStatus": txn_status,
        }

        headers = {
            "Origin": self.node_url,
            "Content-Type": "application/json",
        }

        response = requests.post(url, json=payload, headers=headers)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = response.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")

        return response.json()

    def wait_for_commitment_with_timeout(self, txn_hash_hex: str, timeout_seconds: float) -> None:
        """
        Waits for a transaction to commit within a specified timeout period. DeSo txns commit
        within two blocks, with 1s block times, so within 3s. Note you don't necessarily need
        to wait for commitment. You can "fire and forget" your txns if best-effort is OK, or
        use get_transaction to check that it entered the mempool, which is sufficient for most
        use-cases (and mempool txns almost always commit within a few seconds).

        Args:
            txn_hash_hex (str): The transaction hash in hex format.
            timeout_seconds (float): The maximum time to wait for confirmation, in seconds.

        Raises:
            TimeoutError: If the transaction does not confirm within the timeout period.
            Exception: If there is an error fetching the transaction from the node.
        """
        start_time = time.time()

        while True:
            try:
                txn_response = self.get_transaction(txn_hash_hex, committed_txns_only=True)
                if txn_response.get("TxnFound", False):
                    return  # Transaction is confirmed
            except RequestException as e:
                raise Exception(f"Error getting txn from node: {str(e)}")

            if time.time() - start_time > timeout_seconds:
                raise TimeoutError(f"Timeout waiting for txn to confirm: {txn_hash_hex}")

            time.sleep(0.1)  # Sleep for 100 milliseconds before retrying

    def coins_to_base_units(self, coin_amount: float, is_deso: bool, hex_encode: bool = False) -> str:
        if is_deso:
            base_units = int(coin_amount * 1e9)
        else:
            base_units = int(coin_amount * 1e18)
        if hex_encode:
            return hex(base_units)
        return str(base_units)

    def base_units_to_coins(self, coin_base_units: str | int, is_deso: bool) -> float:
        # Decode hex if needed
        if str(coin_base_units).startswith("0x"):
            coin_base_units = int(coin_base_units, 16)
        if is_deso:
            return float(coin_base_units) / 1e9
        return float(coin_base_units) / 1e18

    def mint_or_burn_tokens(
        self,
        updater_pubkey_base58check: str,
        profile_pubkey_base58check: str,
        operation_type: str,            # 'mint' or 'burn'
        coins_to_mint_or_burn_nanos: str,
        min_fee_rate_nanos_per_kb: int = 1000,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.node_url}/api/v0/dao-coin"

        payload = {
            "UpdaterPublicKeyBase58Check": updater_pubkey_base58check,
            "ProfilePublicKeyBase58CheckOrUsername": profile_pubkey_base58check,
            "OperationType": operation_type,
        }

        if operation_type.lower() == "mint":
            payload["CoinsToMintNanos"] = coins_to_mint_or_burn_nanos
        elif operation_type.lower() == "burn":
            payload["CoinsToBurnNanos"] = coins_to_mint_or_burn_nanos
        else:
            raise ValueError('operation_type must be "mint" or "burn".')

        payload["MinFeeRateNanosPerKB"] = min_fee_rate_nanos_per_kb

        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        resp = requests.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = resp.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")

        return resp.json()

    def send_deso(
            self,
            sender_pubkey_base58check: str,
            recipient_pubkey_or_username: str,
            amount_nanos: int,
            min_fee_rate_nanos_per_kb: int = 1000,
            extra_headers: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        Sends DESO from one account to another.

        Args:
            sender_pubkey_base58check: Public key of the sender in Base58Check format.
            recipient_pubkey_or_username: Public key or username of the recipient.
            amount_nanos: Amount to send in nanos.
            min_fee_rate_nanos_per_kb: Minimum fee rate in nanos per KB.
            extra_headers: Optional headers to include in the request.

        Returns:
            dict: Parsed response from the API.
        """
        url = f"{self.node_url}/api/v0/send-deso"
        payload = {
            "SenderPublicKeyBase58Check": sender_pubkey_base58check,
            "RecipientPublicKeyOrUsername": recipient_pubkey_or_username,
            "AmountNanos": amount_nanos,
            "MinFeeRateNanosPerKB": min_fee_rate_nanos_per_kb
        }
        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        response = requests.post(url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = response.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")

        return response.json()

    def transfer_tokens(
        self,
        sender_pubkey_base58check: str,
        profile_pubkey_base58check: str,
        receiver_pubkey_base58check: str,
        token_to_transfer_base_units: str,
        min_fee_rate_nanos_per_kb: int = 1000,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.node_url}/api/v0/transfer-dao-coin"
        payload = {
            "SenderPublicKeyBase58Check": sender_pubkey_base58check,
            "ProfilePublicKeyBase58CheckOrUsername": profile_pubkey_base58check,
            "ReceiverPublicKeyBase58CheckOrUsername": receiver_pubkey_base58check,
            "DAOCoinToTransferNanos": token_to_transfer_base_units,
            "MinFeeRateNanosPerKB": min_fee_rate_nanos_per_kb,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        resp = requests.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = resp.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")

        return resp.json()

    def update_transfer_restriction_status(
        self,
        updater_pubkey_base58check: str,
        profile_pubkey_base58check: str,
        transfer_restriction_status: str,  # e.g. "profile_owner_only"
        min_fee_rate_nanos_per_kb: int = 1000,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.node_url}/api/v0/dao-coin"
        payload = {
            "TransferRestrictionStatus": transfer_restriction_status,
            "UpdaterPublicKeyBase58Check": updater_pubkey_base58check,
            "ProfilePublicKeyBase58CheckOrUsername": profile_pubkey_base58check,
            "OperationType": "update_transfer_restriction_status",
            "MinFeeRateNanosPerKB": min_fee_rate_nanos_per_kb,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        resp = requests.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = resp.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")
        return resp.json()

    def create_limit_order_with_fee(
        self,
        transactor_public_key: str,
        quote_currency_public_key: str,
        base_currency_public_key: str,
        operation_type: str,  # "BID" or "ASK"
        price: str,
        price_currency_type: str,
        quantity: str,
        fill_type: str,
        quantity_currency_type: str,
        min_fee_rate_nanos_per_kb: int = 0,
        extra_fees: Optional[List[Dict[str, Any]]] = None,
        optional_preceding_txs: Optional[List[Dict[str, Any]]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.node_url}/api/v0/create-dao-coin-limit-order-with-fee"
        payload = {
            "OperationType": operation_type,
            "TransactorPublicKeyBase58Check": transactor_public_key,
            "QuoteCurrencyPublicKeyBase58Check": quote_currency_public_key,
            "BaseCurrencyPublicKeyBase58Check": base_currency_public_key,
            "Price": price,
            "PriceCurrencyType": price_currency_type,
            "Quantity": quantity,
            "FillType": fill_type,
            "MinFeeRateNanosPerKB": min_fee_rate_nanos_per_kb,
            "TransactionFees": extra_fees,
            "OptionalPrecedingTransactions": optional_preceding_txs,
            "QuantityCurrencyType": quantity_currency_type,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)
        #print(payload)
        resp = requests.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = resp.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")
        return resp.json()

    def cancel_limit_order(
        self,
        transactor_public_key: str,
        cancel_order_id: str,
        min_fee_rate_nanos_per_kb: int = 1000,
        extra_fees: Optional[List[Dict[str, Any]]] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.node_url}/api/v0/cancel-dao-coin-limit-order"
        payload = {
            "TransactorPublicKeyBase58Check": transactor_public_key,
            "CancelOrderID": cancel_order_id,
            "MinFeeRateNanosPerKB": min_fee_rate_nanos_per_kb,
            "TransactionFees": extra_fees,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        resp = requests.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = resp.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")
        return resp.json()

    def get_token_balances(
            self,
            user_public_key: str,
            creator_public_keys: List[str],
            txn_status: str = "Committed",
            extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        """
        Fetches token balances for a given user public key and a list of creator public keys.

        Args:
            user_public_key (str): The base58 public key of the user.
            creator_public_keys (List[str]): List of creator public keys to query balances for.
            txn_status (str): The transaction status filter. Default is 'Committed'.
            extra_headers (Optional[Dict[str, str]]): Additional headers for the HTTP request.

        Returns:
            Dict[str, Any]: The token balances in a structured dictionary format.

        Raises:
            requests.exceptions.RequestException: If the request fails.
            json.JSONDecodeError: If the response is not valid JSON.
            ValueError: If the server returns a non-200 status code.
        """
        url = f"{self.node_url}/api/v0/get-token-balances-for-public-key"

        payload = {
            "UserPublicKey": user_public_key,
            "CreatorPublicKeys": creator_public_keys,
            "TxnStatus": txn_status,
        }

        headers = {
            "Content-Type": "application/json",
            "Origin": self.node_url,
        }
        if extra_headers:
            headers.update(extra_headers)

        response = requests.post(url, json=payload, headers=headers)
        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = response.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")

        return response.json()

    def get_single_profile(
            self,
            public_key_base58check: Optional[str] = None,
            username: Optional[str] = None,
            extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any] | None:
        """
        Fetches a single profile from the DeSo node.

        Args:
            public_key_base58check (str, optional): The public key of the user to fetch.
            username (str, optional): The username of the user to fetch.
            no_error_on_missing (bool): If true, suppresses errors when the profile is missing.
            extra_headers (dict, optional): Additional headers to include in the request.

        Returns:
            dict: The profile data from the node.

        Raises:
            requests.exceptions.RequestException: If the request fails.
            json.JSONDecodeError: If response parsing fails.
            ValueError: If the server returns a non-200 status code.
        """
        url = f"{self.node_url}/api/v0/get-single-profile"

        payload = {
            "PublicKeyBase58Check": public_key_base58check or "",
            "Username": username or "",
            "NoErrorOnMissing": False,
        }

        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        try:
            response = requests.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except requests.exceptions.HTTPError as err:
            # Handle 404 gracefully.
            # TODO: This is a hack but fine for now...
            if "404" in str(err):
                return None
            raise ValueError(f"get_single_profile: Error making request to node: {err}")

        try:
            response_data = response.json()
        except json.JSONDecodeError as err:
            raise ValueError(f"get_single_profile: Error unmarshalling response: {err}")

        return response_data.get("Profile")

    def get_limit_orders(
        self,
        coin1_creator_pubkey: str,
        coin2_creator_pubkey: str,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.node_url}/api/v0/get-dao-coin-limit-orders"
        payload = {
            "DAOCoin1CreatorPublicKeyBase58Check": coin1_creator_pubkey,
            "DAOCoin2CreatorPublicKeyBase58Check": coin2_creator_pubkey,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        resp = requests.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = resp.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")
        return resp.json()

    def get_transactor_limit_orders(
        self,
        transactor_pubkey_base58check: str,
        extra_headers: Optional[Dict[str, str]] = None,
    ) -> Dict[str, Any]:
        url = f"{self.node_url}/api/v0/get-transactor-dao-coin-limit-orders"
        payload = {
            "TransactorPublicKeyBase58Check": transactor_pubkey_base58check,
        }
        headers = {
            "Content-Type": "application/json",
        }
        if extra_headers:
            headers.update(extra_headers)

        resp = requests.post(url, json=payload, headers=headers)
        try:
            resp.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = resp.json()  # Get the error response JSON
            raise requests.exceptions.HTTPError(f"HTTP Error: {e}, Response: {error_json}")
        return resp.json()

    def submit_post(
            self,
            updater_public_key_base58check: str,
            body: str,
            parent_post_hash_hex: Optional[str] = None,
            reposted_post_hash_hex: Optional[str] = None,
            title: Optional[str] = "",
            image_urls: Optional[List[str]] = None,
            video_urls: Optional[List[str]] = None,
            post_extra_data: Optional[Dict[str, Any]] = None,
            min_fee_rate_nanos_per_kb: int = 1000,
            is_hidden: bool = False,
            in_tutorial: bool = False
    ) -> Dict[str, Any]:
        """
        Submit a post or repost to the DeSo blockchain.

        Args:
            updater_public_key_base58check: Public key of the updater.
            body: The content of the post.
            parent_post_hash_hex: The hash of the parent post for replies.
            reposted_post_hash_hex: The hash of the post being reposted.
            title: An optional title for the post.
            image_urls: Optional list of image URLs.
            video_urls: Optional list of video URLs.
            post_extra_data: Optional additional data for the post.
            min_fee_rate_nanos_per_kb: Minimum fee rate in nanos per KB.
            is_hidden: Boolean to indicate if the post is hidden.
            in_tutorial: Boolean to indicate if the post is part of a tutorial.

        Returns:
            Dict[str, Any]: Response from the DeSo node.

        Raises:
            ValueError: If the request fails.
        """
        url = f"{self.node_url}/api/v0/submit-post"
        payload = {
            "UpdaterPublicKeyBase58Check": updater_public_key_base58check,
            "PostHashHexToModify": "",
            "ParentStakeID": parent_post_hash_hex or "",
            "RepostedPostHashHex": reposted_post_hash_hex or "",
            "Title": title or "",
            "BodyObj": {
                "Body": body,
                "ImageURLs": image_urls or [],
                "VideoURLs": video_urls or [],
            },
            "PostExtraData": post_extra_data or {"Node": "1"},
            "Sub": "",
            "IsHidden": is_hidden,
            "MinFeeRateNanosPerKB": min_fee_rate_nanos_per_kb,
            "InTutorial": in_tutorial,
        }

        headers = {
            "Content-Type": "application/json",
        }

        response = requests.post(url, json=payload, headers=headers)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = response.json() if response.content else response.text
            raise ValueError(f"HTTP Error: {e}, Response: {error_json}")

        return response.json()

    def create_follow_transaction(
            self,
            follower_public_key_base58check: str,
            followed_public_key_base58check: str,
            is_unfollow: bool = False,
            min_fee_rate_nanos_per_kb: int = 1000,
    ) -> Dict[str, Any]:
        """
        Create a follow or unfollow transaction.

        Args:
            follower_public_key_base58check: Public key of the follower.
            followed_public_key_base58check: Public key of the followed user.
            is_unfollow: Whether to unfollow instead of follow.
            min_fee_rate_nanos_per_kb: Minimum fee rate in nanos per KB.

        Returns:
            Dict[str, Any]: Response from the DeSo node.

        Raises:
            ValueError: If the request fails.
        """
        url = f"{self.node_url}/api/v0/create-follow-txn-stateless"
        payload = {
            "FollowerPublicKeyBase58Check": follower_public_key_base58check,
            "FollowedPublicKeyBase58Check": followed_public_key_base58check,
            "IsUnfollow": is_unfollow,
            "MinFeeRateNanosPerKB": min_fee_rate_nanos_per_kb,
        }

        headers = {
            "Content-Type": "application/json",
        }

        response = requests.post(url, json=payload, headers=headers)

        try:
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            error_json = response.json() if response.content else response.text
            raise ValueError(f"HTTP Error: {e}, Response: {error_json}")

        return response.json()

class DeSoKeyPair:
    def __init__(self, public_key: bytes, private_key: bytes):
        self.public_key = public_key
        self.private_key = private_key

def create_key_pair_from_seed_or_seed_hex(
    seed: str,
    passphrase: str,
    index: int,
    is_testnet: bool
) -> Tuple[Optional[DeSoKeyPair], Optional[str]]:
    """
    Creates a key pair from either a seed phrase or seed hex.

    Args:
        seed (str): Either a BIP39 mnemonic seed phrase or a hex string
        passphrase (str): Optional passphrase for BIP39 seed
        index (int): Account index for derivation path
        is_testnet (bool): Whether to use testnet or mainnet parameters

    Returns:
        Tuple[DeSoKeyPair, Optional[str]]: Returns the key pair and any error message
    """
    if not seed:
        return None, "Seed must be provided"

    # First try to decode as hex to determine if it's a seed hex
    try:
        seed_bytes = binascii.unhexlify(seed.lower())
        # If we get here, it's a valid hex string
        if passphrase or index != 0:
            return None, "Seed hex provided, but passphrase or index params were also provided"

        # Convert the seed hex directly to keys
        privkey = PrivateKey(seed_bytes)
        pubkey = privkey.public_key
        return DeSoKeyPair(pubkey.format(), privkey.secret), None

    except binascii.Error:
        # Not a valid hex string, treat as mnemonic
        try:
            # Validate and convert mnemonic to seed
            mnemo = Mnemonic("english")
            if not mnemo.check(seed):
                return None, "Invalid mnemonic seed phrase"

            seed_bytes = mnemo.to_seed(seed, passphrase)

            # Initialize BIP32 with appropriate network
            network = "test" if is_testnet else "main"
            bip32 = BIP32.from_seed(seed_bytes, network=network)

            # Derive the key path: m/44'/0'/index'/0/0
            # Note: in BIP32, hardened keys are represented with index + 0x80000000
            path = f"m/44'/0'/{index}'/0/0"
            derived_key = bip32.get_privkey_from_path(path)

            # Convert to coincurve keys for consistent interface
            privkey = PrivateKey(derived_key)
            pubkey = privkey.public_key

            return DeSoKeyPair(pubkey.format(), privkey.secret), None

        except Exception as e:
            return None, f"Error converting seed to key pair: {str(e)}"

def base58_check_encode(input_bytes: bytes, is_testnet: bool) -> str:
     """
     Encode input bytes using Base58Check encoding with a specific prefix.

     Args:
         input_bytes: The bytes to encode
         prefix: 3-byte prefix to prepend

     Returns:
         Base58Check encoded string
     """
     prefix = b"\x11\xc2\x00" if is_testnet else  b"\xcd\x14\x00"

     # Combine prefix and input bytes
     combined = prefix + input_bytes

     # Calculate double SHA256 checksum
     first_hash = hashlib.sha256(combined).digest()
     second_hash = hashlib.sha256(first_hash).digest()
     checksum = second_hash[:4]

     final_bytes = combined + checksum

     # Encode using Base58
     return base58.b58encode(final_bytes).decode()
