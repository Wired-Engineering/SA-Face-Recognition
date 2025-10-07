#!/usr/bin/env python3
"""Test database connection and queries"""

import sys
sys.path.insert(0, 'src/python')

from DatabaseManager import MySqlite3Manager

# Initialize database
db = MySqlite3Manager()

# Test queries
print("\n=== Database Test ===")

print("\n1. Total registrations:")
try:
    total = db.total_registrations()
    print(f"   Total: {total}")
except Exception as e:
    print(f"   ERROR: {e}")

print("\n2. Get all registration IDs (list):")
try:
    ids = db.get_all_registration_ids_list()
    print(f"   Count: {len(ids)}")
    print(f"   First 5: {ids[:5] if len(ids) >= 5 else ids}")
except Exception as e:
    print(f"   ERROR: {e}")

print("\n3. Cache stats:")
try:
    stats = db.get_cache_stats()
    print(f"   Enabled: {stats['enabled']}")
    print(f"   Size: {stats['size']}")
    print(f"   Hit rate: {stats['hit_rate']}%")
except Exception as e:
    print(f"   ERROR: {e}")

print("\n4. Sample person data:")
try:
    if ids:
        sample_id = ids[0]
        data = db.get_person_data(sample_id)
        print(f"   Person ID: {sample_id}")
        print(f"   Data: {data}")
except Exception as e:
    print(f"   ERROR: {e}")

print("\n5. Health check:")
try:
    health = db.health_check()
    print(f"   Credentials DB: {health['credentials_db']['status']}")
    print(f"   Registrations DB: {health['registrations_db']['status']} ({health['registrations_db']['type']})")
    if health['registrations_db']['error']:
        print(f"   Error: {health['registrations_db']['error']}")
except Exception as e:
    print(f"   ERROR: {e}")

print("\n=== Test Complete ===\n")
