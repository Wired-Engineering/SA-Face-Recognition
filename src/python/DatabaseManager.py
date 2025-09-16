import sqlite3
import pandas as pd
from utils import *
import os
month2number={'JAN':'01','FEB':'02','MAR':'03','APR':'04','MAY':'05','JUN':'06','JUL':'07','AUG':'08','SEP':'09','OCT':'10','NOV':'11','DEC':'12'}
class MySqlite3Manager:
    def __init__(self):
        self.dbname="system/Attendance.db"
        self.create_database()
        self.create_table_admin()
        self.create_table_person()
        self.insert_into_admin()
    def connect(self):
        self.con=sqlite3.connect(self.dbname)
        self.cursor=self.con.cursor() 
    def connect_link(self):
        self.con=sqlite3.connect(self.dbname)
        self.cursor=self.con.cursor()  
        print('database created')
    def create_database(self):
        self.connect_link()
        self.con.close()
    
    
    def create_table_admin(self):
        self.connect()
        command = '''CREATE TABLE ADMIN(Name TEXT, ID TEXT,Password TEXT)'''
        try:
            self.cursor.execute(command)
            self.con.commit()
            print('Admin table created')
        except Exception as e:
            print(e)
    def create_table_person(self):
        self.connect()
        command = f'''CREATE TABLE PERSON(Id TEXT, Name TEXT)'''
        try:
            self.cursor.execute(command)
            self.con.commit()
            print('Person table created')
        except Exception as e:
            print(e)

    
    
    def insert_into_admin(self, username="admin",ID_="admin",password='1234'):
        self.connect()
        command = f"SELECT * FROM ADMIN WHERE ID = ?"
        self.cursor.execute(command, (ID_,))
        rows = self.cursor.fetchall()
        if rows:
            pass
        else:
            command_insertvalue = "insert into ADMIN (Name,ID,Password) values (?, ?,?)"
            try:
                self.cursor.execute(command_insertvalue, (username,ID_,password))
                self.con.commit()
                self.con.close()
                print('data entered in admin table')
            except Exception as e:
                print(e)
    def insert_into_person(self, id_, name):
        self.connect()
        command = "SELECT * FROM PERSON WHERE (Id) = ? "
        self.cursor.execute(command, (id_,))
        rows = self.cursor.fetchall()
        if rows:
            return "Id already exist"
        command_insertvalue = f"insert into PERSON (Id,Name) values (?, ?)"
        try:
            self.cursor.execute(command_insertvalue, (id_,name))
            self.con.commit()
            self.con.close()
            return "New person Added"
        except Exception as e:
            print(e)
    
    
      
    
    
    
    def authenticate_admin(self,id_,upassword):
        self.connect()
        command = "SELECT * FROM ADMIN WHERE (ID) = ? "
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
   
    def get_id_from_name(self, name):
        self.connect()
        command = "SELECT * FROM PERSON WHERE (Name) = ? "
        self.cursor.execute(command, (name,))
        rows = self.cursor.fetchall()
        if rows:
            row = rows[0]
            id_ = row[0]
            return id_
        return None
    
    def get_name_from_id(self, id_):
        self.connect()
        command = "SELECT * FROM PERSON WHERE (Id) = ? "
        self.cursor.execute(command, (id_,))
        rows = self.cursor.fetchall()
        if rows:
            row = rows[0]
            name = row[1]
            return name
        return None
    
    def get_person_name(self, id_):
        self.connect()
        command = "SELECT * FROM PERSON WHERE (Id) = ? "
        self.cursor.execute(command, (id_,))
        rows = self.cursor.fetchall()
        if rows:
            row = rows[0]
            name = row[1]
            return name
        return None
    
    def get_person_list(self):
        self.connect()
        command = "SELECT * FROM PERSON "
        self.cursor.execute(command)
        rows = self.cursor.fetchall()
        person_list=[]
        if rows:
            person_list=[row[0] for row in rows]
        return person_list
    def get_admin_name(self, id_):
        self.connect()
        command = "SELECT * FROM ADMIN WHERE (ID) = ? "
        self.cursor.execute(command, (id_,))
        rows = self.cursor.fetchall()
        if rows:
            row = rows[0]
            name = row[1]
            return name
        return None
    
    

        
    def change_admin_id_password(self,oldadminid,oldadminpass,newadminid,newadminpass,newadminpassconf):
        status=self.authenticate_admin(oldadminid,oldadminpass)
        if status=='Login Success':
            if newadminpass==newadminpassconf:
                status=self.delete_data_from_admin(oldadminid)
                if status==False:
                    return 'Update error'
                self.insert_into_admin('Admin',newadminid,newadminpass)
                return 'Admin id password updated'
            else:
                return 'confirm password not matched'
        else:
            return 'previous admin id or password not matched'
    

    def get_all_person_ids(self,):
        self.connect()
        df = pd.read_sql_query(f"SELECT * FROM PERSON", self.con)
        self.con.close()
        return list(df['Id'].values)
    def get_attendance_data(self,):
        self.connect()
        df = pd.read_sql_query(f"SELECT * FROM ATTENDANCE", self.con)
        return df
        
    def total_person(self)->str:
        self.connect()
        df = pd.read_sql_query(f"SELECT * FROM PERSON", self.con)
        self.con.close()
        return str(len(df))
    def total_data_attendance(self)->str:
        self.connect()
        df = pd.read_sql_query(f"SELECT * FROM ATTENDANCE", self.con)
        self.con.close()
        return str(len(df))
    
    def delete_data_from_person(self, id_):
        face_deleted=False
        name=self.get_person_name(id_)
        self.connect()
        command = "DELETE FROM PERSON WHERE Id=? "
        try:
            self.cursor.execute(command, (id_,))
            self.con.commit()
            self.con.close()
            try:
                os.remove(f'images/{id_}.png')
                face_deleted=True
            except Exception as e:
                print(e)
    
            if face_deleted==True:
                return True
            else:
                return False
        except:
            return False 
    def delete_data_from_admin(self, id_):
        self.connect()
        command = "DELETE FROM ADMIN WHERE ID=? "
        try:
            self.cursor.execute(command, (id_,))
            self.con.commit()
            self.con.close()
            return True
        except:
            return False 
    def delete_datbase(self):
        self.connect()
        command = "DROP DATABASE "+self.dbname
        self.cursor.execute(command)
        self.con.commit()
        print ('Success! DATABASE Deleted')
    def get_last_entry_time(self, personid):
        self.con=sqlite3.connect(self.dbname)
        cursor = self.con.cursor()
        command = "SELECT * FROM ATTENDANCE WHERE (Id) = ? and (Date) = ? and (Status) = ?"
        cdate,ctime,cdtime=get_current_datetime()
        cursor.execute(command, (str(personid),cdate,'Present'))
        rows = cursor.fetchall()
        if rows:
            row = rows[-1]
            time = str(row[5])
            return time
        return None
    def get_filtered_report(self,sid,smonth,syear):
        self.connect()
        if sid=="":
            df = pd.read_sql_query(f"SELECT * FROM ATTENDANCE ", self.con)
            self.con.close()
            return df
        else:
            df = pd.read_sql_query(f"SELECT * FROM ATTENDANCE WHERE Id = '{sid}'", self.con)
            self.con.close()
            #filter by year
            df = df[df['Date'].str[-4:] == syear]
            #filter by month
            df = df[df['Date'].str[-7:-5] == month2number[smonth]]
            return df

    



