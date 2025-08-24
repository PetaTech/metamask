#!/usr/bin/env python3
"""
Simple test script for the Seed Brute Force Research Tool
"""

import asyncio
import sys
from seed_utils import SeedGenerator, BruteForceAttacker

async def test_seed_generation():
    """Test basic seed generation and validation"""
    print("Testing seed generation...")
    
    try:
        seed_gen = SeedGenerator()
        
        # Generate a random seed
        seed = seed_gen.generate_random_seed()
        print(f"Generated seed: {seed}")
        
        # Validate the seed
        is_valid = seed_gen.validate_seed(seed)
        print(f"Seed is valid: {is_valid}")
        
        # Convert to address
        address = seed_gen.seed_to_address(seed)
        print(f"Derived address: {address}")
        
        return seed, address
        
    except Exception as e:
        print(f"Error in seed generation test: {e}")
        return None, None

async def test_partial_brute_force():
    """Test partial brute force functionality with a known seed"""
    print("\nTesting partial brute force attack...")
    
    try:
        seed_gen = SeedGenerator()
        
        # Generate a test seed and address
        original_seed = seed_gen.generate_random_seed()
        target_address = seed_gen.seed_to_address(original_seed)
        
        print(f"Original seed: {original_seed}")
        print(f"Target address: {target_address}")
        
        # Create a modified seed (change one word to create the attack scenario)
        words = original_seed.split()
        words[0] = "abandon"  # Replace first word with a different one
        modified_seed = " ".join(words)
        
        print(f"Modified seed (for attack): {modified_seed}")
        
        # Create brute force attacker
        attacker = BruteForceAttacker(target_address)
        
        # Attempt to find the original seed (with limited attempts for testing)
        print("Starting partial brute force attack (limited to 50 attempts for testing)...")
        found_seed = attacker.partial_brute_force(modified_seed, max_attempts=50)
        
        print(f"Attempts made: {attacker.get_attempt_count()}")
        
        if found_seed:
            print(f"SUCCESS: Found seed: {found_seed}")
            found_address = seed_gen.seed_to_address(found_seed)
            print(f"Address matches: {found_address.lower() == target_address.lower()}")
        else:
            print("No matching seed found within attempt limit")
            
    except Exception as e:
        print(f"Error in brute force test: {e}")

async def test_database_connection():
    """Test database connectivity"""
    print("\nTesting database connection...")
    
    try:
        from database import db_manager
        
        await db_manager.connect("test_db")
        print("Successfully connected to database")
        
        # Test basic operations
        count = await db_manager.get_match_count()
        print(f"Current match count: {count}")
        
        await db_manager.disconnect()
        print("Successfully disconnected from database")
        
    except Exception as e:
        print(f"Database test failed: {e}")
        print("Make sure MongoDB is running and accessible")

async def main():
    """Run all tests"""
    print("=== Seed Brute Force Research Tool - Test Suite ===\n")
    
    # Check if wordlist exists
    try:
        with open("wordlist.txt", 'r') as f:
            line_count = sum(1 for _ in f)
            print(f"Wordlist found with {line_count} words")
    except FileNotFoundError:
        print("ERROR: wordlist.txt not found!")
        print("Please ensure the BIP39 wordlist is available as 'wordlist.txt'")
        return
    
    # Run tests
    await test_seed_generation()
    await test_partial_brute_force()
    await test_database_connection()
    
    print("\n=== Test Suite Complete ===")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nTest interrupted by user")
    except Exception as e:
        print(f"Test suite failed: {e}")
        sys.exit(1)