import asyncio
from typing import Optional, List, Dict, Any
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase, AsyncIOMotorCollection
import os
from datetime import datetime
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

class SeedMatch:
    """Simple data class for seed matches (replacing Pydantic)"""
    def __init__(self, seed_phrase: str, address: str, balance: float, timestamp: datetime, attempts_made: int):
        self.seed_phrase = seed_phrase
        self.address = address
        self.balance = balance
        self.timestamp = timestamp
        self.attempts_made = attempts_made

class DatabaseManager:
    def __init__(self, connection_string: str = None):
        self.connection_string = connection_string or os.getenv(
            "MONGODB_URL", 
            "mongodb://localhost:27017"
        )
        self.client: Optional[AsyncIOMotorClient] = None
        self.db: Optional[AsyncIOMotorDatabase] = None
        self.collection: Optional[AsyncIOMotorCollection] = None
        
    async def connect(self, database_name: str = "seed_bruteforce"):
        """Connect to MongoDB"""
        try:
            self.client = AsyncIOMotorClient(self.connection_string)
            self.db = self.client[database_name]
            
            # Separate collections for balanced vs zero balance addresses
            self.balanced_collection = self.db["balanced_addresses"]
            self.zero_balance_collection = self.db["zero_balance_addresses"]
            
            # Cycle statistics collection
            self.cycle_stats_collection = self.db["cycle_statistics"]
            
            # Legacy collection for backward compatibility
            self.collection = self.db["successful_matches"]
            
            # Test connection
            await self.client.admin.command('ping')
            print("Successfully connected to MongoDB")
            print("Collections: balanced_addresses, zero_balance_addresses")
            
        except Exception as e:
            print(f"Failed to connect to MongoDB: {e}")
            raise
    
    async def disconnect(self):
        """Disconnect from MongoDB"""
        if self.client:
            self.client.close()
            print("Disconnected from MongoDB")
    
    async def store_successful_match(self, seed_match: SeedMatch) -> str:
        """Store a successful seed match in appropriate collection based on balance"""
        if self.balanced_collection is None or self.zero_balance_collection is None:
            raise RuntimeError("Database not connected")
            
        document = {
            "seed_phrase": seed_match.seed_phrase,
            "address": seed_match.address,
            "balance": seed_match.balance,
            "timestamp": seed_match.timestamp,
            "attempts_made": seed_match.attempts_made
        }
        
        # Store in different collections based on balance
        if seed_match.balance > 0:
            result = await self.balanced_collection.insert_one(document)
            print(f"💰 Stored balanced address: {seed_match.address} (Balance: {seed_match.balance})")
        else:
            result = await self.zero_balance_collection.insert_one(document)
            
        return str(result.inserted_id)
    
    async def get_all_matches(self) -> List[Dict[str, Any]]:
        """Retrieve all successful matches from the database"""
        if self.collection is None:
            raise RuntimeError("Database not connected")
            
        matches = []
        async for document in self.collection.find():
            document["_id"] = str(document["_id"])
            matches.append(document)
        
        return matches
    
    async def get_match_by_address(self, address: str) -> Optional[Dict[str, Any]]:
        """Find a match by wallet address"""
        if self.collection is None:
            raise RuntimeError("Database not connected")
            
        document = await self.collection.find_one({"address": address})
        if document:
            document["_id"] = str(document["_id"])
        
        return document
    
    async def get_match_count(self) -> int:
        """Get total number of successful matches"""
        if self.collection is None:
            raise RuntimeError("Database not connected")
            
        return await self.collection.count_documents({})
    
    async def delete_match(self, match_id: str) -> bool:
        """Delete a match by ID"""
        if self.collection is None:
            raise RuntimeError("Database not connected")
            
        from bson import ObjectId
        result = await self.collection.delete_one({"_id": ObjectId(match_id)})
        return result.deleted_count > 0
    
    async def get_balanced_addresses(self) -> List[Dict[str, Any]]:
        """Get all addresses with balance > 0"""
        if self.balanced_collection is None:
            raise RuntimeError("Database not connected")
            
        matches = []
        async for document in self.balanced_collection.find().sort("balance", -1):  # Sort by balance descending
            document["_id"] = str(document["_id"])
            matches.append(document)
        
        return matches
    
    async def get_zero_balance_addresses(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get zero balance addresses (limited for performance)"""
        if self.zero_balance_collection is None:
            raise RuntimeError("Database not connected")
            
        matches = []
        async for document in self.zero_balance_collection.find().limit(limit).sort("timestamp", -1):
            document["_id"] = str(document["_id"])
            matches.append(document)
        
        return matches
    
    async def get_balance_statistics(self) -> Dict[str, Any]:
        """Get statistics about balanced vs zero balance addresses"""
        if self.balanced_collection is None or self.zero_balance_collection is None:
            raise RuntimeError("Database not connected")
        
        balanced_count = await self.balanced_collection.count_documents({})
        zero_balance_count = await self.zero_balance_collection.count_documents({})
        
        # Get highest balance found
        highest_balance_doc = await self.balanced_collection.find_one(
            sort=[("balance", -1)]
        )
        
        highest_balance = highest_balance_doc.get("balance", 0) if highest_balance_doc else 0
        
        return {
            "balanced_addresses": balanced_count,
            "zero_balance_addresses": zero_balance_count,
            "total_addresses": balanced_count + zero_balance_count,
            "highest_balance_found": highest_balance,
            "success_rate": f"{(balanced_count / (balanced_count + zero_balance_count) * 100):.4f}%" if (balanced_count + zero_balance_count) > 0 else "0%"
        }
    
    async def store_cycle_stats(self, cycle_data: Dict[str, Any]) -> str:
        """Store cycle completion statistics"""
        if self.cycle_stats_collection is None:
            raise RuntimeError("Database not connected")
            
        document = {
            "cycle_number": cycle_data.get("cycle_number"),
            "base_seed": cycle_data.get("base_seed"),
            "total_attempts": cycle_data.get("total_attempts"),
            "valid_seeds": cycle_data.get("valid_seeds"),
            "addresses_with_activity": cycle_data.get("addresses_with_activity"),
            "timestamp": cycle_data.get("timestamp"),
            "session_total_attempts": cycle_data.get("session_total_attempts")
        }
        
        result = await self.cycle_stats_collection.insert_one(document)
        return str(result.inserted_id)
    
    async def get_recent_cycles(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent cycle statistics"""
        if self.cycle_stats_collection is None:
            raise RuntimeError("Database not connected")
            
        cycles = []
        async for document in self.cycle_stats_collection.find().sort("timestamp", -1).limit(limit):
            document["_id"] = str(document["_id"])
            cycles.append(document)
        
        return cycles

# Global database instance
db_manager = DatabaseManager()