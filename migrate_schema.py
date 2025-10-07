#!/usr/bin/env python3
"""
Schema Migration Script: Update SQLite database to new naming scheme

Migrates:
- ADMIN table → CREDENTIALS table
- PERSON table → FR_REGISTRATIONS table
- Registration column → Registration_id column

NOTE: This only migrates the local SQLite database.
PostgreSQL tables will be created automatically with the new schema on first startup.

Usage:
    python migrate_schema.py
"""

import sqlite3
import os
import sys

def migrate_sqlite(db_path):
    """Migrate SQLite database schema"""
    print(f"\n{'='*60}")
    print(f"  SQLite Schema Migration: {db_path}")
    print(f"{'='*60}\n")

    if not os.path.exists(db_path):
        print(f"❌ Database not found at {db_path}")
        return False

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Check which tables exist
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
        existing_tables = [row[0] for row in cursor.fetchall()]
        print(f"📋 Found tables: {existing_tables}\n")

        migrated = False

        # Migrate ADMIN → CREDENTIALS
        if 'ADMIN' in existing_tables:
            if 'CREDENTIALS' in existing_tables:
                print("⚠️  CREDENTIALS table already exists")
                print("   Dropping old ADMIN table...")
                cursor.execute("DROP TABLE ADMIN")
                conn.commit()
                print("✅ Old ADMIN table removed")
                migrated = True
            else:
                print("🔄 Migrating ADMIN → CREDENTIALS...")
                cursor.execute("ALTER TABLE ADMIN RENAME TO CREDENTIALS")
                conn.commit()
                print("✅ ADMIN table renamed to CREDENTIALS")
                migrated = True

        # Migrate PERSON → FR_REGISTRATIONS with column rename
        if 'PERSON' in existing_tables:
            if 'FR_REGISTRATIONS' in existing_tables:
                # Check if FR_REGISTRATIONS has data
                cursor.execute("SELECT COUNT(*) FROM FR_REGISTRATIONS")
                fr_count = cursor.fetchone()[0]

                cursor.execute("SELECT COUNT(*) FROM PERSON")
                person_count = cursor.fetchone()[0]

                if fr_count == 0 and person_count > 0:
                    # FR_REGISTRATIONS is empty but PERSON has data - need to migrate
                    print("⚠️  FR_REGISTRATIONS table exists but is empty")
                    print(f"   Found {person_count} records in PERSON table - migrating data...")

                    cursor.execute("PRAGMA table_info(PERSON)")
                    columns = {col[1]: col for col in cursor.fetchall()}

                    if 'Registration' in columns:
                        # Copy data with column rename
                        cursor.execute('''
                            INSERT INTO FR_REGISTRATIONS (Id, Name, Title, Registration_id)
                            SELECT Id, Name, Title, Registration FROM PERSON
                        ''')
                        conn.commit()
                        print(f"✅ Migrated {person_count} records to FR_REGISTRATIONS")
                    else:
                        # Copy data without column rename
                        cursor.execute('''
                            INSERT INTO FR_REGISTRATIONS (Id, Name, Title, Registration_id)
                            SELECT Id, Name, Title, Registration_id FROM PERSON
                        ''')
                        conn.commit()
                        print(f"✅ Copied {person_count} records to FR_REGISTRATIONS")

                    print("   Dropping old PERSON table...")
                    cursor.execute("DROP TABLE PERSON")
                    conn.commit()
                    print("✅ Old PERSON table removed")
                    migrated = True
                elif person_count == 0:
                    # PERSON is empty, safe to drop
                    print("   PERSON table is empty - removing...")
                    cursor.execute("DROP TABLE PERSON")
                    conn.commit()
                    print("✅ Empty PERSON table removed")
                    migrated = True
                else:
                    print(f"ℹ️  FR_REGISTRATIONS has {fr_count} records, PERSON has {person_count} records")
                    print("   Both tables have data - manual intervention needed")
                    print("   Skipping automatic migration to prevent data loss")
            else:
                print("🔄 Migrating PERSON → FR_REGISTRATIONS...")

                # Check if Registration column exists
                cursor.execute("PRAGMA table_info(PERSON)")
                columns = {col[1]: col for col in cursor.fetchall()}

                if 'Registration' in columns:
                    # Need to migrate with column rename
                    print("   Creating FR_REGISTRATIONS table with new schema...")
                    cursor.execute('''
                        CREATE TABLE FR_REGISTRATIONS(
                            Id TEXT PRIMARY KEY,
                            Name TEXT,
                            Title TEXT,
                            Registration_id TEXT UNIQUE
                        )
                    ''')

                    print("   Copying data from PERSON to FR_REGISTRATIONS...")
                    cursor.execute('''
                        INSERT INTO FR_REGISTRATIONS (Id, Name, Title, Registration_id)
                        SELECT Id, Name, Title, Registration FROM PERSON
                    ''')

                    print("   Dropping old PERSON table...")
                    cursor.execute("DROP TABLE PERSON")

                    conn.commit()
                    print("✅ PERSON table migrated to FR_REGISTRATIONS with Registration_id column")
                    migrated = True
                else:
                    # Just rename the table
                    print("   Renaming PERSON → FR_REGISTRATIONS...")
                    cursor.execute("ALTER TABLE PERSON RENAME TO FR_REGISTRATIONS")
                    conn.commit()
                    print("✅ PERSON table renamed to FR_REGISTRATIONS")
                    migrated = True

        conn.close()

        if migrated:
            print(f"\n{'='*60}")
            print("  ✅ SQLite Migration Complete!")
            print(f"{'='*60}\n")
            return True
        else:
            print("\n✓ No migration needed - tables already using new schema\n")
            return True

    except Exception as e:
        print(f"\n❌ Migration failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Main migration function"""
    print(f"\n{'='*60}")
    print("  SQLite Schema Migration")
    print(f"{'='*60}")
    print("\nThis script will migrate your LOCAL SQLite database to the new schema:")
    print("  • ADMIN → CREDENTIALS")
    print("  • PERSON → FR_REGISTRATIONS")
    print("  • Registration column → Registration_id")
    print()
    print("NOTE: PostgreSQL tables will be created with the new schema automatically")
    print("      when you start the application with DEV_DATABASE_URL or DATABASE_URL set.")
    print()

    response = input("Continue with SQLite migration? (yes/no): ").strip().lower()
    if response != 'yes':
        print("❌ Migration cancelled")
        return

    # Migrate SQLite database only
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
        sqlite_path = "src/python/system/Attendance.db"  # Default for error message
    if os.path.exists(sqlite_path):
        if not migrate_sqlite(sqlite_path):
            print("\n⚠️  Migration failed")
            return
    else:
        print(f"\n⚠️  SQLite database not found at {sqlite_path}")
        print("Nothing to migrate - tables will be created on first run.")
        return

    print(f"\n{'='*60}")
    print("  🎉 Migration Complete!")
    print(f"{'='*60}")
    print("\n📝 Summary:")
    print("   ✓ SQLite schema updated to new naming")
    print("   ✓ CREDENTIALS table contains admin logins (local)")
    print("   ✓ FR_REGISTRATIONS table contains registrations (local)")
    print("   ✓ Registration_id column replaces Registration")
    print()
    print("   📌 PostgreSQL (if used):")
    print("      - Will create FR_REGISTRATIONS table automatically on startup")
    print("      - Uses new schema from the start (no migration needed)")
    print("\n⚡ Next steps:")
    print("   1. Set DEV_DATABASE_URL in .env for development database")
    print("   2. Set DATABASE_URL in .env for production database (Replit)")
    print("   3. Restart your application: pnpm start")
    print("   4. Verify admin login works")
    print("   5. Verify registration operations work")
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
