"""
Run database migration for match feedback table.
Execute this script to apply the migration.
"""
import os
import sys
from pathlib import Path

# Add the app directory to the path
sys.path.insert(0, str(Path(__file__).parent))

from dotenv import load_dotenv
load_dotenv()

def run_migration():
    """Run the match feedback migration via Supabase."""
    
    supabase_url = os.getenv("SUPABASE_URL")
    service_role_key = os.getenv("SUPABASE_SERVICE_ROLE_KEY")
    
    if not supabase_url or not service_role_key:
        print("ERROR: Missing SUPABASE_URL or SUPABASE_SERVICE_ROLE_KEY in .env")
        return False
    
    # Read the migration file
    migration_path = Path(__file__).parent.parent / "supabase" / "migrations" / "004_add_match_feedback.sql"
    
    if not migration_path.exists():
        print(f"ERROR: Migration file not found at {migration_path}")
        return False
    
    migration_sql = migration_path.read_text(encoding='utf-8')
    
    print("=" * 60)
    print("MIGRATION: 004_add_match_feedback.sql")
    print("=" * 60)
    print()
    print("Supabase does not support running raw SQL via the REST API.")
    print("Please run the migration manually in Supabase SQL Editor.")
    print()
    print("INSTRUCTIONS:")
    print("-" * 60)
    print("1. Go to your Supabase project dashboard")
    print("2. Navigate to 'SQL Editor' in the left sidebar")
    print("3. Click 'New query'")
    print("4. Copy and paste the SQL below")
    print("5. Click 'Run' to execute")
    print("-" * 60)
    print()
    print("SQL TO RUN:")
    print("=" * 60)
    print()
    print(migration_sql)
    print()
    print("=" * 60)
    print()
    
    # Also save to a convenient file
    output_path = Path(__file__).parent / "migration_to_run.sql"
    output_path.write_text(migration_sql, encoding='utf-8')
    print(f"SQL also saved to: {output_path}")
    print()
    print("After running the migration, the following will be created:")
    print("  - match_feedback table")
    print("  - feedback_accuracy_stats view")
    print("  - calculate_optimal_threshold function")
    print("  - Indexes for efficient queries")
    print()
    
    return True


if __name__ == "__main__":
    run_migration()
