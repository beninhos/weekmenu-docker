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
    
    cursor.execute("PRAGMA table_info(menu_item)")
    menu_item_columns = [column[1] for column in cursor.fetchall()]
    
    # Recipe tabel updates
    if 'serves' not in recipe_columns:
        print("Voeg serves kolom toe aan recipe tabel...")
        cursor.execute("ALTER TABLE recipe ADD COLUMN serves INTEGER DEFAULT 4")
        conn.commit()
        print("✅ Serves kolom toegevoegd!")
    
    if 'is_favorite' not in recipe_columns:
        print("Voeg is_favorite kolom toe aan recipe tabel...")
        cursor.execute("ALTER TABLE recipe ADD COLUMN is_favorite BOOLEAN DEFAULT 0")
        conn.commit()
        print("✅ Is_favorite kolom toegevoegd!")
    
    if 'last_used' not in recipe_columns:
        print("Voeg last_used kolom toe aan recipe tabel...")
        cursor.execute("ALTER TABLE recipe ADD COLUMN last_used DATETIME")
        conn.commit()
        print("✅ Last_used kolom toegevoegd!")
    
    # Menu_item tabel updates
    if 'people_count' not in menu_item_columns:
        print("Voeg people_count kolom toe aan menu_item tabel...")
        cursor.execute("ALTER TABLE menu_item ADD COLUMN people_count INTEGER DEFAULT 4")
        conn.commit()
        print("✅ People_count kolom toegevoegd!")
    
    print("\n📊 Database status:")
    print(f"✅ Recipe kolommen: {len(recipe_columns) + 3}")
    print(f"✅ Menu_item kolommen: {len(menu_item_columns) + 1}")

except Exception as e:
    print(f"❌ Error: {e}")
    conn.rollback()

finally:
    conn.close()

print("Portie management database migratie voltooid!")
