from app.database import supabase

result = supabase.table('scan_jobs').select('*').order('created_at', desc=True).limit(3).execute()
for r in result.data:
    print(f"ID: {r['id']}")
    print(f"Status: {r['status']}")
    print(f"Error: {r.get('error_message')}")
    print(f"Apify Run ID: {r.get('apify_run_id')}")
    print('---')

















