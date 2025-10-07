#!/usr/bin/env python3
"""
Data Migration Script: Copy FR_REGISTRATIONS data from SQLite to PostgreSQL

This script migrates existing registration data from your local SQLite database
to PostgreSQL when you're ready to switch to cloud storage.

Prerequisites:
1. Run migrate_schema.py first to ensure table names are updated
2. Set DEV_DATABASE_URL or DATABASE_URL in your .env file
3. Ensure PostgreSQL database is accessible

Usage:
    python migrate_data_to_postgres.py

Options:
    - Copy all data from SQLite to PostgreSQL
    - Three cleanup modes: keep as backup, clear data, or drop table
    - Handles duplicate detection (won't re-insert existing records)
"""

import sqlite3
import psycopg2
from psycopg2 import pool
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

# Load .env file
env_path = Path(__file__).parent / '.env'
load_dotenv(dotenv_path=env_path)


def get_postgres_url():
    """Get PostgreSQL URL from environment"""
    url = os.getenv('DEV_DATABASE_URL') or os.getenv('DATABASE_URL')
    if not url:
        print("❌ No database URL found!")
        print("   Please set DEV_DATABASE_URL or DATABASE_URL in your .env file")
        return None
    return url


def connect_sqlite(db_path):
    """Connect to SQLite database"""
    if not os.path.exists(db_path):
        print(f"❌ SQLite database not found at {db_path}")
        return None
    return sqlite3.connect(db_path)


def connect_postgres(database_url):
    """Connect to PostgreSQL database"""
    try:
        conn = psycopg2.connect(database_url)
        return conn
    except Exception as e:
        print(f"❌ Failed to connect to PostgreSQL: {e}")
        return None


def ensure_postgres_table(pg_conn):
    """Ensure FR_REGISTRATIONS table exists in PostgreSQL"""
    try:
        cursor = pg_conn.cursor()
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS FR_REGISTRATIONS(
                Id TEXT PRIMARY KEY,
                Name TEXT,
                Title TEXT,
                Registration_id TEXT UNIQUE
            )
        ''')
        pg_conn.commit()
        cursor.close()
        print("✅ PostgreSQL FR_REGISTRATIONS table ready")
        return True
    except Exception as e:
        print(f"❌ Failed to create PostgreSQL table: {e}")
        return False


def get_sqlite_registrations(sqlite_conn):
    """Read all registrations from SQLite"""
    try:
        cursor = sqlite_conn.cursor()

        # Check if FR_REGISTRATIONS table exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='FR_REGISTRATIONS'")
        if not cursor.fetchone():
            print("⚠️  FR_REGISTRATIONS table not found in SQLite")
            print("   Please run migrate_schema.py first to update table names")
            return None

        cursor.execute("SELECT Id, Name, Title, Registration_id FROM FR_REGISTRATIONS")
        rows = cursor.fetchall()
        cursor.close()
        return rows
    except Exception as e:
        print(f"❌ Failed to read from SQLite: {e}")
        return None


def get_postgres_existing_ids(pg_conn):
    """Get set of existing IDs in PostgreSQL to avoid duplicates"""
    try:
        cursor = pg_conn.cursor()
        cursor.execute("SELECT Id FROM FR_REGISTRATIONS")
        existing_ids = {row[0] for row in cursor.fetchall()}
        cursor.close()
        return existing_ids
    except Exception as e:
        print(f"❌ Failed to read existing PostgreSQL IDs: {e}")
        return set()


def migrate_data(sqlite_conn, pg_conn, sqlite_cleanup_mode='keep'):
    """
    Migrate data from SQLite to PostgreSQL

    Args:
        sqlite_cleanup_mode: 'keep', 'clear', or 'drop'
            - 'keep': Keep SQLite data as backup
            - 'clear': Clear SQLite FR_REGISTRATIONS data (DELETE FROM)
            - 'drop': Drop SQLite FR_REGISTRATIONS table entirely
    """
    print(f"\n{'='*60}")
    print("  Data Migration: SQLite → PostgreSQL")
    print(f"{'='*60}\n")

    # Read SQLite data
    print("📖 Reading data from SQLite...")
    sqlite_rows = get_sqlite_registrations(sqlite_conn)

    if sqlite_rows is None:
        return False

    if len(sqlite_rows) == 0:
        print("ℹ️  No data found in SQLite FR_REGISTRATIONS table")
        print("   Nothing to migrate.")
        return True

    print(f"   Found {len(sqlite_rows)} registrations in SQLite\n")

    # Get existing PostgreSQL IDs
    print("🔍 Checking for existing data in PostgreSQL...")
    existing_ids = get_postgres_existing_ids(pg_conn)
    print(f"   Found {len(existing_ids)} existing registrations in PostgreSQL\n")

    # Filter out duplicates
    new_rows = [row for row in sqlite_rows if row[0] not in existing_ids]
    duplicate_count = len(sqlite_rows) - len(new_rows)

    if duplicate_count > 0:
        print(f"⚠️  Skipping {duplicate_count} duplicate records (already in PostgreSQL)")

    if len(new_rows) == 0:
        print("✅ All SQLite data already exists in PostgreSQL")
        print("   No new records to migrate.\n")
    else:
        # Insert new data
        print(f"📝 Migrating {len(new_rows)} new registrations to PostgreSQL...")

        try:
            cursor = pg_conn.cursor()

            for idx, (person_id, name, title, reg_id) in enumerate(new_rows, 1):
                cursor.execute(
                    "INSERT INTO FR_REGISTRATIONS (Id, Name, Title, Registration_id) VALUES (%s, %s, %s, %s)",
                    (person_id, name, title, reg_id)
                )

                # Progress indicator
                if idx % 10 == 0 or idx == len(new_rows):
                    print(f"   Progress: {idx}/{len(new_rows)} records migrated...")

            pg_conn.commit()
            cursor.close()

            print(f"\n✅ Successfully migrated {len(new_rows)} registrations to PostgreSQL\n")

        except Exception as e:
            print(f"\n❌ Migration failed: {e}")
            pg_conn.rollback()
            return False

    # Handle SQLite cleanup based on mode
    if sqlite_cleanup_mode == 'clear':
        print("🗑️  Clearing SQLite FR_REGISTRATIONS data...")
        try:
            cursor = sqlite_conn.cursor()
            cursor.execute("DELETE FROM FR_REGISTRATIONS")
            sqlite_conn.commit()
            cursor.close()
            print("✅ SQLite FR_REGISTRATIONS data cleared (table structure remains)\n")
        except Exception as e:
            print(f"❌ Failed to clear SQLite data: {e}\n")
            return False
    elif sqlite_cleanup_mode == 'drop':
        print("🗑️  Dropping SQLite FR_REGISTRATIONS table...")
        try:
            cursor = sqlite_conn.cursor()
            cursor.execute("DROP TABLE FR_REGISTRATIONS")
            sqlite_conn.commit()
            cursor.close()
            print("✅ SQLite FR_REGISTRATIONS table dropped (PostgreSQL is now the only source)\n")
        except Exception as e:
            print(f"❌ Failed to drop SQLite table: {e}\n")
            return False
    else:  # keep
        print("💾 SQLite data kept as backup\n")

    return True


def main():
    """Main migration function"""
    print(f"\n{'='*60}")
    print("  Data Migration: SQLite → PostgreSQL")
    print(f"{'='*60}")
    print("\nThis script will migrate your FR_REGISTRATIONS data from SQLite to PostgreSQL.")
    print("\n📋 What this does:")
    print("   1. Reads all registrations from SQLite (system/Attendance.db)")
    print("   2. Copies them to PostgreSQL (DEV_DATABASE_URL or DATABASE_URL)")
    print("   3. Choose cleanup: keep backup, clear data, or drop table")
    print("\n⚠️  Important:")
    print("   - Run migrate_schema.py FIRST if you haven't already")
    print("   - Ensure DEV_DATABASE_URL or DATABASE_URL is set in .env")
    print("   - This won't duplicate records (checks for existing IDs)")
    print()

    response = input("Continue with data migration? (yes/no): ").strip().lower()
    if response != 'yes':
        print("❌ Migration cancelled")
        return

    # Get PostgreSQL URL
    pg_url = get_postgres_url()
    if not pg_url:
        return

    db_env = "DEV_DATABASE_URL" if os.getenv('DEV_DATABASE_URL') else "DATABASE_URL"
    print(f"\n🔌 Using PostgreSQL from: {db_env}")

    # Connect to databases
    # Try multiple possible paths (local dev vs Docker)
    possible_paths = [
        "src/python/system/Attendance.db",  # Running from project root
        "system/Attendance.db",              # Running from src/python/ or Docker
    ]

    sqlite_path = None
    for path in possible_paths:
        if os.path.exists(path):
            sqlite_path = path
            break

    if not sqlite_path:
        print("❌ SQLite database not found at any expected location")
        print("   Tried: src/python/system/Attendance.db, system/Attendance.db")
        return

    print(f"📂 Connecting to SQLite: {sqlite_path}")
    sqlite_conn = connect_sqlite(sqlite_path)
    if not sqlite_conn:
        return

    print(f"🔌 Connecting to PostgreSQL...")
    pg_conn = connect_postgres(pg_url)
    if not pg_conn:
        sqlite_conn.close()
        return

    print("✅ Database connections established\n")

    # Ensure PostgreSQL table exists
    if not ensure_postgres_table(pg_conn):
        sqlite_conn.close()
        pg_conn.close()
        return

    # Ask about SQLite cleanup
    print("\n❓ After successful migration, what should happen to SQLite data?")
    print("   1. Keep SQLite data as backup (recommended)")
    print("   2. Clear SQLite FR_REGISTRATIONS data (keeps empty table)")
    print("   3. Drop SQLite FR_REGISTRATIONS table entirely (PostgreSQL only)")
    print()
    cleanup_choice = input("Enter choice (1, 2, or 3): ").strip()

    cleanup_modes = {
        '1': 'keep',
        '2': 'clear',
        '3': 'drop'
    }
    cleanup_mode = cleanup_modes.get(cleanup_choice, 'keep')

    # Perform migration
    success = migrate_data(sqlite_conn, pg_conn, sqlite_cleanup_mode=cleanup_mode)

    # Close connections
    sqlite_conn.close()
    pg_conn.close()

    if success:
        print(f"{'='*60}")
        print("  🎉 Migration Complete!")
        print(f"{'='*60}")
        print("\n📝 Summary:")
        print("   ✓ FR_REGISTRATIONS data migrated to PostgreSQL")

        cleanup_status = {
            'keep': 'kept as backup',
            'clear': 'cleared (empty table remains)',
            'drop': 'dropped (table removed)'
        }
        print(f"   ✓ SQLite data {cleanup_status.get(cleanup_mode, 'kept as backup')}")

        print("\n⚡ Next steps:")
        print("   1. Restart your application: pnpm start")
        print("   2. Verify registration data appears correctly")
        print("   3. Test adding new registrations")
        print("   4. New registrations will now go to PostgreSQL")
        print()
    else:
        print(f"\n{'='*60}")
        print("  ❌ Migration Failed")
        print(f"{'='*60}")
        print("\nPlease review the errors above and try again.")
        print()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n❌ Migration cancelled by user (Ctrl+C)")
        sys.exit(1)
    except Exception as e:
        print(f"\n\n❌ Unexpected error: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
