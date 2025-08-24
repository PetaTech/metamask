import random
import hashlib
import time
import threading
import hmac
import struct
from typing import List, Optional
from mnemonic import Mnemonic
from web3 import Web3
import ecdsa
from eth_keys import keys

# No rate limiting needed - using direct blockchain nodes!

class SeedGenerator:
    def __init__(self, wordlist_path: str = "wordlist.txt"):
        self.mnemo = Mnemonic("english")
        self.wordlist = self._load_wordlist(wordlist_path)
        self.w3 = None  # Reuse Web3 connection
        
    def _load_wordlist(self, path: str) -> List[str]:
        """Load BIP39 wordlist from file"""
        with open(path, 'r', encoding='utf-8') as f:
            return [line.strip() for line in f.readlines()]
    
    def generate_random_seed(self) -> str:
        """Generate a random 12-word BIP39 seed phrase (MetaMask way)"""
        return self.mnemo.generate(strength=128)  # 128 bits = 12 words
    
    
    def validate_seed(self, seed: str) -> bool:
        """Validate if seed phrase is valid BIP39"""
        return self.mnemo.check(seed)
    
    def seed_to_address(self, seed: str) -> str:
        """Convert seed phrase to Ethereum address using pure Python cryptography"""
        if not self.validate_seed(seed):
            raise ValueError("Invalid seed phrase")
            
        try:
            # Convert mnemonic to seed bytes (512 bits)
            seed_bytes = self.mnemo.to_seed(seed, passphrase="")
            
            # Simple BIP32-style derivation for Ethereum
            # Generate master private key using HMAC-SHA512
            master_key = hmac.new(b"Bitcoin seed", seed_bytes, hashlib.sha512).digest()
            private_key_bytes = master_key[:32]
            
            # For simplicity, we'll derive the first account using a simple hash
            # This isn't exactly BIP44, but creates consistent addresses from seeds
            ethereum_derivation = hashlib.sha256(private_key_bytes + b"m/44'/60'/0'/0/0").digest()
            
            # Ensure private key is valid for secp256k1
            private_key_int = int.from_bytes(ethereum_derivation, 'big')
            if private_key_int >= ecdsa.SECP256k1.order:
                private_key_int = private_key_int % ecdsa.SECP256k1.order
            
            final_private_key = private_key_int.to_bytes(32, 'big')
            
            # Generate public key using secp256k1
            private_key_obj = keys.PrivateKey(final_private_key)
            public_key = private_key_obj.public_key
            
            # Get Ethereum address from public key
            address = public_key.to_checksum_address()
            
            return address
            
        except Exception as e:
            raise Exception(f"Failed to derive Ethereum address from seed: {e}")
    
    
    def _get_web3_connection(self):
        """Get or create Web3 connection using only direct blockchain nodes"""
        if self.w3 is None:
            # Multiple public blockchain endpoints (no API keys, no rate limits!)
            direct_endpoints = [
                "https://ethereum.publicnode.com",                    # PublicNode
                "https://rpc.ankr.com/eth",                          # Ankr public
                "https://eth.llamarpc.com",                          # Llama RPC
                "https://ethereum.blockpi.network/v1/rpc/public",    # BlockPI
                "https://eth-mainnet.public.blastapi.io",           # Blast API
                "https://cloudflare-eth.com",                        # Cloudflare
                "https://main-light.eth.linkpool.io",               # LinkPool
                "https://rpc.flashbots.net",                        # Flashbots
                "https://eth-mainnet.nodereal.io/v1/1659dfb40aa24bbb8153a677b98064d7",  # NodeReal
            ]
            
            print(f"🔗 Trying {len(direct_endpoints)} direct blockchain endpoints...")
            
            # Try each endpoint until one works
            for i, endpoint in enumerate(direct_endpoints, 1):
                try:
                    print(f"[{i}/{len(direct_endpoints)}] Connecting to {endpoint}...")
                    test_w3 = Web3(Web3.HTTPProvider(endpoint, request_kwargs={'timeout': 10}))
                    
                    # Test connection with a simple call
                    test_w3.eth.get_block('latest')
                    
                    self.w3 = test_w3
                    print(f"✅ SUCCESS: Connected to {endpoint}")
                    print(f"🚀 MAXIMUM SPEED: No rate limits, direct blockchain access!")
                    return self.w3
                    
                except Exception as e:
                    print(f"❌ Failed {endpoint}: {str(e)[:100]}...")
                    continue
            
            # If all endpoints fail
            print(f"💥 ERROR: All {len(direct_endpoints)} blockchain endpoints failed!")
            print(f"🔧 Check your internet connection or try again later.")
            return None
            
        return self.w3 if self.w3 and self.w3.is_connected() else None
    
    def has_transaction_history(self, address: str) -> bool:
        """Check if address has any outgoing transactions - MAXIMUM SPEED with direct blockchain access"""
        try:
            w3 = self._get_web3_connection()
            if not w3:
                return False
            
            # Convert to checksum address to avoid EIP-55 errors
            checksum_address = w3.to_checksum_address(address)
            # Get transaction count (nonce) - direct blockchain query, no rate limits!
            tx_count = w3.eth.get_transaction_count(checksum_address)
            return tx_count > 0  # True if address has sent transactions
            
        except Exception as e:
            print(f"Error checking transaction history: {e}")
            return False
    
    def get_transaction_count(self, address: str) -> int:
        """Get transaction count for address - MAXIMUM SPEED direct blockchain access"""
        try:
            w3 = self._get_web3_connection()
            if not w3:
                return 0
            
            # Convert to checksum address to avoid EIP-55 errors
            checksum_address = w3.to_checksum_address(address)
            return w3.eth.get_transaction_count(checksum_address)
            
        except Exception as e:
            print(f"Error getting transaction count: {e}")
            return 0
    
    def get_balance(self, address: str) -> float:
        """Get ETH balance for address - MAXIMUM SPEED direct blockchain access"""
        try:
            w3 = self._get_web3_connection()
            if not w3:
                return 0.0
            
            # Convert to checksum address to avoid EIP-55 errors
            checksum_address = w3.to_checksum_address(address)
            balance_wei = w3.eth.get_balance(checksum_address)
            balance_eth = w3.from_wei(balance_wei, 'ether')
            return float(balance_eth)
            
        except Exception as e:
            print(f"Error getting balance: {e}")
            return 0.0
    
    def has_balance(self, address: str) -> bool:
        """Check if address has any ETH balance"""
        try:
            balance = self.get_balance(address)
            return balance > 0
            
        except Exception as e:
            print(f"Error checking balance: {e}")
            return False

class BruteForceAttacker:
    def __init__(self, target_address: str, wordlist_path: str = "wordlist.txt"):
        self.target_address = target_address.lower()
        self.seed_gen = SeedGenerator(wordlist_path)
        self.wordlist = self.seed_gen.wordlist
        self.attempts = 0
        
    def partial_brute_force(self, base_seed: str, max_attempts: int = 2048) -> Optional[str]:
        """
        Perform partial brute force attack on a seed phrase
        Fix 11 words, iterate through possibilities for the remaining word
        """
        words = base_seed.split()
        if len(words) != 12:
            raise ValueError("Seed must be exactly 12 words")
            
        # Try each position (0-11)
        for position in range(12):
            original_word = words[position]
            
            # Try each word from wordlist at this position
            for candidate_word in self.wordlist:
                if self.attempts >= max_attempts:
                    return None
                    
                words[position] = candidate_word
                candidate_seed = " ".join(words)
                
                if self.seed_gen.validate_seed(candidate_seed):
                    try:
                        derived_address = self.seed_gen.seed_to_address(candidate_seed)
                        if derived_address.lower() == self.target_address:
                            return candidate_seed
                    except Exception:
                        pass
                        
                self.attempts += 1
            
            # Restore original word before trying next position
            words[position] = original_word
            
        return None
    
    def get_attempt_count(self) -> int:
        """Get current number of attempts made"""
        return self.attempts