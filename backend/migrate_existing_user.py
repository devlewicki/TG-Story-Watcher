from sqlalchemy import text
from app.db import SessionLocal, init_db
from app.models import User, TelegramAccount, SettingsStore
from app.multitenancy import hash_password
init_db(); db=SessionLocal()
try:
 db.execute(text("CREATE TABLE IF NOT EXISTS users (id SERIAL PRIMARY KEY, first_name VARCHAR(255) NOT NULL, last_name VARCHAR(255) NOT NULL, email VARCHAR(320) UNIQUE NOT NULL, password_hash VARCHAR(512) NOT NULL, created_at TIMESTAMPTZ NOT NULL)"))
 if not db.execute(text("SELECT 1 FROM information_schema.columns WHERE table_name='telegram_accounts' AND column_name='user_id'")).fetchone():
  db.execute(text("ALTER TABLE telegram_accounts ADD COLUMN user_id INTEGER REFERENCES users(id) ON DELETE CASCADE")); db.execute(text("CREATE INDEX IF NOT EXISTS ix_telegram_accounts_user_id ON telegram_accounts(user_id)"))
 db.commit(); u=db.query(User).filter_by(email="mlewickiy@yandex.ru").first()
 if not u:
  u=User(first_name="Maxim",last_name="Lewickiy",email="mlewickiy@yandex.ru",password_hash=hash_password("test1234")); db.add(u); db.flush()
 a=db.query(TelegramAccount).filter_by(id=1).first()
 if a and a.user_id is None:a.user_id=u.id
 for section in ("discovery","filters","general","limits","monitoring","queue","telegram","view"):
  legacy=db.get(SettingsStore,section)
  scoped=db.get(SettingsStore,f"user:{u.id}:{section}")
  if legacy and scoped is None: db.add(SettingsStore(key=f"user:{u.id}:{section}",value=legacy.value))
 db.commit(); print({"user_id":u.id,"account_id":a.id if a else None})
finally:db.close()
