import sqlite3
import pandas as pd
from utils import *
import os
import warnings
import logging
import time
import threading
from functools import wraps
from contextlib import contextmanager
from typing import Optional, List, Dict, Any, Tuple

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Suppress pandas warning about non-SQLAlchemy connections (psycopg2 works fine)
warnings.filterwarnings('ignore', message='.*pandas only supports SQLAlchemy.*')

# Try to import PostgreSQL adapter
try:
    import psycopg2
    import psycopg2.pool
    from psycopg2 import OperationalError, InterfaceError, DatabaseError
    from psycopg2.extras import RealDictCursor
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    logger.warning("⚠️ psycopg2 not available - PostgreSQL support disabled")


# Custom Exceptions
class DatabaseConnectionError(Exception):
    """Raised when database connection fails"""
    pass

class DatabaseOperationError(Exception):
    """Raised when a database operation fails"""
    pass

class DatabaseTimeoutError(Exception):
    """Raised when a database operation times out"""
    pass

class PaginationError(Exception):
    """Raised when pagination parameters are invalid"""
    pass


# Retry decorator with exponential backoff
def retry_on_db_error(max_retries=3, base_delay=1, max_delay=10):
    """
    Decorator to retry database operations on transient errors
    Args:
        max_retries: Maximum number of retry attempts
        base_delay: Initial delay between retries in seconds
        max_delay: Maximum delay between retries in seconds
    """
    def decorator(func):
        @wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries):
                try:
                    return func(*args, **kwargs)
                except (OperationalError, InterfaceError) as e:
                    last_exception = e
                    if attempt < max_retries - 1:
                        delay = min(base_delay * (2 ** attempt), max_delay)
                        logger.warning(
                            f"Database operation failed (attempt {attempt + 1}/{max_retries}): {e}. "
                            f"Retrying in {delay}s..."
                        )
                        time.sleep(delay)
                    else:
                        logger.error(f"Database operation failed after {max_retries} attempts: {e}")
                except Exception as e:
                    # Don't retry on non-transient errors
                    logger.error(f"Non-retryable database error: {e}")
                    raise DatabaseOperationError(f"Database operation failed: {e}") from e

            raise DatabaseConnectionError(
                f"Failed to connect to database after {max_retries} attempts"
            ) from last_exception
        return wrapper
    return decorator

class MySqlite3Manager:
    # Configuration constants
    DB_TIMEOUT = 30  # seconds
    CONNECTION_POOL_MIN = 1
    CONNECTION_POOL_MAX = 10
    QUERY_TIMEOUT = 30  # seconds
    DEFAULT_PAGE_SIZE = 50
    MAX_PAGE_SIZE = 1000

    def __init__(self):
        # HYBRID SETUP:
        # - credentials table: Always in SQLite (local)
        # - fr_registrations table: PostgreSQL if DATABASE_URL set, otherwise SQLite

        # SQLite setup (always used for credentials table)
        self.dbname = "system/Attendance.db"
        logger.info(f"🔌 credentials table: Using SQLite ({self.dbname})")

        # PostgreSQL setup (for fr_registrations table)
        # Use DEV_DATABASE_URL in development, DATABASE_URL in production
        self.database_url = os.getenv('DEV_DATABASE_URL') or os.getenv('DATABASE_URL')
        self.use_postgres_for_registrations = bool(self.database_url and POSTGRES_AVAILABLE)

        if self.use_postgres_for_registrations:
            db_env = "DEV_DATABASE_URL" if os.getenv('DEV_DATABASE_URL') else "DATABASE_URL"
            logger.info(f"🔌 fr_registrations table: Using PostgreSQL from {db_env}")
            # Initialize connection pool for PostgreSQL with timeout and health checks
            try:
                self.registrations_pool = psycopg2.pool.ThreadedConnectionPool(
                    self.CONNECTION_POOL_MIN,
                    self.CONNECTION_POOL_MAX,
                    self.database_url,
                    connect_timeout=self.DB_TIMEOUT,
                    options=f'-c statement_timeout={self.QUERY_TIMEOUT * 1000}'  # milliseconds
                )
                if self.registrations_pool:
                    # Test connection health
                    test_conn = self.registrations_pool.getconn()
                    try:
                        with test_conn.cursor() as cur:
                            cur.execute('SELECT 1')
                        logger.info("✅ PostgreSQL connection pool created and validated for fr_registrations table")
                    finally:
                        self.registrations_pool.putconn(test_conn)
            except Exception as e:
                logger.error(f"❌ Failed to create PostgreSQL connection pool: {e}")
                logger.warning("⚠️ Falling back to SQLite for fr_registrations table")
                self.use_postgres_for_registrations = False
                self.registrations_pool = None
        else:
            logger.info(f"🔌 fr_registrations table: Using SQLite ({self.dbname})")
            self.registrations_pool = None

        # In-memory cache for person data (critical for fast recognition lookups)
        self._person_cache: Dict[str, Dict[str, Any]] = {}
        self._cache_timestamps: Dict[str, float] = {}  # Track when each entry was cached
        self._cache_lock = threading.Lock()
        self._cache_enabled = True
        self._cache_ttl = 3600  # Cache TTL in seconds (1 hour default)
        self._cache_hits = 0
        self._cache_misses = 0

        # Background thread for periodic cache cleanup
        self._cleanup_thread = None
        self._cleanup_interval = 300  # Clean up every 5 minutes
        self._cleanup_running = False

        self.create_database()
        self.create_table_credentials()
        self.create_table_registrations()
        self.insert_default_credentials()

        # Initialize cache with all person data
        self._warm_cache()

    @property
    def credentials_placeholder(self):
        """Return SQL placeholder for credentials table (always SQLite = ?)"""
        return '?'

    @property
    def registrations_placeholder(self):
        """Return SQL placeholder for fr_registrations table (PostgreSQL = %s, SQLite = ?)"""
        return '%s' if self.use_postgres_for_registrations else '?'

    # Context Managers for automatic resource cleanup
    @contextmanager
    def get_credentials_connection(self):
        """Context manager for credentials table (SQLite) connections"""
        con = None
        cursor = None
        try:
            con = sqlite3.connect(self.dbname, timeout=self.DB_TIMEOUT)
            cursor = con.cursor()
            yield con, cursor
            con.commit()
        except sqlite3.Error as e:
            if con:
                con.rollback()
            logger.error(f"SQLite credentials operation error: {e}")
            raise DatabaseOperationError(f"Credentials database error: {e}") from e
        finally:
            if cursor:
                cursor.close()
            if con:
                con.close()

    @contextmanager
    def get_registrations_connection(self):
        """Context manager for fr_registrations table connections with validation and automatic cleanup"""
        con = None
        cursor = None

        try:
            if self.use_postgres_for_registrations:
                # Get connection from PostgreSQL pool with validation
                con = self.registrations_pool.getconn()

                # Validate connection is alive - if stale, get a new one
                try:
                    with con.cursor() as test_cursor:
                        test_cursor.execute('SELECT 1')
                except (OperationalError, InterfaceError):
                    logger.warning("Stale PostgreSQL connection detected, getting new connection")
                    self.registrations_pool.putconn(con, close=True)
                    con = self.registrations_pool.getconn()

                cursor = con.cursor()
            else:
                # Use SQLite
                con = sqlite3.connect(self.dbname, timeout=self.DB_TIMEOUT)
                cursor = con.cursor()

            yield con, cursor
            con.commit()

        except Exception as e:
            if con:
                try:
                    con.rollback()
                except:
                    pass

            if self.use_postgres_for_registrations and isinstance(e, (OperationalError, InterfaceError, DatabaseError)):
                logger.error(f"PostgreSQL registrations operation error: {e}")
                raise  # Re-raise to allow retry decorator on calling methods
            else:
                logger.error(f"Database registrations operation error: {e}")
                raise DatabaseOperationError(f"Registrations database error: {e}") from e

        finally:
            if cursor:
                try:
                    cursor.close()
                except:
                    pass
            if con:
                if self.use_postgres_for_registrations and self.registrations_pool:
                    try:
                        self.registrations_pool.putconn(con)
                    except:
                        pass
                elif not self.use_postgres_for_registrations:
                    try:
                        con.close()
                    except:
                        pass

    # Legacy connection methods (kept for backward compatibility)
    def connect_credentials(self):
        """Connect to SQLite for credentials table operations"""
        self.con = sqlite3.connect(self.dbname)
        self.cursor = self.con.cursor()

    def connect_registrations(self):
        """Connect to appropriate database for fr_registrations table operations"""
        if self.use_postgres_for_registrations:
            # Get connection from PostgreSQL pool
            self.con = self.registrations_pool.getconn()
            self.cursor = self.con.cursor()
        else:
            # Use SQLite
            self.con = sqlite3.connect(self.dbname)
            self.cursor = self.con.cursor()

    def close_credentials(self):
        """Close credentials table connection (SQLite)"""
        if hasattr(self, 'con') and self.con:
            self.con.close()

    def close_registrations(self):
        """Close fr_registrations table connection and return to pool if PostgreSQL"""
        if hasattr(self, 'con') and self.con:
            if self.use_postgres_for_registrations and self.registrations_pool:
                # Return connection to pool
                self.registrations_pool.putconn(self.con)
            else:
                # Close SQLite connection
                self.con.close()

    # Helper methods
    def _validate_pagination(self, page: int, page_size: int) -> Tuple[int, int]:
        """Validate and normalize pagination parameters"""
        if page < 1:
            raise PaginationError("Page number must be >= 1")
        if page_size < 1:
            raise PaginationError("Page size must be >= 1")
        if page_size > self.MAX_PAGE_SIZE:
            logger.warning(f"Page size {page_size} exceeds maximum {self.MAX_PAGE_SIZE}, using maximum")
            page_size = self.MAX_PAGE_SIZE
        return page, page_size

    def _calculate_offset(self, page: int, page_size: int) -> int:
        """Calculate SQL OFFSET from page number and size"""
        return (page - 1) * page_size

    # Cache management methods
    def _warm_cache(self):
        """Load all person data into cache on startup for instant lookups"""
        try:
            with self.get_registrations_connection() as (con, cursor):
                cursor.execute("SELECT id, name, title, registration_id FROM fr_registrations")
                rows = cursor.fetchall()

                current_time = time.time()
                with self._cache_lock:
                    self._person_cache.clear()
                    self._cache_timestamps.clear()
                    for row in rows:
                        person_id, name, title, registration_id = row
                        self._person_cache[person_id] = {
                            'name': name if name else '',
                            'title': title if title else '',  # Handle NULL values from migration
                            'registration_id': registration_id if registration_id else ''
                        }
                        self._cache_timestamps[person_id] = current_time

                logger.info(f"🔥 Cache warmed: {len(self._person_cache)} person records loaded into memory")

                # Start background cleanup thread
                self._start_cleanup_thread()

        except Exception as e:
            logger.error(f"Failed to warm cache: {e}")
            logger.warning("⚠️ Cache warming failed - will use database queries instead")
            # Continue without cache - will fall back to DB queries

    def _start_cleanup_thread(self):
        """Start background thread for periodic cache cleanup"""
        if self._cleanup_thread is None or not self._cleanup_thread.is_alive():
            self._cleanup_running = True
            self._cleanup_thread = threading.Thread(
                target=self._cleanup_loop,
                daemon=True,  # Daemon thread will exit when main program exits
                name="CacheCleanup"
            )
            self._cleanup_thread.start()
            logger.info(f"🧹 Cache cleanup thread started (TTL: {self._cache_ttl}s, interval: {self._cleanup_interval}s)")

    def _cleanup_loop(self):
        """Background loop to periodically clean expired cache entries"""
        while self._cleanup_running:
            try:
                time.sleep(self._cleanup_interval)
                self._cleanup_expired_entries()
            except Exception as e:
                logger.error(f"Error in cache cleanup thread: {e}")

    def _cleanup_expired_entries(self):
        """Remove expired entries from cache based on TTL"""
        current_time = time.time()
        expired_keys = []

        with self._cache_lock:
            for person_id, timestamp in self._cache_timestamps.items():
                if current_time - timestamp > self._cache_ttl:
                    expired_keys.append(person_id)

            # Remove expired entries
            for person_id in expired_keys:
                del self._person_cache[person_id]
                del self._cache_timestamps[person_id]

        if expired_keys:
            logger.info(f"🧹 Cache cleanup: removed {len(expired_keys)} expired entries (TTL: {self._cache_ttl}s)")

    def _is_cache_entry_valid(self, person_id: str) -> bool:
        """Check if a cache entry is still valid (not expired)"""
        if person_id not in self._cache_timestamps:
            return False
        current_time = time.time()
        return (current_time - self._cache_timestamps[person_id]) <= self._cache_ttl

    def _invalidate_cache_entry(self, person_id: str):
        """Remove a specific person from cache"""
        with self._cache_lock:
            if person_id in self._person_cache:
                del self._person_cache[person_id]
                if person_id in self._cache_timestamps:
                    del self._cache_timestamps[person_id]
                logger.debug(f"Cache invalidated for person: {person_id}")

    def _update_cache_entry(self, person_id: str, name: str, title: str, registration_id: str):
        """Update or add a person to cache with current timestamp"""
        with self._cache_lock:
            self._person_cache[person_id] = {
                'name': name,
                'title': title,
                'registration_id': registration_id
            }
            self._cache_timestamps[person_id] = time.time()
            logger.debug(f"Cache updated for person: {person_id}")

    def _clear_cache(self):
        """Clear entire cache"""
        with self._cache_lock:
            self._person_cache.clear()
            self._cache_timestamps.clear()
            self._cache_hits = 0
            self._cache_misses = 0
            logger.info("Cache cleared")

    def get_cache_stats(self) -> Dict[str, Any]:
        """Get cache statistics including TTL and expiration info"""
        with self._cache_lock:
            total = self._cache_hits + self._cache_misses
            hit_rate = (self._cache_hits / total * 100) if total > 0 else 0

            # Calculate age statistics
            current_time = time.time()
            ages = [current_time - ts for ts in self._cache_timestamps.values()]
            avg_age = sum(ages) / len(ages) if ages else 0
            oldest_age = max(ages) if ages else 0

            return {
                'enabled': self._cache_enabled,
                'size': len(self._person_cache),
                'hits': self._cache_hits,
                'misses': self._cache_misses,
                'hit_rate': round(hit_rate, 2),
                'total_requests': total,
                'ttl_seconds': self._cache_ttl,
                'cleanup_interval_seconds': self._cleanup_interval,
                'avg_entry_age_seconds': round(avg_age, 2),
                'oldest_entry_age_seconds': round(oldest_age, 2),
                'cleanup_thread_running': self._cleanup_running
            }

    def configure_cache(self, ttl: int = None, cleanup_interval: int = None, enabled: bool = None):
        """
        Configure cache settings
        Args:
            ttl: Cache TTL in seconds (None to keep current)
            cleanup_interval: Cleanup interval in seconds (None to keep current)
            enabled: Enable/disable cache (None to keep current)
        """
        if ttl is not None:
            self._cache_ttl = max(60, ttl)  # Minimum 1 minute
            logger.info(f"Cache TTL updated to {self._cache_ttl}s")

        if cleanup_interval is not None:
            self._cleanup_interval = max(30, cleanup_interval)  # Minimum 30 seconds
            logger.info(f"Cache cleanup interval updated to {self._cleanup_interval}s")

        if enabled is not None:
            self._cache_enabled = enabled
            if not enabled:
                self._clear_cache()
            logger.info(f"Cache {'enabled' if enabled else 'disabled'}")

    def get_person_data(self, person_id: str) -> Optional[Dict[str, Any]]:
        """
        Fast cached lookup for person data (name, title, registration_id)
        Returns None if person doesn't exist
        Automatically refreshes expired entries from database
        """
        if not self._cache_enabled:
            # Cache disabled - fall back to DB query
            try:
                with self.get_registrations_connection() as (con, cursor):
                    cursor.execute(
                        f"SELECT name, title, registration_id FROM fr_registrations WHERE id = {self.registrations_placeholder}",
                        (person_id,)
                    )
                    row = cursor.fetchone()
                    if row:
                        return {
                            'id': person_id,
                            'name': row[0],
                            'title': row[1],
                            'registration_id': row[2]
                        }
                    return None
            except Exception as e:
                logger.error(f"Error fetching person data from DB: {e}")
                return None

        # Try cache first - check if entry exists and is not expired
        with self._cache_lock:
            if person_id in self._person_cache and self._is_cache_entry_valid(person_id):
                self._cache_hits += 1
                data = self._person_cache[person_id].copy()
                data['id'] = person_id
                return data

            # Cache miss or expired entry
            self._cache_misses += 1

        # Fetch from DB and update cache
        try:
            with self.get_registrations_connection() as (con, cursor):
                cursor.execute(
                    f"SELECT name, title, registration_id FROM fr_registrations WHERE id = {self.registrations_placeholder}",
                    (person_id,)
                )
                row = cursor.fetchone()
                if row:
                    name, title, registration_id = row
                    self._update_cache_entry(person_id, name, title, registration_id)
                    return {
                        'id': person_id,
                        'name': name,
                        'title': title,
                        'registration_id': registration_id
                    }
                return None
        except Exception as e:
            logger.error(f"Error fetching person data: {e}")
            return None

    def get_person_data_batch(self, person_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """
        Batch lookup for multiple person IDs - optimized for recognition with crowds
        Returns dict mapping person_id -> person_data
        Automatically refreshes expired entries from database
        """
        result = {}
        uncached_ids = []

        # Check cache first - only use valid (non-expired) entries
        with self._cache_lock:
            for person_id in person_ids:
                if person_id in self._person_cache and self._is_cache_entry_valid(person_id):
                    self._cache_hits += 1
                    data = self._person_cache[person_id].copy()
                    data['id'] = person_id
                    result[person_id] = data
                else:
                    self._cache_misses += 1
                    uncached_ids.append(person_id)

        # Batch fetch uncached or expired IDs from database
        if uncached_ids:
            try:
                with self.get_registrations_connection() as (con, cursor):
                    # Build query for batch fetch
                    placeholders = ','.join([self.registrations_placeholder] * len(uncached_ids))
                    cursor.execute(
                        f"SELECT id, name, title, registration_id FROM fr_registrations WHERE id IN ({placeholders})",
                        uncached_ids
                    )
                    rows = cursor.fetchall()

                    for row in rows:
                        person_id, name, title, registration_id = row
                        # Update cache
                        self._update_cache_entry(person_id, name, title, registration_id)
                        # Add to result
                        result[person_id] = {
                            'id': person_id,
                            'name': name,
                            'title': title,
                            'registration_id': registration_id
                        }
            except Exception as e:
                logger.error(f"Error in batch person data fetch: {e}")

        return result

    def create_database(self):
        """Initialize database files/connections"""
        # Create SQLite file if it doesn't exist
        try:
            with self.get_credentials_connection() as (con, cursor):
                logger.info('SQLite database file created/verified')
        except Exception as e:
            logger.error(f"Failed to create SQLite database: {e}")
            raise

        # Test PostgreSQL connection if being used
        if self.use_postgres_for_registrations:
            try:
                with self.get_registrations_connection() as (con, cursor):
                    logger.info('PostgreSQL connection verified')
            except Exception as e:
                logger.warning(f"⚠️ PostgreSQL connection test failed: {e}")
                logger.warning("⚠️ Falling back to SQLite for fr_registrations table")
                self.use_postgres_for_registrations = False

    def create_table_credentials(self):
        """Create credentials table in SQLite"""
        command = '''CREATE TABLE IF NOT EXISTS credentials(name TEXT, id TEXT, password TEXT)'''
        try:
            with self.get_credentials_connection() as (con, cursor):
                cursor.execute(command)
                logger.info('credentials table created/verified in SQLite')
        except Exception as e:
            logger.error(f"Error creating credentials table: {e}")
            raise

    def create_table_registrations(self):
        """Create fr_registrations table in PostgreSQL or SQLite with automatic schema migration"""
        command = f'''CREATE TABLE IF NOT EXISTS fr_registrations(
            id TEXT PRIMARY KEY,
            name TEXT,
            title TEXT,
            registration_id TEXT UNIQUE
        )'''
        try:
            # Step 1: Create table
            with self.get_registrations_connection() as (con, cursor):
                cursor.execute(command)
                db_type = "PostgreSQL" if self.use_postgres_for_registrations else "SQLite"
                logger.info(f'fr_registrations table created/verified in {db_type}')

            # Step 2: Run migrations in separate transaction
            self._run_schema_migrations()

        except Exception as e:
            logger.error(f"Error creating fr_registrations table: {e}")
            raise

    def _run_schema_migrations(self):
        """Run schema migrations for fr_registrations table in separate transaction"""
        # Migration 1: Add title column if missing
        try:
            with self.get_registrations_connection() as (con, cursor):
                # Check if column exists
                try:
                    cursor.execute("SELECT title FROM fr_registrations LIMIT 0")
                    # Column exists, no migration needed
                except Exception as check_error:
                    # Column doesn't exist, need to add it
                    # First rollback the failed SELECT
                    try:
                        con.rollback()
                    except:
                        pass

                    # Now add the column in a new statement
                    logger.warning("⚠️ Migration: 'title' column missing in fr_registrations table, adding it now...")
                    cursor.execute("ALTER TABLE fr_registrations ADD COLUMN title TEXT")
                    logger.info("✅ Migration: 'title' column added successfully")

        except Exception as e:
            logger.error(f"Schema migration failed: {e}")
            # Don't raise - allow system to continue, cache will just not work
            logger.warning("⚠️ System will continue but cache may not function properly")

    def __del__(self):
        """Cleanup connection pool and cache thread on object destruction"""
        # Stop cache cleanup thread
        if hasattr(self, '_cleanup_running'):
            self._cleanup_running = False
            if hasattr(self, '_cleanup_thread') and self._cleanup_thread:
                try:
                    self._cleanup_thread.join(timeout=2)
                except:
                    pass

        # Close PostgreSQL connection pool
        if hasattr(self, 'use_postgres_for_registrations') and self.use_postgres_for_registrations:
            if hasattr(self, 'registrations_pool') and self.registrations_pool:
                try:
                    self.registrations_pool.closeall()
                    logger.info("✅ PostgreSQL connection pool closed")
                except Exception as e:
                    logger.error(f"Error closing PostgreSQL connection pool: {e}")

    def insert_default_credentials(self, username="admin", ID_="admin", password='1234'):
        """Insert default admin into credentials table (SQLite)"""
        try:
            with self.get_credentials_connection() as (con, cursor):
                command = f"SELECT * FROM credentials WHERE id = {self.credentials_placeholder}"
                cursor.execute(command, (ID_,))
                rows = cursor.fetchall()
                if not rows:
                    command_insertvalue = f"INSERT INTO credentials (name,id,password) VALUES ({self.credentials_placeholder}, {self.credentials_placeholder},{self.credentials_placeholder})"
                    cursor.execute(command_insertvalue, (username, ID_, password))
                    logger.info('Default admin created in SQLite')
        except Exception as e:
            logger.error(f"Error inserting default admin: {e}")
            raise

    def insert_into_registrations(self, id_, name, title, registration_id):
        """Insert registration into fr_registrations table (PostgreSQL or SQLite)"""
        try:
            with self.get_registrations_connection() as (con, cursor):
                command = f"SELECT * FROM fr_registrations WHERE id = {self.registrations_placeholder}"
                cursor.execute(command, (id_,))
                rows = cursor.fetchall()
                if rows:
                    logger.warning(f"Registration with id {id_} already exists")
                    return "id already exist"

                command_insertvalue = f"INSERT INTO fr_registrations (id,name,title,registration_id) VALUES ({self.registrations_placeholder}, {self.registrations_placeholder}, {self.registrations_placeholder}, {self.registrations_placeholder})"
                cursor.execute(command_insertvalue, (id_, name, title, registration_id))
                logger.info(f"New registration added: {id_} - {name}")

                # Update cache
                self._update_cache_entry(id_, name, title, registration_id)

                return "New registration Added"
        except Exception as e:
            logger.error(f"Error inserting registration {id_}: {e}")
            return f"Error: {e}"
    def authenticate_admin(self, id_, upassword):
        """Authenticate admin from credentials table (SQLite)"""
        try:
            with self.get_credentials_connection() as (con, cursor):
                command = f"SELECT * FROM credentials WHERE id = {self.credentials_placeholder}"
                cursor.execute(command, (id_,))
                rows = cursor.fetchall()
                if rows:
                    row = rows[0]
                    cpassword = row[2]
                    if upassword == cpassword:
                        #logger.info(f"Admin {id_} authenticated successfully")
                        return 'Login Success'
                    else:
                        logger.warning(f"Failed login attempt for admin {id_}: wrong password")
                        return 'Wrong password Try again'
                else:
                    logger.warning(f"Failed login attempt: admin id {id_} not found")
                    return 'id not found'
        except Exception as e:
            logger.error(f"Error authenticating admin {id_}: {e}")
            raise

    def get_id_from_name(self, name):
        """Get person ID from name (PostgreSQL or SQLite) - not cached (rare operation)"""
        try:
            with self.get_registrations_connection() as (con, cursor):
                command = f"SELECT id FROM fr_registrations WHERE name = {self.registrations_placeholder}"
                cursor.execute(command, (name,))
                rows = cursor.fetchall()
                if rows:
                    return rows[0][0]
                return None
        except Exception as e:
            logger.error(f"Error getting ID from name {name}: {e}")
            raise

    def get_name_from_id(self, id_):
        """Get person name from ID (PostgreSQL or SQLite) - uses cache"""
        data = self.get_person_data(id_)
        return data['name'] if data else None

    def get_person_name(self, id_):
        """Get person name from ID (PostgreSQL or SQLite) - uses cache"""
        data = self.get_person_data(id_)
        return data['name'] if data else None

    def get_person_title(self, id_):
        """Get person title from ID (PostgreSQL or SQLite) - uses cache"""
        data = self.get_person_data(id_)
        return data['title'] if data else None

    def get_registration_id(self, id_):
        """Get registration ID from person ID (PostgreSQL or SQLite) - uses cache"""
        data = self.get_person_data(id_)
        return data['registration_id'] if data else None

    def check_registration_exists(self, registration_id):
        """Check if a registration ID already exists in the database (PostgreSQL or SQLite)"""
        try:
            with self.get_registrations_connection() as (con, cursor):
                command = f"SELECT id FROM fr_registrations WHERE registration_id = {self.registrations_placeholder}"
                cursor.execute(command, (registration_id,))
                rows = cursor.fetchall()
                return len(rows) > 0
        except Exception as e:
            logger.error(f"Error checking registration existence for {registration_id}: {e}")
            raise

    def get_registrations_list(self, page: int = 1, page_size: int = None) -> Dict[str, Any]:
        """
        Get list of person IDs with pagination support (PostgreSQL or SQLite)
        Args:
            page: Page number (1-indexed)
            page_size: Number of results per page (default: DEFAULT_PAGE_SIZE)
        Returns:
            Dict containing:
                - data: List of person IDs
                - page: Current page number
                - page_size: Items per page
                - total: Total number of records
                - total_pages: Total number of pages
        """
        if page_size is None:
            page_size = self.DEFAULT_PAGE_SIZE

        try:
            page, page_size = self._validate_pagination(page, page_size)
            offset = self._calculate_offset(page, page_size)

            with self.get_registrations_connection() as (con, cursor):
                # Get total count
                cursor.execute("SELECT COUNT(*) FROM fr_registrations")
                total = cursor.fetchone()[0]

                # Get paginated results
                command = f"SELECT id FROM fr_registrations ORDER BY id LIMIT {page_size} OFFSET {offset}"
                cursor.execute(command)
                rows = cursor.fetchall()
                registrations_list = [row[0] for row in rows]

                total_pages = (total + page_size - 1) // page_size  # Ceiling division

                return {
                    'data': registrations_list,
                    'page': page,
                    'page_size': page_size,
                    'total': total,
                    'total_pages': total_pages
                }
        except Exception as e:
            logger.error(f"Error getting registrations list: {e}")
            raise

    def get_registrations_list_all(self) -> List[str]:
        """Get all person IDs without pagination (use with caution for large datasets)"""
        try:
            with self.get_registrations_connection() as (con, cursor):
                cursor.execute("SELECT id FROM fr_registrations ORDER BY id")
                rows = cursor.fetchall()
                return [row[0] for row in rows]
        except Exception as e:
            logger.error(f"Error getting all registrations: {e}")
            raise

    def get_admin_name(self, id_):
        """Get admin name from ID (SQLite)"""
        try:
            with self.get_credentials_connection() as (con, cursor):
                command = f"SELECT name FROM credentials WHERE id = {self.credentials_placeholder}"
                cursor.execute(command, (id_,))
                rows = cursor.fetchall()
                if rows:
                    return rows[0][0]
                return None
        except Exception as e:
            logger.error(f"Error getting admin name for ID {id_}: {e}")
            raise

    def change_admin_id_password(self, oldadminid, oldadminpass, newadminid, newadminpass, newadminpassconf):
        """Change admin password (SQLite)"""
        try:
            status = self.authenticate_admin(oldadminid, oldadminpass)
            if status == 'Login Success':
                if newadminpass == newadminpassconf:
                    status = self.delete_credentials(oldadminid)
                    if status == False:
                        logger.error(f"Failed to delete old credentials for {oldadminid}")
                        return 'Update error'
                    self.insert_default_credentials('Admin', newadminid, newadminpass)
                    logger.info(f"Admin credentials updated: {oldadminid} -> {newadminid}")
                    return 'Admin id password updated'
                else:
                    logger.warning("Password confirmation mismatch during admin credential change")
                    return 'confirm password not matched'
            else:
                logger.warning(f"Failed to change admin credentials: authentication failed for {oldadminid}")
                return 'previous admin id or password not matched'
        except Exception as e:
            logger.error(f"Error changing admin credentials: {e}")
            raise

    def get_all_registration_ids(self, page: int = 1, page_size: int = None) -> Dict[str, Any]:
        """
        Get all registration IDs with pagination (PostgreSQL or SQLite)
        Args:
            page: Page number (1-indexed)
            page_size: Number of results per page (default: DEFAULT_PAGE_SIZE)
        Returns:
            Dict with paginated results (same format as get_registrations_list)
        """
        return self.get_registrations_list(page, page_size)

    def get_all_registration_ids_list(self) -> List[str]:
        """Get all registration IDs as a simple list (use with caution for large datasets)"""
        return self.get_registrations_list_all()

    def total_registrations(self) -> int:
        """Get total number of registrations (PostgreSQL or SQLite)"""
        try:
            with self.get_registrations_connection() as (con, cursor):
                cursor.execute("SELECT COUNT(*) FROM fr_registrations")
                count = cursor.fetchone()[0]
                return count
        except Exception as e:
            logger.error(f"Error getting total registrations count: {e}")
            raise

    def delete_registration(self, id_):
        """
        Delete registration from fr_registrations table (PostgreSQL or SQLite).
        Returns True if database deletion succeeds, regardless of file deletion status.
        File deletion should be handled by the API endpoint via face_recognizer.remove_person()
        """
        try:
            # Get name before deletion for logging
            name = self.get_person_name(id_)

            with self.get_registrations_connection() as (con, cursor):
                command = f"DELETE FROM fr_registrations WHERE id = {self.registrations_placeholder}"
                cursor.execute(command, (id_,))

                if cursor.rowcount > 0:
                    logger.info(f"Deleted registration: {id_} - {name}")

                    # Invalidate cache
                    self._invalidate_cache_entry(id_)

                    return True
                else:
                    logger.warning(f"No registration found with ID {id_} to delete")
                    return False
        except Exception as e:
            logger.error(f"⚠️ Failed to delete registration {id_} from database: {e}")
            return False

    def delete_credentials(self, id_):
        """Delete admin from credentials table (SQLite)"""
        try:
            with self.get_credentials_connection() as (con, cursor):
                command = f"DELETE FROM credentials WHERE id = {self.credentials_placeholder}"
                cursor.execute(command, (id_,))

                if cursor.rowcount > 0:
                    logger.info(f"Deleted admin credentials: {id_}")
                    return True
                else:
                    logger.warning(f"No credentials found with ID {id_} to delete")
                    return False
        except Exception as e:
            logger.error(f"⚠️ Failed to delete credentials {id_}: {e}")
            return False

    def delete_datbase(self):
        """Drop database (SQLite only) - USE WITH CAUTION"""
        logger.warning("⚠️ delete_datbase() called - this is a dangerous operation")
        try:
            with self.get_credentials_connection() as (con, cursor):
                # SQLite doesn't support DROP DATABASE, this would need to delete the file
                import os
                if os.path.exists(self.dbname):
                    os.remove(self.dbname)
                    logger.info(f'Success! Database file {self.dbname} deleted')
                else:
                    logger.warning(f'Database file {self.dbname} does not exist')
        except Exception as e:
            logger.error(f"Failed to delete database: {e}")
            raise

    # Health check method
    def health_check(self) -> Dict[str, Any]:
        """
        Check health of database connections
        Returns dict with connection status for both databases
        """
        health = {
            'credentials_db': {'type': 'SQLite', 'status': 'unknown', 'error': None},
            'registrations_db': {
                'type': 'PostgreSQL' if self.use_postgres_for_registrations else 'SQLite',
                'status': 'unknown',
                'error': None
            }
        }

        # Test credentials connection
        try:
            with self.get_credentials_connection() as (con, cursor):
                cursor.execute('SELECT 1')
                health['credentials_db']['status'] = 'healthy'
        except Exception as e:
            health['credentials_db']['status'] = 'unhealthy'
            health['credentials_db']['error'] = str(e)
            logger.error(f"Credentials DB health check failed: {e}")

        # Test registrations connection
        try:
            with self.get_registrations_connection() as (con, cursor):
                cursor.execute('SELECT 1')
                health['registrations_db']['status'] = 'healthy'
        except Exception as e:
            health['registrations_db']['status'] = 'unhealthy'
            health['registrations_db']['error'] = str(e)
            logger.error(f"Registrations DB health check failed: {e}")

        return health

