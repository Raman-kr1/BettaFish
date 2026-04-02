#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MindSpider - AI Crawler Project Main Program
Integrates BroadTopicExtraction and DeepSentimentCrawling core modules
"""

import os
import sys
import argparse
import difflib
import re
from datetime import date, datetime
from pathlib import Path
import subprocess
import asyncio
import pymysql
from pymysql.cursors import DictCursor
from sqlalchemy.ext.asyncio import create_async_engine, AsyncEngine
from sqlalchemy import inspect, text
from config import settings
from loguru import logger
from urllib.parse import quote_plus

# Add project root directory to path
project_root = Path(__file__).parent
sys.path.append(str(project_root))

try:
    import config
except ImportError:
    logger.error("Error: Unable to import config.py configuration file")
    logger.error("Please ensure config.py exists in the project root directory with database and API configuration")
    sys.exit(1)

class MindSpider:
    """MindSpider Main Program"""
    
    def __init__(self):
        """Initialize MindSpider"""
        self.project_root = project_root
        self.broad_topic_path = self.project_root / "BroadTopicExtraction"
        self.deep_sentiment_path = self.project_root / "DeepSentimentCrawling"
        self.schema_path = self.project_root / "schema"
        
        logger.info("MindSpider AI Crawler Project")
        logger.info(f"Project path: {self.project_root}")
    
    def check_config(self) -> bool:
        """Check basic configuration"""
        logger.info("Checking basic configuration...")
        
        # Check settings configuration items
        required_configs = [
            'DB_HOST', 'DB_PORT', 'DB_USER', 'DB_PASSWORD', 'DB_NAME', 'DB_CHARSET',
            'MINDSPIDER_API_KEY', 'MINDSPIDER_BASE_URL', 'MINDSPIDER_MODEL_NAME'
        ]
        
        missing_configs = []
        for config_name in required_configs:
            if not hasattr(settings, config_name) or not getattr(settings, config_name):
                missing_configs.append(config_name)
        
        if missing_configs:
            logger.error(f"Missing configuration: {', '.join(missing_configs)}")
            logger.error("Please check the environment variable configuration in the .env file")
            return False
        
        logger.info("Basic configuration check passed")
        return True
    
    def check_database_connection(self) -> bool:
        """Check database connection"""
        logger.info("Checking database connection...")
        
        def build_async_url() -> str:
            dialect = (settings.DB_DIALECT or "mysql").lower()
            if dialect in ("postgresql", "postgres"):
                return f"postgresql+asyncpg://{settings.DB_USER}:{quote_plus(settings.DB_PASSWORD)}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
            # Default to mysql async driver asyncmy
            return (
                f"mysql+asyncmy://{settings.DB_USER}:{quote_plus(settings.DB_PASSWORD)}"
                f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}?charset={settings.DB_CHARSET}"
            )

        async def _test_connection(db_url: str) -> None:
            engine: AsyncEngine = create_async_engine(db_url, pool_pre_ping=True)
            try:
                async with engine.connect() as conn:
                    await conn.execute(text("SELECT 1"))
            finally:
                await engine.dispose()

        try:
            db_url: str = build_async_url()
            asyncio.run(_test_connection(db_url))
            logger.info("Database connection is normal")
            return True
        except Exception as e:
            logger.exception(f"Database connection failed: {e}")
            return False
    
    def check_database_tables(self) -> bool:
        """Check if database tables exist"""
        logger.info("Checking database tables...")
        
        def build_async_url() -> str:
            dialect = (settings.DB_DIALECT or "mysql").lower()
            if dialect in ("postgresql", "postgres"):
                return f"postgresql+asyncpg://{settings.DB_USER}:{quote_plus(settings.DB_PASSWORD)}@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}"
            return (
                f"mysql+asyncmy://{settings.DB_USER}:{quote_plus(settings.DB_PASSWORD)}"
                f"@{settings.DB_HOST}:{settings.DB_PORT}/{settings.DB_NAME}?charset={settings.DB_CHARSET}"
            )

        async def _check_tables(db_url: str) -> list[str]:
            engine: AsyncEngine = create_async_engine(db_url, pool_pre_ping=True)
            try:
                async with engine.connect() as conn:
                    def _get_tables(sync_conn):
                        return inspect(sync_conn).get_table_names()
                    tables = await conn.run_sync(_get_tables)
                    return tables
            finally:
                await engine.dispose()

        try:
            db_url: str = build_async_url()
            existing_tables = asyncio.run(_check_tables(db_url))
            required_tables = ['daily_news', 'daily_topics']
            missing_tables = [t for t in required_tables if t not in existing_tables]
            if missing_tables:
                logger.error(f"Missing database tables: {', '.join(missing_tables)}")
                return False
            logger.info("Database tables check passed")
            return True
        except Exception as e:
            logger.exception(f"Failed to check database tables: {e}")
            return False
    
    def initialize_database(self) -> bool:
        """Initialize database"""
        logger.info("Initializing database...")
        
        try:
            # Run database initialization script
            init_script = self.schema_path / "init_database.py"
            if not init_script.exists():
                logger.error("Error: Database initialization script not found")
                return False
            
            result = subprocess.run(
                [sys.executable, str(init_script)],
                cwd=self.schema_path,
                capture_output=True,
                text=True
            )
            
            if result.returncode == 0:
                logger.info("Database initialization successful")
                return True
            else:
                logger.error(f"Database initialization failed: {result.stderr}")
                return False
                
        except Exception as e:
            logger.exception(f"Database initialization exception: {e}")
            return False
    
    def _ensure_database_ready(self) -> bool:
        """Ensure database tables are ready, auto-initialize if not exist"""
        if not self.check_database_connection():
            logger.error("Database connection failed, cannot continue")
            return False
        
        if not self.check_database_tables():
            logger.warning("Database tables do not exist, auto-initializing...")
            if not self.initialize_database():
                logger.error("Database auto-initialization failed")
                return False
            logger.info("Database tables auto-initialized successfully")
        
        return True

    def check_dependencies(self) -> bool:
        """Check dependency environment"""
        logger.info("Checking dependency environment...")
        
        # Check Python packages
        required_packages = ['pymysql', 'requests', 'playwright']
        missing_packages = []
        
        for package in required_packages:
            try:
                __import__(package)
            except ImportError:
                missing_packages.append(package)
        
        if missing_packages:
            logger.error(f"Missing Python packages: {', '.join(missing_packages)}")
            logger.info("Please run: pip install -r requirements.txt")
            return False
        
        # Check and install MediaCrawler dependencies
        mediacrawler_path = self.deep_sentiment_path / "MediaCrawler"
        if not mediacrawler_path.exists():
            logger.error("Error: MediaCrawler directory not found")
            return False
        
        # Auto-install MediaCrawler dependencies
        self._install_mediacrawler_dependencies()
        
        logger.info("Dependency environment check passed")
        return True
    
    def _install_mediacrawler_dependencies(self) -> bool:
        """Auto-install MediaCrawler submodule dependencies"""
        mediacrawler_req = self.deep_sentiment_path / "MediaCrawler" / "requirements.txt"
        
        if not mediacrawler_req.exists():
            logger.warning(f"MediaCrawler requirements.txt does not exist: {mediacrawler_req}")
            return False
        
        # Check if already installed (using marker file)
        marker_file = self.deep_sentiment_path / "MediaCrawler" / ".deps_installed"
        req_mtime = mediacrawler_req.stat().st_mtime
        
        if marker_file.exists():
            marker_mtime = marker_file.stat().st_mtime
            if marker_mtime >= req_mtime:
                logger.debug("MediaCrawler dependencies already installed, skipping")
                return True
        
        logger.info("Installing MediaCrawler dependencies...")
        install_commands = [
            [sys.executable, "-m", "pip", "install", "-r", str(mediacrawler_req), "-q"],
            ["uv", "pip", "install", "-r", str(mediacrawler_req), "-q"],
        ]
        try:
            for cmd in install_commands:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=300  # 5 minute timeout
                )
                if result.returncode == 0:
                    marker_file.touch()
                    logger.info(f"MediaCrawler dependencies installed successfully (via {cmd[0]})")
                    return True
                logger.debug(f"{cmd[0]} installation failed, trying next method: {result.stderr.strip()}")

            logger.error("MediaCrawler dependency installation failed: all installation methods unavailable")
            return False

        except subprocess.TimeoutExpired:
            logger.error("MediaCrawler dependency installation timed out")
            return False
        except Exception as e:
            logger.exception(f"MediaCrawler dependency installation exception: {e}")
            return False

    def run_broad_topic_extraction(self, extract_date: date = None, keywords_count: int = 100) -> bool:
        """Run BroadTopicExtraction module"""
        logger.info("Running BroadTopicExtraction module...")
        
        # Auto-check and initialize database tables
        if not self._ensure_database_ready():
            return False
        
        if not extract_date:
            extract_date = date.today()
        
        try:
            cmd = [
                sys.executable, "main.py",
                "--keywords", str(keywords_count)
            ]
            
            logger.info(f"Executing command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                cwd=self.broad_topic_path,
                timeout=1800  # 30 minute timeout
            )
            
            if result.returncode == 0:
                logger.info("BroadTopicExtraction module executed successfully")
                return True
            else:
                logger.error(f"BroadTopicExtraction module execution failed, return code: {result.returncode}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("BroadTopicExtraction module execution timed out")
            return False
        except Exception as e:
            logger.exception(f"BroadTopicExtraction module execution exception: {e}")
            return False
    
    def run_deep_sentiment_crawling(self, target_date: date = None, platforms: list = None,
                                   max_keywords: int = 50, max_notes: int = 50,
                                   test_mode: bool = False) -> bool:
        """Run DeepSentimentCrawling module"""
        logger.info("Running DeepSentimentCrawling module...")

        # Auto-check and initialize database tables
        if not self._ensure_database_ready():
            return False

        # Auto-install MediaCrawler dependencies
        self._install_mediacrawler_dependencies()
        
        if not target_date:
            target_date = date.today()
        
        try:
            cmd = [sys.executable, "main.py"]
            
            if target_date:
                cmd.extend(["--date", target_date.strftime("%Y-%m-%d")])
            
            if platforms:
                cmd.extend(["--platforms"] + platforms)
            
            cmd.extend([
                "--max-keywords", str(max_keywords),
                "--max-notes", str(max_notes)
            ])
            
            if test_mode:
                cmd.append("--test")
            
            logger.info(f"Executing command: {' '.join(cmd)}")
            
            result = subprocess.run(
                cmd,
                cwd=self.deep_sentiment_path,
                timeout=3600  # 60 minute timeout
            )
            
            if result.returncode == 0:
                logger.info("DeepSentimentCrawling module executed successfully")
                return True
            else:
                logger.error(f"DeepSentimentCrawling module execution failed, return code: {result.returncode}")
                return False
                
        except subprocess.TimeoutExpired:
            logger.error("DeepSentimentCrawling module execution timed out")
            return False
        except Exception as e:
            logger.exception(f"DeepSentimentCrawling module execution exception: {e}")
            return False
    
    def run_complete_workflow(self, target_date: date = None, platforms: list = None,
                             keywords_count: int = 100, max_keywords: int = 50,
                             max_notes: int = 50, test_mode: bool = False) -> bool:
        """Run complete workflow"""
        logger.info("Starting complete MindSpider workflow")
        
        # Auto-check and initialize database tables (ensure auto-initialization when called independently)
        if not self._ensure_database_ready():
            return False
        
        if not target_date:
            target_date = date.today()
        
        logger.info(f"Target date: {target_date}")
        logger.info(f"Platform list: {platforms if platforms else 'All supported platforms'}")
        logger.info(f"Test mode: {'Yes' if test_mode else 'No'}")
        
        # Step 1: Run topic extraction
        logger.info("=== Step 1: Topic Extraction ===")
        if not self.run_broad_topic_extraction(target_date, keywords_count):
            logger.error("Topic extraction failed, terminating workflow")
            return False
        
        # Step 2: Run sentiment crawling
        logger.info("=== Step 2: Sentiment Crawling ===")
        if not self.run_deep_sentiment_crawling(target_date, platforms, max_keywords, max_notes, test_mode):
            logger.error("Sentiment crawling failed, but topic extraction completed")
            return False
        
        logger.info("Complete workflow executed successfully!")
        return True
    
    def show_status(self):
        """Show project status"""
        logger.info("MindSpider Project Status:")
        logger.info(f"Project path: {self.project_root}")
        
        # Configuration status
        config_ok = self.check_config()
        logger.info(f"Configuration status: {'Normal' if config_ok else 'Abnormal'}")
        
        # Database status
        if config_ok:
            db_conn_ok = self.check_database_connection()
            logger.info(f"Database connection: {'Normal' if db_conn_ok else 'Abnormal'}")
            
            if db_conn_ok:
                db_tables_ok = self.check_database_tables()
                logger.info(f"Database tables: {'Normal' if db_tables_ok else 'Need initialization'}")
        
        # Dependency status
        deps_ok = self.check_dependencies()
        logger.info(f"Dependency environment: {'Normal' if deps_ok else 'Abnormal'}")
        
        # Module status
        broad_topic_exists = self.broad_topic_path.exists()
        deep_sentiment_exists = self.deep_sentiment_path.exists()
        logger.info(f"BroadTopicExtraction module: {'Exists' if broad_topic_exists else 'Missing'}")
        logger.info(f"DeepSentimentCrawling module: {'Exists' if deep_sentiment_exists else 'Missing'}")
    
    def setup_project(self) -> bool:
        """Project initialization setup"""
        logger.info("Starting MindSpider project initialization...")
        
        # 1. Check configuration
        if not self.check_config():
            return False
        
        # 2. Check dependencies
        if not self.check_dependencies():
            return False
        
        # 3. Check database connection
        if not self.check_database_connection():
            return False
        
        # 4. Check and initialize database tables
        if not self.check_database_tables():
            logger.info("Need to initialize database tables...")
            if not self.initialize_database():
                return False
        
        logger.info("MindSpider project initialization complete!")
        return True

PLATFORM_CHOICES = ['xhs', 'dy', 'ks', 'bili', 'wb', 'tieba', 'zhihu']

PLATFORM_ALIASES = {
    'weibo': 'wb', 'webo': 'wb', 'weibo': 'wb',
    'douyin': 'dy', 'tiktok': 'dy',
    'kuaishou': 'ks', 'kuaishou': 'ks',
    'bilibili': 'bili', 'bstation': 'bili', 'bstation': 'bili',
    'xiaohongshu': 'xhs', 'redbook': 'xhs', 'redbook': 'xhs',
    'zhihu': 'zhihu', 'zhihu': 'zhihu',
    'tieba': 'tieba', 'baidutieba': 'tieba',
}

class SuggestiveArgumentParser(argparse.ArgumentParser):
    """Provides similar candidate suggestions on argument errors"""

    def error(self, message: str):
        match = re.search(r"invalid choice: '([^']+)'", message)
        if match:
            bad = match.group(1)
            alias = PLATFORM_ALIASES.get(bad.lower())
            suggestions = difflib.get_close_matches(bad, PLATFORM_CHOICES, n=3, cutoff=0.3)
            if alias:
                print(f"Error: '{bad}' is not a valid platform code. Did you mean '{alias}'?", file=sys.stderr)
            elif suggestions:
                print(f"Error: '{bad}' is not a valid platform code. Closest options: {suggestions}", file=sys.stderr)
            else:
                print(f"Error: '{bad}' is not a valid platform code. Valid platforms: {PLATFORM_CHOICES}", file=sys.stderr)
            print(f"Full error: {message}", file=sys.stderr)
        else:
            print(f"Error: {message}", file=sys.stderr)
        self.print_usage(sys.stderr)
        sys.exit(2)

def main():
    """Command line entry"""
    parser = SuggestiveArgumentParser(description="MindSpider - AI Crawler Project Main Program")
    
    # Basic operations
    parser.add_argument("--setup", action="store_true", help="Initialize project setup")
    parser.add_argument("--status", action="store_true", help="Show project status")
    parser.add_argument("--init-db", action="store_true", help="Initialize database")
    
    # Module execution
    parser.add_argument("--broad-topic", action="store_true", help="Run topic extraction module only")
    parser.add_argument("--deep-sentiment", action="store_true", help="Run sentiment crawling module only")
    parser.add_argument("--complete", action="store_true", help="Run complete workflow")
    
    # Parameter configuration
    parser.add_argument("--date", type=str, help="Target date (YYYY-MM-DD), defaults to today")
    parser.add_argument("--platforms", type=str, nargs='+',
                       choices=PLATFORM_CHOICES,
                       help="Specify crawling platforms")
    parser.add_argument("--keywords-count", type=int, default=100, help="Number of keywords for topic extraction")
    parser.add_argument("--max-keywords", type=int, default=50, help="Maximum keywords per platform")
    parser.add_argument("--max-notes", type=int, default=50, help="Maximum content per keyword")
    parser.add_argument("--test", action="store_true", help="Test mode (small data volume)")
    
    args = parser.parse_args()
    
    # Parse date
    target_date = None
    if args.date:
        try:
            target_date = datetime.strptime(args.date, "%Y-%m-%d").date()
        except ValueError:
            logger.error("Error: Incorrect date format, please use YYYY-MM-DD format")
            return
    
    # Create MindSpider instance
    spider = MindSpider()
    
    try:
        # Show status
        if args.status:
            spider.show_status()
            return
        
        # Project setup
        if args.setup:
            if spider.setup_project():
                logger.info("Project setup complete, you can start using MindSpider!")
            else:
                logger.error("Project setup failed, please check configuration and environment")
            return
        
        # Initialize database
        if args.init_db:
            if spider.initialize_database():
                logger.info("Database initialization successful")
            else:
                logger.error("Database initialization failed")
            return
        
        # Run modules
        if args.broad_topic:
            spider.run_broad_topic_extraction(target_date, args.keywords_count)
        elif args.deep_sentiment:
            spider.run_deep_sentiment_crawling(
                target_date, args.platforms, args.max_keywords, args.max_notes, args.test
            )
        elif args.complete:
            spider.run_complete_workflow(
                target_date, args.platforms, args.keywords_count, 
                args.max_keywords, args.max_notes, args.test
            )
        else:
            # Default to running complete workflow
            logger.info("Running complete MindSpider workflow...")
            spider.run_complete_workflow(
                target_date, args.platforms, args.keywords_count,
                args.max_keywords, args.max_notes, args.test
            )
    
    except KeyboardInterrupt:
        logger.info("User interrupted operation")
    except Exception as e:
        logger.exception(f"Execution error: {e}")

if __name__ == "__main__":
    main()
