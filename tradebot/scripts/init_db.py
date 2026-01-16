"""
Initialize database schema
"""
import sys
from pathlib import Path

# Add parent directory to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from bot.db import Database
from bot.config import DB_PATH
import logging

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def main():
    """Initialize database"""
    logger.info("Initializing database...")
    logger.info(f"Database path: {DB_PATH}")
    
    db = Database()
    db.create_tables()
    db.close()
    
    logger.info("Database initialized successfully!")
    logger.info(f"You can now start collecting data. Database file: {DB_PATH}")


if __name__ == "__main__":
    main()

