import sqlite3
import pandas as pd
from utils import *
import os
import warnings

# Suppress pandas warning about non-SQLAlchemy connections (psycopg2 works fine)
warnings.filterwarnings('ignore', message='.*pandas only supports SQLAlchemy.*')

# Try to import PostgreSQL adapter
try:
    import psycopg2
    import psycopg2.pool
    POSTGRES_AVAILABLE = True
except ImportError:
    POSTGRES_AVAILABLE = False
    print("⚠️ psycopg2 not available - PostgreSQL support disabled")

month2number={'JAN':'01','FEB':'02','MAR':'03','APR':'04','MAY':'05','JUN':'06','JUL':'07','AUG':'08','SEP':'09','OCT':'10','NOV':'11','DEC':'12'}

class MySqlite3Manager:
    def __init__(self):
        # HYBRID SETUP:
        # - CREDENTIALS table: Always in SQLite (local)
        # - FR_REGISTRATIONS table: PostgreSQL if DATABASE_URL set, otherwise SQLite

        # SQLite setup (always used for CREDENTIALS table)
        self.dbname = "system/Attendance.db"
        print(f"🔌 CREDENTIALS table: Using SQLite ({self.dbname})")

        # PostgreSQL setup (for FR_REGISTRATIONS table)
        # Use DEV_DATABASE_URL in development, DATABASE_URL in production
        self.database_url = os.getenv('DEV_DATABASE_URL') or os.getenv('DATABASE_URL')
        self.use_postgres_for_registrations = bool(self.database_url and POSTGRES_AVAILABLE)

        if self.use_postgres_for_registrations:
            db_env = "DEV_DATABASE_URL" if os.getenv('DEV_DATABASE_URL') else "DATABASE_URL"
            print(f"🔌 FR_REGISTRATIONS table: Using PostgreSQL from {db_env}")
            # Initialize connection pool for PostgreSQL
            try:
                self.registrations_pool = psycopg2.pool.SimpleConnectionPool(
                    1, 10,  # min and max connections
                    self.database_url
                )
                if self.registrations_pool:
                    print("✅ PostgreSQL connection pool created for FR_REGISTRATIONS table")
            except Exception as e:
                print(f"❌ Failed to create PostgreSQL connection pool: {e}")
                print("⚠️ Falling back to SQLite for FR_REGISTRATIONS table")
                self.use_postgres_for_registrations = False
                self.registrations_pool = None
        else:
            print(f"🔌 FR_REGISTRATIONS table: Using SQLite ({self.dbname})")
            self.registrations_pool = None

        self.create_database()
        self.create_table_credentials()
        self.create_table_registrations()
        self.auto_migrate_old_tables()  # Automatically migrate data from old tables
        self.insert_default_credentials()

    @property
    def credentials_placeholder(self):
        """Return SQL placeholder for CREDENTIALS table (always SQLite = ?)"""
        return '?'

    @property
    def registrations_placeholder(self):
        """Return SQL placeholder for FR_REGISTRATIONS table (PostgreSQL = %s, SQLite = ?)"""
        return '%s' if self.use_postgres_for_registrations else '?'

    def connect_credentials(self):
        """Connect to SQLite for CREDENTIALS table operations"""
        self.con = sqlite3.connect(self.dbname)
        self.cursor = self.con.cursor()

    def connect_registrations(self):
        """Connect to appropriate database for FR_REGISTRATIONS table operations"""
        if self.use_postgres_for_registrations:
            # Get connection from PostgreSQL pool
            self.con = self.registrations_pool.getconn()
            self.cursor = self.con.cursor()
        else:
            # Use SQLite
            self.con = sqlite3.connect(self.dbname)
            self.cursor = self.con.cursor()

    def close_credentials(self):
        """Close CREDENTIALS table connection (SQLite)"""
        if hasattr(self, 'con') and self.con:
            self.con.close()

    def close_registrations(self):
        """Close FR_REGISTRATIONS table connection and return to pool if PostgreSQL"""
        if hasattr(self, 'con') and self.con:
            if self.use_postgres_for_registrations and self.registrations_pool:
                # Return connection to pool
                self.registrations_pool.putconn(self.con)
            else:
                # Close SQLite connection
                self.con.close()

    def create_database(self):
        """Initialize database files/connections"""
        # Create SQLite file if it doesn't exist
        self.connect_credentials()
        print('SQLite database file created/verified')
        self.close_credentials()

        # Test PostgreSQL connection if being used
        if self.use_postgres_for_registrations:
            try:
                self.connect_registrations()
                print('PostgreSQL connection verified')
                self.close_registrations()
            except Exception as e:
                print(f"⚠️ PostgreSQL connection test failed: {e}")
                print("⚠️ Falling back to SQLite for FR_REGISTRATIONS table")
                self.use_postgres_for_registrations = False

    def auto_migrate_old_tables(self):
        """
        Automatically migrate data from old tables (ADMIN, PERSON) to new tables on startup.
        This runs after new tables are created but before data operations begin.
        """
        try:
            self.connect_credentials()
            cursor = self.cursor

            # Get list of tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            # Migrate ADMIN → CREDENTIALS
            if 'ADMIN' in tables and 'CREDENTIALS' in tables:
                cursor.execute("SELECT COUNT(*) FROM CREDENTIALS")
                cred_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM ADMIN")
                admin_count = cursor.fetchone()[0]

                if cred_count == 0 and admin_count > 0:
                    print(f"🔄 Auto-migrating {admin_count} records: ADMIN → CREDENTIALS")
                    cursor.execute("INSERT INTO CREDENTIALS SELECT * FROM ADMIN")
                    self.con.commit()

            # Migrate PERSON → FR_REGISTRATIONS
            if 'PERSON' in tables:
                # Check if FR_REGISTRATIONS exists and get counts
                cursor.execute("SELECT COUNT(*) FROM FR_REGISTRATIONS") if 'FR_REGISTRATIONS' in tables else None
                fr_count = cursor.fetchone()[0] if 'FR_REGISTRATIONS' in tables else 0

                cursor.execute("SELECT COUNT(*) FROM PERSON")
                person_count = cursor.fetchone()[0]

                if person_count > 0 and fr_count == 0:
                    print(f"🔄 Auto-migrating {person_count} records: PERSON → FR_REGISTRATIONS")

                    # Check if PERSON has Registration or Registration_id column
                    cursor.execute("PRAGMA table_info(PERSON)")
                    columns = {col[1]: col for col in cursor.fetchall()}

                    if 'Registration' in columns and 'Registration_id' not in columns:
                        # Need to rename column during migration
                        cursor.execute('''
                            INSERT INTO FR_REGISTRATIONS (Id, Name, Title, Registration_id)
                            SELECT Id, Name, Title, Registration FROM PERSON
                        ''')
                    else:
                        # Column names match
                        cursor.execute('''
                            INSERT INTO FR_REGISTRATIONS (Id, Name, Title, Registration_id)
                            SELECT Id, Name, Title, Registration_id FROM PERSON
                        ''')
                    self.con.commit()

            self.close_credentials()

            # Now cleanup old tables (safe because data has been migrated)
            if 'ADMIN' in tables or 'PERSON' in tables:
                self.cleanup_old_tables()

        except Exception as e:
            print(f"⚠️ Auto-migration error: {e}")
            import traceback
            traceback.print_exc()

    def cleanup_old_tables(self):
        """
        Remove old table names (ADMIN, PERSON) if they still exist in SQLite.

        WARNING: This should only be called by migration scripts AFTER data has been copied.
        This is NOT called automatically to prevent data loss.
        """
        # Only cleanup SQLite - PostgreSQL is new and won't have old tables
        try:
            self.connect_credentials()
            cursor = self.cursor

            # Check for old tables
            cursor.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = [row[0] for row in cursor.fetchall()]

            # ADMIN table cleanup
            if 'ADMIN' in tables and 'CREDENTIALS' in tables:
                cursor.execute("SELECT COUNT(*) FROM CREDENTIALS")
                cred_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM ADMIN")
                admin_count = cursor.fetchone()[0]

                if cred_count > 0 or admin_count == 0:
                    cursor.execute("DROP TABLE ADMIN")
                    self.con.commit()
                else:
                    print("⚠️ Skipping ADMIN table cleanup - data loss prevention")

            # PERSON table cleanup
            if 'PERSON' in tables and 'FR_REGISTRATIONS' in tables:
                cursor.execute("SELECT COUNT(*) FROM FR_REGISTRATIONS")
                fr_count = cursor.fetchone()[0]
                cursor.execute("SELECT COUNT(*) FROM PERSON")
                person_count = cursor.fetchone()[0]

                if fr_count > 0 or person_count == 0:
                    cursor.execute("DROP TABLE PERSON")
                    self.con.commit()
                else:
                    print("⚠️ Skipping PERSON table cleanup - data loss prevention")

            self.close_credentials()
        except Exception as e:
            print(f"⚠️ Cleanup error (SQLite): {e}")

    def create_table_credentials(self):
        """Create CREDENTIALS table in SQLite"""
        self.connect_credentials()
        command = '''CREATE TABLE IF NOT EXISTS CREDENTIALS(Name TEXT, ID TEXT, Password TEXT)'''
        try:
            self.cursor.execute(command)
            self.con.commit()
            print('CREDENTIALS table created/verified in SQLite')
        except Exception as e:
            print(f"Error creating CREDENTIALS table: {e}")
        finally:
            self.close_credentials()

    def create_table_registrations(self):
        """Create FR_REGISTRATIONS table in PostgreSQL or SQLite"""
        self.connect_registrations()
        command = f'''CREATE TABLE IF NOT EXISTS FR_REGISTRATIONS(
            Id TEXT PRIMARY KEY,
            Name TEXT,
            Title TEXT,
            Registration_id TEXT UNIQUE
        )'''
        try:
            self.cursor.execute(command)
            self.con.commit()
            db_type = "PostgreSQL" if self.use_postgres_for_registrations else "SQLite"
            print(f'FR_REGISTRATIONS table created/verified in {db_type}')
        except Exception as e:
            print(f"Error creating FR_REGISTRATIONS table: {e}")
        finally:
            self.close_registrations()

    def __del__(self):
        """Cleanup connection pool on object destruction"""
        if hasattr(self, 'use_postgres_for_registrations') and self.use_postgres_for_registrations:
            if hasattr(self, 'registrations_pool') and self.registrations_pool:
                try:
                    self.registrations_pool.closeall()
                    print("✅ PostgreSQL connection pool closed")
                except:
                    pass

    
    
    def insert_default_credentials(self, username="admin",ID_="admin",password='1234'):
        """Insert default admin into CREDENTIALS table (SQLite)"""
        self.connect_credentials()
        try:
            command = f"SELECT * FROM CREDENTIALS WHERE ID = {self.credentials_placeholder}"
            self.cursor.execute(command, (ID_,))
            rows = self.cursor.fetchall()
            if rows:
                pass
            else:
                command_insertvalue = f"insert into CREDENTIALS (Name,ID,Password) values ({self.credentials_placeholder}, {self.credentials_placeholder},{self.credentials_placeholder})"
                try:
                    self.cursor.execute(command_insertvalue, (username,ID_,password))
                    self.con.commit()
                    print('Default admin created in SQLite')
                except Exception as e:
                    print(f"Error inserting admin: {e}")
        finally:
            self.close_credentials()

    def insert_into_registrations(self, id_, name, title, registration_id):
        """Insert registration into FR_REGISTRATIONS table (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            command = f"SELECT * FROM FR_REGISTRATIONS WHERE (Id) = {self.registrations_placeholder} "
            self.cursor.execute(command, (id_,))
            rows = self.cursor.fetchall()
            if rows:
                return "Id already exist"
            command_insertvalue = f"insert into FR_REGISTRATIONS (Id,Name,Title,Registration_id) values ({self.registrations_placeholder}, {self.registrations_placeholder}, {self.registrations_placeholder}, {self.registrations_placeholder})"
            self.cursor.execute(command_insertvalue, (id_,name,title,registration_id))
            self.con.commit()
            return "New registration Added"
        except Exception as e:
            print(f"Error inserting registration: {e}")
            return f"Error: {e}"
        finally:
            self.close_registrations()
    
    
      
    
    
    
    def authenticate_admin(self,id_,upassword):
        """Authenticate admin from CREDENTIALS table (SQLite)"""
        self.connect_credentials()
        try:
            command = f"SELECT * FROM CREDENTIALS WHERE (ID) = {self.credentials_placeholder} "
            self.cursor.execute(command, (id_,))
            rows = self.cursor.fetchall()
            if rows:
                row = rows[0]
                cpassword = row[2]
                if upassword==cpassword:
                    return 'Login Success'
                else:
                    return 'Wrong password Try again'
            else:
                return 'Id not found'
        finally:
            self.close_credentials()

    def get_id_from_name(self, name):
        """Get person ID from name (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            command = f"SELECT * FROM FR_REGISTRATIONS WHERE (Name) = {self.registrations_placeholder} "
            self.cursor.execute(command, (name,))
            rows = self.cursor.fetchall()
            if rows:
                row = rows[0]
                id_ = row[0]
                return id_
            return None
        finally:
            self.close_registrations()

    def get_name_from_id(self, id_):
        """Get person name from ID (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            command = f"SELECT * FROM FR_REGISTRATIONS WHERE (Id) = {self.registrations_placeholder} "
            self.cursor.execute(command, (id_,))
            rows = self.cursor.fetchall()
            if rows:
                row = rows[0]
                name = row[1]
                return name
            return None
        finally:
            self.close_registrations()

    def get_person_name(self, id_):
        """Get person name from ID (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            command = f"SELECT * FROM FR_REGISTRATIONS WHERE (Id) = {self.registrations_placeholder} "
            self.cursor.execute(command, (id_,))
            rows = self.cursor.fetchall()
            if rows:
                row = rows[0]
                name = row[1]
                return name
            return None
        finally:
            self.close_registrations()

    def get_person_title(self, id_):
        """Get person title from ID (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            command = f"SELECT * FROM FR_REGISTRATIONS WHERE (Id) = {self.registrations_placeholder} "
            self.cursor.execute(command, (id_,))
            rows = self.cursor.fetchall()
            if rows:
                row = rows[0]
                title = row[2]
                return title
            return None
        finally:
            self.close_registrations()

    def get_registration_id(self, id_):
        """Get registration ID from person ID (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            command = f"SELECT * FROM FR_REGISTRATIONS WHERE (Id) = {self.registrations_placeholder} "
            self.cursor.execute(command, (id_,))
            rows = self.cursor.fetchall()
            if rows:
                row = rows[0]
                registration_id = row[3]
                return registration_id
            return None
        finally:
            self.close_registrations()

    def check_registration_exists(self, registration_id):
        """Check if a registration ID already exists in the database (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            command = f"SELECT Id FROM FR_REGISTRATIONS WHERE Registration_id = {self.registrations_placeholder}"
            self.cursor.execute(command, (registration_id,))
            rows = self.cursor.fetchall()
            return len(rows) > 0
        finally:
            self.close_registrations()

    def get_registrations_list(self):
        """Get list of all person IDs (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            command = "SELECT * FROM FR_REGISTRATIONS "
            self.cursor.execute(command)
            rows = self.cursor.fetchall()
            registrations_list=[]
            if rows:
                registrations_list=[row[0] for row in rows]
            return registrations_list
        finally:
            self.close_registrations()

    def get_admin_name(self, id_):
        """Get admin name from ID (SQLite)"""
        self.connect_credentials()
        try:
            command = f"SELECT * FROM CREDENTIALS WHERE (ID) = {self.credentials_placeholder} "
            self.cursor.execute(command, (id_,))
            rows = self.cursor.fetchall()
            if rows:
                row = rows[0]
                name = row[0]
                return name
            return None
        finally:
            self.close_credentials()
    
    

        
    def change_admin_id_password(self,oldadminid,oldadminpass,newadminid,newadminpass,newadminpassconf):
        """Change admin password (SQLite)"""
        status=self.authenticate_admin(oldadminid,oldadminpass)
        if status=='Login Success':
            if newadminpass==newadminpassconf:
                status=self.delete_credentials(oldadminid)
                if status==False:
                    return 'Update error'
                self.insert_default_credentials('Admin',newadminid,newadminpass)
                return 'Admin id password updated'
            else:
                return 'confirm password not matched'
        else:
            return 'previous admin id or password not matched'

    def get_all_registration_ids(self,):
        """Get all registration IDs (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            df = pd.read_sql_query(f"SELECT * FROM FR_REGISTRATIONS", self.con)
            return list(df['Id'].values)
        finally:
            self.close_registrations()
    def get_attendance_data(self,):
        """Get all attendance data (if ATTENDANCE table exists, uses SQLite)"""
        self.connect_credentials()  # If ATTENDANCE table exists, it's in SQLite
        try:
            df = pd.read_sql_query(f"SELECT * FROM ATTENDANCE", self.con)
            return df
        finally:
            self.close_credentials()

    def total_registrations(self)->str:
        """Get total number of registrations (PostgreSQL or SQLite)"""
        self.connect_registrations()
        try:
            df = pd.read_sql_query(f"SELECT * FROM FR_REGISTRATIONS", self.con)
            return str(len(df))
        finally:
            self.close_registrations()

    def total_data_attendance(self)->str:
        """Get total attendance records (if ATTENDANCE table exists, uses SQLite)"""
        self.connect_credentials()  # If ATTENDANCE table exists, it's in SQLite
        try:
            df = pd.read_sql_query(f"SELECT * FROM ATTENDANCE", self.con)
            return str(len(df))
        finally:
            self.close_credentials()
    
    def delete_registration(self, id_):
        """
        Delete registration from FR_REGISTRATIONS table (PostgreSQL or SQLite).
        Returns True if database deletion succeeds, regardless of file deletion status.
        File deletion should be handled by the API endpoint via face_recognizer.remove_person()
        """
        name=self.get_person_name(id_)
        self.connect_registrations()
        command = f"DELETE FROM FR_REGISTRATIONS WHERE Id={self.registrations_placeholder} "
        try:
            self.cursor.execute(command, (id_,))
            self.con.commit()
            # Database deletion succeeded - return True
            # (File deletion is handled separately by face_recognizer.remove_person)
            return True
        except Exception as e:
            print(f"⚠️ Failed to delete registration {id_} from database: {e}")
            return False
        finally:
            self.close_registrations()

    def delete_credentials(self, id_):
        """Delete admin from CREDENTIALS table (SQLite)"""
        self.connect_credentials()
        command = f"DELETE FROM CREDENTIALS WHERE ID={self.credentials_placeholder} "
        try:
            self.cursor.execute(command, (id_,))
            self.con.commit()
            return True
        except Exception as e:
            print(f"⚠️ Failed to delete credentials {id_}: {e}")
            return False
        finally:
            self.close_credentials() 
    def delete_datbase(self):
        """Drop database (SQLite only)"""
        self.connect_credentials()
        command = "DROP DATABASE "+self.dbname
        self.cursor.execute(command)
        self.con.commit()
        print ('Success! DATABASE Deleted')
        self.close_credentials()

    def get_last_entry_time(self, personid):
        """Get last attendance entry time for person (if ATTENDANCE table exists, uses SQLite)"""
        self.connect_credentials()  # If ATTENDANCE table exists, it's in SQLite
        try:
            command = f"SELECT * FROM ATTENDANCE WHERE (Id) = {self.credentials_placeholder} and (Date) = {self.credentials_placeholder} and (Status) = {self.credentials_placeholder}"
            cdate,ctime,cdtime=get_current_datetime()
            self.cursor.execute(command, (str(personid),cdate,'Present'))
            rows = self.cursor.fetchall()
            if rows:
                row = rows[-1]
                time = str(row[5])
                return time
            return None
        finally:
            self.close_credentials()

    def get_filtered_report(self,sid,smonth,syear):
        """Get filtered attendance report (if ATTENDANCE table exists, uses SQLite)"""
        self.connect_credentials()  # If ATTENDANCE table exists, it's in SQLite
        try:
            if sid=="":
                df = pd.read_sql_query(f"SELECT * FROM ATTENDANCE ", self.con)
                return df
            else:
                df = pd.read_sql_query(f"SELECT * FROM ATTENDANCE WHERE Id = '{sid}'", self.con)
                #filter by year
                df = df[df['Date'].str[-4:] == syear]
                #filter by month
                df = df[df['Date'].str[-7:-5] == month2number[smonth]]
                return df
        finally:
            self.close_credentials()

    



