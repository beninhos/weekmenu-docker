import sqlite3
import os
from datetime import datetime

# Database pad
db_path = 'data/weekmenu.db'

# Check of database bestaat
if not os.path.exists(db_path):
    print("Database bestaat niet!")
    exit(1)

# Connect naar database
conn = sqlite3.connect(db_path)
cursor = conn.cursor()

try:
    # Check welke kolommen al bestaan
    cursor.execute("PRAGMA table_info(recipe)")
    recipe_columns = [column[1] for column in cursor.fetchall()]
    
    # Usage tracking kolommen toevoegen
    if 'usage_count' not in recipe_columns:
        print("Voeg usage_count kolom toe aan recipe tabel...")
        cursor.execute("ALTER TABLE recipe ADD COLUMN usage_count INTEGER DEFAULT 0")
        conn.commit()
        print("✅ Usage_count kolom toegevoegd!")
    
    # Check of alle velden er zijn die we nodig hebben
    required_fields = ['is_favorite', 'last_used', 'usage_count']
    missing_fields = [field for field in required_fields if field not in recipe_columns]
    
    if missing_fields:
        print(f"⚠️  Ontbrekende velden: {missing_fields}")
        for field in missing_fields:
            if field == 'is_favorite':
                cursor.execute("ALTER TABLE recipe ADD COLUMN is_favorite BOOLEAN DEFAULT 0")
            elif field == 'last_used':
                cursor.execute("ALTER TABLE recipe ADD COLUMN last_used DATETIME")
            elif field == 'usage_count':
                cursor.execute("ALTER TABLE recipe ADD COLUMN usage_count INTEGER DEFAULT 0")
        conn.commit()
        print("✅ Ontbrekende velden toegevoegd!")
    
    print("\n📊 Database status:")
    cursor.execute("PRAGMA table_info(recipe)")
    columns = cursor.fetchall()
    print("Recipe kolommen:")
    for col in columns:
        print(f"  - {col[1]} ({col[2]})")
    
    # Test query voor populaire recepten
    print("\n🔍 Test query voor populaire recepten:")
    cursor.execute("SELECT name, usage_count FROM recipe ORDER BY usage_count DESC LIMIT 5")
    popular = cursor.fetchall()
    if popular:
        for name, count in popular:
            print(f"  - {name}: {count} keer gebruikt")
    else:
        print("  Nog geen usage data")

except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()

finally:
    conn.close()

print("Usage tracking database migratie voltooid!")
