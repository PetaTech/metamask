# Seed Brute Force Research Tool

⚠️ **SECURITY RESEARCH ONLY** ⚠️

This FastAPI application is designed for defensive security research purposes to test the feasibility of partial seed brute-force attacks on cryptocurrency wallets. This tool should ONLY be used for:

- Security research and education
- Testing your own wallets/seeds
- Understanding attack vectors for defensive purposes

## Features

- **Partial Brute Force Attack**: Fix 11 words of a seed phrase and iterate through possibilities for the remaining word
- **MongoDB Integration**: Store successful matches with seed phrase, address, and balance
- **RESTful API**: Easy-to-use endpoints for managing attacks and viewing results
- **Background Processing**: Attacks run asynchronously without blocking the API

## Setup

1. **Install Dependencies**:
   ```bash
   pip install -r requirements.txt
   ```

2. **Setup MongoDB**:
   - Install MongoDB locally or use MongoDB Atlas
   - Update connection string in `.env` file

3. **Create Environment File**:
   ```bash
   cp .env.example .env
   # Edit .env with your configuration
   ```

4. **Ensure wordlist.txt exists**:
   - The BIP39 English wordlist should be in the root directory

## API Endpoints

### Health Check
- `GET /health` - Check application and database status

### Attack Management
- `POST /attack/start` - Start a partial brute force attack
- `POST /attack/stop` - Stop the current attack
- `GET /attack/status` - Get current attack status

### Results
- `GET /matches` - Get all successful matches
- `GET /matches/{address}` - Get match by wallet address
- `GET /stats` - Get overall statistics

### Utilities
- `POST /utils/generate-seed` - Generate random seed for testing
- `POST /utils/seed-to-address` - Convert seed to Ethereum address

## Running the Application

```bash
python main.py
```

The API will be available at `http://localhost:8000`

API documentation: `http://localhost:8000/docs`

## Example Usage

### Start an Attack
```bash
curl -X POST "http://localhost:8000/attack/start" \
  -H "Content-Type: application/json" \
  -d '{
    "target_address": "0x742d35Cc6635C0532925a3b8D581d3E9f4f9Ffff",
    "max_cycles": 5,
    "max_attempts_per_cycle": 1000
  }'
```

### Check Status
```bash
curl "http://localhost:8000/attack/status"
```

### View Results
```bash
curl "http://localhost:8000/matches"
```

## Security Notes

- This tool demonstrates why partial seed exposure is dangerous
- In practice, brute forcing even one unknown word requires significant computational resources
- Full 12-word seeds are cryptographically secure when generated properly
- Never share partial seed phrases

## Disclaimer

This tool is for educational and defensive security research only. The authors are not responsible for any misuse of this software. Always comply with applicable laws and only test on systems you own or have explicit permission to test.